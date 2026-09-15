"""Header-based single sign-on for Okta Access Gateway (OAG) and similar reverse proxies.

OAG authenticates the user against Okta, then forwards the request with identity headers.
PeopleSoft reads the user ID from a header (its OAM/OAG integration uses PS_SSO_UID / OAM_REMOTE_USER)
through Signon PeopleCode. This module does the same:

  1. Trust check   - request must come from a trusted proxy (PS_SSO_TRUSTED_PROXIES) and/or carry the
                     shared secret header OAG is configured to inject (PS_SSO_SECRET_HEADER / PS_SSO_SECRET).
  2. Identity      - user ID from PS_SSO_HEADER (default PS_SSO_UID, fallbacks OAM_REMOTE_USER, REMOTE_USER),
                     optional email / display name / groups headers.
  3. Resolution    - match a PeopleSoft user profile (PSOPRDEFN.OPRID or EMAILID), else a worker's business
                     email; optionally create the profile just-in-time (PS_SSO_AUTOCREATE).
  4. Authorization - roles = PSROLEUSER rows + groups header. Admin roles may change data; others are read-only.
"""
import ipaddress
from dataclasses import dataclass, field

from . import db
from .config import config

FALLBACK_UID_HEADERS = ("OAM_REMOTE_USER", "REMOTE_USER", "X-Forwarded-User")


class SSOError(Exception):
    def __init__(self, status, title, detail):
        super().__init__(detail)
        self.status, self.title, self.detail = status, title, detail


@dataclass
class Principal:
    oprid: str
    name: str = ""
    email: str = ""
    emplid: str = ""
    roles: list = field(default_factory=list)
    is_admin: bool = False
    source: str = "header"
    header_name: str = ""
    created: bool = False

    def as_dict(self):
        return {"oprid": self.oprid, "name": self.name, "email": self.email, "emplid": self.emplid, "roles": self.roles,
                "isAdmin": self.is_admin, "source": self.source, "headerName": self.header_name, "createdJustInTime": self.created}


def _get_header(headers, name):
    if not name:
        return None
    v = headers.get(name)
    if v is None:
        # Proxies commonly normalise underscores to dashes.
        v = headers.get(name.replace("_", "-"))
    return v.strip() if isinstance(v, str) and v.strip() else None


def trusted_source(headers, client_ip):
    """True when the request may carry SSO headers: matches trusted proxies and/or the shared secret."""
    secret_ok = True
    if config.sso_secret:
        secret_ok = _get_header(headers, config.sso_secret_header) == config.sso_secret
    proxy_ok = True
    nets = [n.strip() for n in config.sso_trusted_proxies.split(",") if n.strip()]
    if nets:
        proxy_ok = False
        try:
            ip = ipaddress.ip_address(client_ip)
            for n in nets:
                if ip in ipaddress.ip_network(n, strict=False):
                    proxy_ok = True
                    break
        except ValueError:
            proxy_ok = False
    return secret_ok and proxy_ok


def identity_from_headers(headers):
    """Return (uid, header_name) or (None, None)."""
    for name in (config.sso_header, *FALLBACK_UID_HEADERS):
        v = _get_header(headers, name)
        if v:
            return v, name
    return None, None


def received_headers(headers):
    """Diagnostic view of the SSO-relevant headers (secret masked) for the sign-on status page."""
    names = [config.sso_header, *FALLBACK_UID_HEADERS, config.sso_email_header, config.sso_name_header,
             config.sso_groups_header, config.sso_secret_header]
    out = {}
    for n in names:
        if not n:
            continue
        v = _get_header(headers, n)
        if v is not None:
            out[n] = "********" if n == config.sso_secret_header else v
    return out


