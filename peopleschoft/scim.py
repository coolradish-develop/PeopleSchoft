"""SCIM 2.0 server (inbound): Okta provisions users *into* PeopleSoft user profiles (PSOPRDEFN).

Register this in Okta as a custom SCIM 2.0 app (header auth, Bearer PS_SCIM_TOKEN) with base URL
  <PS_PUBLIC_URL>/scim/v2
"""
import json
import re
import uuid

from . import db

CORE = "urn:ietf:params:scim:schemas:core:2.0:User"
ENT = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


class ScimError(Exception):
    def __init__(self, status, detail, scim_type=None):
        super().__init__(detail)
        self.status, self.detail, self.scim_type = status, detail, scim_type

    def body(self):
        b = {"schemas": [ERROR], "detail": self.detail, "status": str(self.status)}
        if self.scim_type:
            b["scimType"] = self.scim_type
        return b


def service_provider_config(base):
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": base + "/api-docs",
        "patch": {"supported": True}, "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200}, "changePassword": {"supported": False},
        "sort": {"supported": False}, "etag": {"supported": False},
        "authenticationSchemes": [{"type": "oauthbearertoken", "name": "OAuth Bearer Token",
                                   "description": "Authorization: Bearer <PS_SCIM_TOKEN>", "primary": True}],
        "meta": {"resourceType": "ServiceProviderConfig", "location": base + "/scim/v2/ServiceProviderConfig"},
    }


def resource_types(base):
    return _list([{"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"], "id": "User", "name": "User",
                   "endpoint": "/Users", "schema": CORE, "schemaExtensions": [{"schema": ENT, "required": False}],
                   "meta": {"resourceType": "ResourceType", "location": base + "/scim/v2/ResourceTypes/User"}},
                  {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"], "id": "Group", "name": "Group",
                   "endpoint": "/Groups", "schema": "urn:ietf:params:scim:schemas:core:2.0:Group",
                   "meta": {"resourceType": "ResourceType", "location": base + "/scim/v2/ResourceTypes/Group"}}])


def schemas(base):
    attr = lambda n, t="string", multi=False, req=False: {"name": n, "type": t, "multiValued": multi, "required": req,  # noqa: E731
                                                          "caseExact": False, "mutability": "readWrite", "returned": "default", "uniqueness": "none"}
    return _list([
        {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Schema"], "id": CORE, "name": "User", "description": "PeopleSoft user profile (PSOPRDEFN)",
         "attributes": [attr("userName", req=True), attr("name", "complex"), attr("displayName"), attr("active", "boolean"),
                        attr("emails", "complex", multi=True), attr("externalId"), attr("roles", "complex", multi=True)],
         "meta": {"resourceType": "Schema", "location": base + "/scim/v2/Schemas/" + CORE}},
        {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Schema"], "id": ENT, "name": "EnterpriseUser", "description": "Enterprise extension",
         "attributes": [attr("employeeNumber"), attr("department"), attr("manager", "complex")],
         "meta": {"resourceType": "Schema", "location": base + "/scim/v2/Schemas/" + ENT}},
    ])


def _list(resources, start=1, total=None):
    return {"schemas": [LIST], "totalResults": total if total is not None else len(resources),
            "startIndex": start, "itemsPerPage": len(resources), "Resources": resources}


# ---------------------------------------------------------------------- storage <-> SCIM
def to_scim(conn, r, base):
    raw = json.loads(r["RAW_JSON"] or "{}")
    ent = dict(raw.get(ENT) or {})
    if r["EMPLID"]:
        ent["employeeNumber"] = r["EMPLID"]
    roles = [{"value": x["ROLENAME"], "primary": False} for x in conn.execute("SELECT ROLENAME FROM PSROLEUSER WHERE ROLEUSER=?", (r["OPRID"],))]
    out = {
        "schemas": [CORE, ENT], "id": r["SCIM_ID"], "externalId": r["EXTERNAL_ID"], "userName": r["OPRID"],
        "name": {"givenName": r["FIRST_NAME"], "familyName": r["LAST_NAME"], "formatted": r["OPRDEFNDESC"]},
        "displayName": r["OPRDEFNDESC"], "active": not r["ACCTLOCK"],
        "emails": [{"value": r["EMAILID"], "type": "work", "primary": True}] if r["EMAILID"] else [],
        "roles": roles, ENT: ent,
        "meta": {"resourceType": "User", "created": r["CREATED_DTTM"], "lastModified": r["LASTUPDDTTM"],
                 "location": f"{base}/scim/v2/Users/{r['SCIM_ID']}"},
    }
    for k in ("title", "nickName", "phoneNumbers", "locale", "timezone", "preferredLanguage", "userType"):
        if k in raw:
            out[k] = raw[k]
    return out