def resolve(conn, uid, email=None, name=None, groups=None):
    """Map a header identity to a PeopleSoft user profile. Raises SSOError(403) if unknown and no autocreate."""
    row = db.row(conn, "SELECT * FROM PSOPRDEFN WHERE LOWER(OPRID)=LOWER(?) OR (EMAILID<>'' AND LOWER(EMAILID)=LOWER(?))", (uid, email or uid))
    emplid = ""
    created = False
    if row is None:
        w = db.row(conn, "SELECT EMPLID FROM PS_EMAIL_ADDRESSES WHERE LOWER(EMAIL_ADDR)=LOWER(?)", (email or uid,))
        emplid = w["EMPLID"] if w else ""
        if not config.sso_autocreate and not emplid:
            raise SSOError(403, "User ID not found", f"{uid} authenticated at the gateway but has no PeopleSoft user profile. "
                           "Provision the user (SCIM or User Profiles) or set PS_SSO_AUTOCREATE=1.")
        person = db.row(conn, "SELECT * FROM PS_PERSONAL_DATA WHERE EMPLID=?", (emplid,)) if emplid else None
        ts = db.now_iso()
        first, last = (person["FIRST_NAME"], person["LAST_NAME"]) if person else ((name or uid).split(" ")[0], " ".join((name or "").split(" ")[1:]))
        conn.execute("""INSERT INTO PSOPRDEFN (OPRID, SCIM_ID, EMPLID, OPRDEFNDESC, EMAILID, FIRST_NAME, LAST_NAME, ACCTLOCK, EXTERNAL_ID, RAW_JSON, CREATED_DTTM, LASTUPDDTTM)
                        VALUES (?,?,?,?,?,?,?,0,?,'{}',?,?)""",
                     (uid, f"sso-{uid}", emplid, name or (person["NAME_DISPLAY"] if person else uid), email or (uid if "@" in uid else ""),
                      first, last, f"oag:{uid}", ts, ts))
        conn.executemany("INSERT OR IGNORE INTO PSROLEUSER VALUES (?,?)", [(uid, "PeopleSoft User"), (uid, "Employee")])
        db.audit(conn, emplid, "SSO_JIT_CREATE", f"User profile {uid} created just-in-time from gateway headers", uid, "OAG")
        conn.commit()
        row = db.row(conn, "SELECT * FROM PSOPRDEFN WHERE OPRID=?", (uid,))
        created = True
    if row["ACCTLOCK"]:
        raise SSOError(403, "Account locked", f"User profile {row['OPRID']} is locked (ACCTLOCK=1). Reactivate it in Okta.")
    roles = [r["ROLENAME"] for r in db.rows(conn, "SELECT ROLENAME FROM PSROLEUSER WHERE ROLEUSER=?", (row["OPRID"],))]
    for g in groups or []:
        if g and g not in roles:
            roles.append(g)
    admin_roles = {r.strip().lower() for r in config.sso_admin_roles.split(",") if r.strip()}
    p = Principal(oprid=row["OPRID"], name=row["OPRDEFNDESC"] or row["OPRID"], email=row["EMAILID"] or "", emplid=row["EMPLID"] or "",
                  roles=roles, is_admin=any(r.lower() in admin_roles for r in roles), created=created)
    # Record the sign-on (at most once every few minutes, since header auth has no session)
    last = row["LASTSIGNONDTTM"] if "LASTSIGNONDTTM" in row.keys() else None
    now = db.now_iso()
    if not last or last[:16] != now[:16]:
        conn.execute("UPDATE PSOPRDEFN SET LASTSIGNONDTTM=? WHERE OPRID=?", (now, row["OPRID"]))
        if not last or last[:13] != now[:13]:
            db.audit(conn, p.emplid, "SSO_SIGNON", f"{row['OPRID']} signed on via gateway header", row["OPRID"], "OAG")
        conn.commit()
    return p


def authenticate(conn, headers, client_ip):
    """Full flow. Returns a Principal or raises SSOError."""
    if not trusted_source(headers, client_ip):
        raise SSOError(401, "Sign-on required", "Request did not come through the trusted gateway (proxy address or shared secret check failed).")
    uid, hdr = identity_from_headers(headers)
    if not uid:
        raise SSOError(401, "Sign-on required", f"No identity header present. Access this application through Okta Access Gateway, "
                       f"which injects {config.sso_header} after Okta sign-in.")
    groups_raw = _get_header(headers, config.sso_groups_header) or ""
    groups = [g.strip() for g in groups_raw.replace(";", ",").split(",") if g.strip()]
    p = resolve(conn, uid, _get_header(headers, config.sso_email_header), _get_header(headers, config.sso_name_header), groups)
    p.header_name = hdr
    return p