def _link_emplid(conn, body):
    emplid = (body.get(ENT) or {}).get("employeeNumber")
    if emplid and db.row(conn, "SELECT 1 FROM PS_PERSONAL_DATA WHERE EMPLID=?", (emplid,)):
        return emplid
    for e in body.get("emails") or []:
        v = (e or {}).get("value")
        if v:
            r = db.row(conn, "SELECT EMPLID FROM PS_EMAIL_ADDRESSES WHERE LOWER(EMAIL_ADDR)=LOWER(?)", (v,))
            if r:
                return r["EMPLID"]
    r = db.row(conn, "SELECT EMPLID FROM PS_EMAIL_ADDRESSES WHERE LOWER(EMAIL_ADDR)=LOWER(?)", (body.get("userName") or "",))
    return r["EMPLID"] if r else ""


def _fields(body):
    name = body.get("name") or {}
    emails = body.get("emails") or []
    primary = next((e.get("value") for e in emails if e.get("primary")), None) or (emails[0].get("value") if emails else None)
    display = body.get("displayName") or name.get("formatted") or f"{name.get('givenName', '')} {name.get('familyName', '')}".strip()
    return {"FIRST_NAME": name.get("givenName") or "", "LAST_NAME": name.get("familyName") or "", "OPRDEFNDESC": display,
            "EMAILID": primary or body.get("userName") or "", "ACCTLOCK": 0 if body.get("active", True) else 1,
            "EXTERNAL_ID": body.get("externalId")}


def get_by_id(conn, scim_id):
    return db.row(conn, "SELECT * FROM PSOPRDEFN WHERE SCIM_ID=?", (scim_id,))


def _by_id_or_404(conn, scim_id):
    r = get_by_id(conn, scim_id)
    if not r:
        raise ScimError(404, f"User {scim_id} not found")
    return r


def list_users(conn, base, filt=None, start=1, count=100):
    where, params = "1=1", []
    if filt:
        m = re.match(r'^\s*(\w+(?:\.\w+)?)\s+eq\s+"([^"]*)"\s*$', filt, re.I)
        if not m:
            raise ScimError(400, f"Unsupported filter: {filt}", "invalidFilter")
        attr, val = m.group(1).lower(), m.group(2)
        col = {"username": "OPRID", "emails.value": "EMAILID", "externalid": "EXTERNAL_ID", "id": "SCIM_ID",
               "name.givenname": "FIRST_NAME", "name.familyname": "LAST_NAME"}.get(attr)
        if not col:
            raise ScimError(400, f"Unsupported filter attribute: {attr}", "invalidFilter")
        where, params = f"LOWER({col})=LOWER(?)", [val]
    total = conn.execute(f"SELECT COUNT(*) FROM PSOPRDEFN WHERE {where}", params).fetchone()[0]
    rows = db.rows(conn, f"SELECT * FROM PSOPRDEFN WHERE {where} ORDER BY OPRID LIMIT ? OFFSET ?", params + [count, max(start - 1, 0)])
    return _list([to_scim(conn, r, base) for r in rows], start, total)


def create_user(conn, body, base):
    username = body.get("userName")
    if not username:
        raise ScimError(400, "userName is required", "invalidValue")
    if db.row(conn, "SELECT 1 FROM PSOPRDEFN WHERE LOWER(OPRID)=LOWER(?)", (username,)):
        raise ScimError(409, f"User {username} already exists", "uniqueness")
    f = _fields(body)
    scim_id = str(uuid.uuid4())
    ts = db.now_iso()
    conn.execute("""INSERT INTO PSOPRDEFN (OPRID, SCIM_ID, EMPLID, OPRDEFNDESC, EMAILID, FIRST_NAME, LAST_NAME, ACCTLOCK, EXTERNAL_ID, RAW_JSON, CREATED_DTTM, LASTUPDDTTM)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (username, scim_id, _link_emplid(conn, body), f["OPRDEFNDESC"], f["EMAILID"], f["FIRST_NAME"], f["LAST_NAME"],
                  f["ACCTLOCK"], f["EXTERNAL_ID"], json.dumps(body), ts, ts))
    _set_roles(conn, username, body.get("roles"), default=True)
    db.audit(conn, _link_emplid(conn, body), "SCIM_CREATE", f"User profile {username} created by SCIM", "OKTA", "SCIM")
    conn.commit()
    return to_scim(conn, get_by_id(conn, scim_id), base)


def _set_roles(conn, oprid, roles, default=False):
    if roles is None:
        if default and not db.row(conn, "SELECT 1 FROM PSROLEUSER WHERE ROLEUSER=?", (oprid,)):
            conn.executemany("INSERT OR IGNORE INTO PSROLEUSER VALUES (?,?)", [(oprid, "PeopleSoft User"), (oprid, "Employee")])
        return
    conn.execute("DELETE FROM PSROLEUSER WHERE ROLEUSER=?", (oprid,))
    for r in roles:
        v = r.get("value") if isinstance(r, dict) else r
        if v:
            conn.execute("INSERT OR IGNORE INTO PSROLEUSER VALUES (?,?)", (oprid, v))


def replace_user(conn, scim_id, body, base):
    r = _by_id_or_404(conn, scim_id)
    username = body.get("userName") or r["OPRID"]
    f = _fields(body)
    conn.execute("DELETE FROM PSROLEUSER WHERE ROLEUSER=?", (r["OPRID"],)) if username != r["OPRID"] else None
    conn.execute("""UPDATE PSOPRDEFN SET OPRID=?, EMPLID=?, OPRDEFNDESC=?, EMAILID=?, FIRST_NAME=?, LAST_NAME=?, ACCTLOCK=?, EXTERNAL_ID=?, RAW_JSON=?, LASTUPDDTTM=?
                    WHERE SCIM_ID=?""",
                 (username, _link_emplid(conn, body) or r["EMPLID"], f["OPRDEFNDESC"], f["EMAILID"], f["FIRST_NAME"], f["LAST_NAME"],
                  f["ACCTLOCK"], f["EXTERNAL_ID"] or r["EXTERNAL_ID"], json.dumps(body), db.now_iso(), scim_id))
    _set_roles(conn, username, body.get("roles"), default=True)
    db.audit(conn, r["EMPLID"], "SCIM_REPLACE", f"User profile {username} replaced by SCIM (active={not f['ACCTLOCK']})", "OKTA", "SCIM")
    conn.commit()
    return to_scim(conn, get_by_id(conn, scim_id), base)


def patch_user(conn, scim_id, body, base):
    r = _by_id_or_404(conn, scim_id)
    current = to_scim(conn, r, base)
    for op in body.get("Operations") or []:
        kind = (op.get("op") or "").lower()
        path = op.get("path")
        value = op.get("value")
        if kind in ("replace", "add"):
            if not path:
                if not isinstance(value, dict):
                    raise ScimError(400, "value must be an object when path is omitted", "invalidValue")
                for k, v in value.items():
                    _apply_path(current, k, v)
            else:
                _apply_path(current, path, value)
        elif kind == "remove":
            if path:
                _apply_path(current, path, None)
        else:
            raise ScimError(400, f"Unsupported op {kind!r}", "invalidValue")
    return replace_user(conn, scim_id, current, base)


def _apply_path(doc, path, value):
    m = re.match(r'^emails\[type eq "(\w+)"\]\.value$', path)
    if m:
        emails = doc.setdefault("emails", [])
        for e in emails:
            if e.get("type") == m.group(1):
                e["value"] = value
                return
        emails.append({"type": m.group(1), "value": value, "primary": not emails})
        return
    if path.startswith(ENT):
        key = path.split(":")[-1]
        doc.setdefault(ENT, {})[key] = value
        return
    parts = path.split(".")
    target = doc
    for p in parts[:-1]:
        target = target.setdefault(p, {})
    if value is None:
        target.pop(parts[-1], None)
    else:
        target[parts[-1]] = value


def delete_user(conn, scim_id):
    r = _by_id_or_404(conn, scim_id)
    conn.execute("DELETE FROM PSROLEUSER WHERE ROLEUSER=?", (r["OPRID"],))
    conn.execute("DELETE FROM PSOPRDEFN WHERE SCIM_ID=?", (scim_id,))
    db.audit(conn, r["EMPLID"], "SCIM_DELETE", f"User profile {r['OPRID']} deleted by SCIM", "OKTA", "SCIM")
    conn.commit()
