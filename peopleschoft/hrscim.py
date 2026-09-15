"""HR-as-a-source SCIM feed for Okta On-Premises Provisioning (Okta Provisioning Agent).

Serves *workers* (PS_JOB / PS_PERSONAL_DATA) as SCIM Users and departments as Groups so Okta can
import them and treat this system as the profile source ("Profile Source > Enable" on the app).

  /hr/scim/v1   SCIM 1.1  (what the Okta Provisioning Agent speaks by default)
  /hr/scim/v2   SCIM 2.0  (agents with "OPP Agent with SCIM 2.0 support", Okta On-prem SCIM Server agent)

Supported: GET /ServiceProviderConfigs (1.1) | /ServiceProviderConfig (2.0), GET /Users (startIndex, count,
filter: userName eq, id eq, externalId eq, employeeNumber eq, meta.lastModified gt), GET /Users/{id},
GET /Groups, GET /Groups/{id}. Writes are refused (HR is the master) unless PS_HR_SCIM_WRITEBACK=1.
"""
import re
from datetime import date, datetime, timedelta

from . import db, hr
from .config import config

CORE1, ENT1, LIST1, ERR1 = "urn:scim:schemas:core:1.0", "urn:scim:schemas:extension:enterprise:1.0", "urn:scim:schemas:core:1.0", "urn:scim:schemas:core:1.0"
CORE2, ENT2 = "urn:ietf:params:scim:schemas:core:2.0:User", "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
GROUP2, LIST2, ERR2 = "urn:ietf:params:scim:schemas:core:2.0:Group", "urn:ietf:params:scim:api:messages:2.0:ListResponse", "urn:ietf:params:scim:api:messages:2.0:Error"
OKTA_CFG = "urn:okta:schemas:scim:providerconfig:1.0"
CUSTOM = "urn:okta:peopleschoft:1.0:user"      # PeopleSoft job attributes (map them in Okta's profile editor)
CUSTOM_GROUP = "urn:okta:custom:group:1.0"


class HrScimError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.detail = status, detail

    def body(self, version):
        if version == 1:
            return {"Errors": [{"description": self.detail, "code": str(self.status)}]}
        return {"schemas": [ERR2], "detail": self.detail, "status": str(self.status)}


def capabilities():
    caps = ["IMPORT_NEW_USERS", "IMPORT_PROFILE_UPDATES", "OPP_SCIM_INCREMENTAL_IMPORTS"]
    if config.hr_scim_writeback:
        caps += ["PUSH_PROFILE_UPDATES", "PUSH_USER_DEACTIVATION", "REACTIVATE_USERS"]
    return caps


def service_provider_config(base, version):
    if version == 1:
        return {"schemas": [CORE1, OKTA_CFG], "patch": {"supported": False}, "bulk": {"supported": False},
                "filter": {"supported": True, "maxResults": 1000}, "changePassword": {"supported": False},
                "sort": {"supported": False}, "etag": {"supported": False},
                "authenticationSchemes": [{"name": "HTTP Header / Bearer", "description": f"Authorization: Bearer <PS_HR_SCIM_TOKEN> or header {config.hr_scim_header}", "type": "httpheader"}],
                OKTA_CFG: {"userManagementCapabilities": capabilities()}}
    return {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig", OKTA_CFG],
            "documentationUri": base + "/hr-master",
            "patch": {"supported": False}, "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
            "filter": {"supported": True, "maxResults": 1000}, "changePassword": {"supported": False},
            "sort": {"supported": False}, "etag": {"supported": False},
            "authenticationSchemes": [{"type": "oauthbearertoken", "name": "Bearer token", "description": "Authorization: Bearer <PS_HR_SCIM_TOKEN>", "primary": True}],
            OKTA_CFG: {"userManagementCapabilities": capabilities()},
            "meta": {"resourceType": "ServiceProviderConfig", "location": f"{base}/hr/scim/v2/ServiceProviderConfig"}}


def resource_types(base):
    return _list([{"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"], "id": "User", "name": "User", "endpoint": "/Users",
                   "schema": CORE2, "schemaExtensions": [{"schema": ENT2, "required": False}, {"schema": CUSTOM, "required": False}],
                   "meta": {"resourceType": "ResourceType", "location": f"{base}/hr/scim/v2/ResourceTypes/User"}},
                  {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"], "id": "Group", "name": "Group", "endpoint": "/Groups",
                   "schema": GROUP2, "meta": {"resourceType": "ResourceType", "location": f"{base}/hr/scim/v2/ResourceTypes/Group"}}], version=2)


CUSTOM_ATTRS = ["emplid", "emplStatus", "emplStatusDescr", "hrStatus", "preHire", "action", "actionReason", "effectiveDate", "deptid",
                "jobcode", "jobTitle", "jobFamily", "grade", "location", "locationDescr", "city", "state", "country", "company", "businessUnit",
                "supervisorId", "supervisorName", "supervisorEmail", "hireDate", "originalHireDate", "rehireDate", "terminationDate",
                "lastDateWorked", "regTemp", "fullPartTime", "emplClass", "emplClassDescr", "compFrequency"]


def schemas(base):
    def attr(n, t="string"):
        return {"name": n, "type": t, "multiValued": False, "required": False, "caseExact": False, "mutability": "readOnly", "returned": "default", "uniqueness": "none"}
    return _list([
        {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Schema"], "id": CORE2, "name": "User", "description": "PeopleSoft worker (HR master)",
         "attributes": [attr("userName"), attr("name", "complex"), attr("displayName"), attr("nickName"), attr("title"), attr("active", "boolean"),
                        attr("emails", "complex"), attr("phoneNumbers", "complex"), attr("externalId"), attr("userType")],
         "meta": {"resourceType": "Schema", "location": f"{base}/hr/scim/v2/Schemas/{CORE2}"}},
        {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Schema"], "id": ENT2, "name": "EnterpriseUser", "description": "Enterprise extension",
         "attributes": [attr("employeeNumber"), attr("department"), attr("organization"), attr("division"), attr("costCenter"), attr("manager", "complex")],
         "meta": {"resourceType": "Schema", "location": f"{base}/hr/scim/v2/Schemas/{ENT2}"}},
        {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Schema"], "id": CUSTOM, "name": "PeopleSoftWorker", "description": "PS_JOB / PS_EMPLOYMENT attributes",
         "attributes": [attr(a, "boolean" if a == "preHire" else "string") for a in CUSTOM_ATTRS],
         "meta": {"resourceType": "Schema", "location": f"{base}/hr/scim/v2/Schemas/{CUSTOM}"}},
    ], version=2)


# ---------------------------------------------------------------------- worker -> SCIM user
def _prehire_window_start(w):
    return (date.fromisoformat(w["hireDate"]) - timedelta(days=config.okta_prehire_days)).isoformat() + "T00:00:00Z"


def visible(w):
    """Pre-hires appear in the feed only inside the pre-hire window, so Okta creates them just before they start."""
    if not w.get("preHire") or not w.get("hireDate"):
        return True
    return date.fromisoformat(w["hireDate"]) <= date.today() + timedelta(days=config.okta_prehire_days)


def last_modified(w):
    lm = w["lastModified"]
    if w.get("preHire") and w.get("hireDate"):
        lm = max(lm, _prehire_window_start(w))
    return lm


def is_active(w):
    return w["emplStatus"] in hr.ACTIVE_STATUSES


def to_user(w, base, version):
    j = w.get("job") or {}
    active = is_active(w)
    emails = [{"value": w["workEmail"], "primary": True, "type": "work"}] if w["workEmail"] else []
    if w.get("homeEmail"):
        emails.append({"value": w["homeEmail"], "primary": False, "type": "home"})
    phones = [{"value": p, "type": t} for p, t in ((w.get("mobilePhone"), "mobile"), (w.get("workPhone"), "work")) if p]
    custom = {"emplid": w["emplid"], "emplStatus": w["emplStatus"], "emplStatusDescr": w["emplStatusDescr"], "hrStatus": w["hrStatus"],
              "preHire": bool(w.get("preHire")), "action": j.get("action"), "actionReason": j.get("actionReason"), "effectiveDate": j.get("effdt"),
              "deptid": j.get("deptid"), "jobcode": j.get("jobcode"), "jobTitle": j.get("jobTitle"), "jobFamily": j.get("jobFamily"), "grade": j.get("grade"),
              "location": j.get("location"), "locationDescr": j.get("locationDescr"), "city": j.get("city"), "state": j.get("state"),
              "country": j.get("locationCountry") or w.get("country"), "company": j.get("company"), "businessUnit": j.get("businessUnit"),
              "supervisorId": j.get("supervisorId"), "supervisorName": j.get("supervisorName"), "supervisorEmail": j.get("supervisorEmail"),
              "hireDate": w.get("hireDate"), "originalHireDate": w.get("originalHireDate"), "rehireDate": w.get("rehireDate"),
              "terminationDate": w.get("terminationDate"), "lastDateWorked": w.get("lastDateWorked"), "regTemp": j.get("regTemp"),
              "fullPartTime": j.get("fullPartTime"), "emplClass": j.get("emplClass"), "emplClassDescr": j.get("emplClassDescr"), "compFrequency": j.get("compFrequency")}
    custom = {k: v for k, v in custom.items() if v not in (None, "")}
    ent = {"employeeNumber": w["emplid"], "department": j.get("deptDescr"), "organization": j.get("company"), "division": j.get("businessUnit"),
           "costCenter": j.get("deptid")}
    if j.get("supervisorId"):
        ent["manager"] = {"managerId": j["supervisorId"], "displayName": j.get("supervisorName"), "value": j["supervisorId"]}
    ent = {k: v for k, v in ent.items() if v not in (None, "")}
    created = (w.get("originalHireDate") or w.get("hireDate") or "1970-01-01") + "T00:00:00Z"
    lm = last_modified(w)
    core, entk, path = (CORE1, ENT1, "v1") if version == 1 else (CORE2, ENT2, "v2")
    groups = [{"value": j["deptid"], "display": j.get("deptDescr")}] if j.get("deptid") else []
    first = w.get("preferredFirstName") or w["firstName"]
    user = {
        "schemas": [core, entk, CUSTOM], "id": w["emplid"], "externalId": w["emplid"], "userName": w["workEmail"] or w["emplid"],
        "name": {"givenName": w["firstName"], "familyName": w["lastName"], "middleName": w.get("middleName") or None, "formatted": f"{w['firstName']} {w['lastName']}"},
        "displayName": f"{first} {w['lastName']}", "nickName": w.get("preferredFirstName") or None, "title": j.get("jobTitle"),
        "userType": j.get("emplClassDescr"), "active": active, "emails": emails, "phoneNumbers": phones, "groups": groups,
        entk: ent, CUSTOM: custom,
        "meta": {"created": created, "lastModified": lm, "version": f"W/\"{lm}\"", "location": f"{base}/hr/scim/{path}/Users/{w['emplid']}"},
    }
    if version == 2:
        user["meta"]["resourceType"] = "User"
    user["name"] = {k: v for k, v in user["name"].items() if v}
    return {k: v for k, v in user.items() if v is not None}


def to_group(conn, d, base, version, with_members=True):
    members = []
    if with_members:
        for r in db.rows(conn, """SELECT p.EMPLID, p.NAME_DISPLAY FROM PS_PERSONAL_DATA p JOIN PS_JOB j ON j.EMPLID=p.EMPLID
                                  WHERE j.DEPTID=? AND j.EFFDT=(SELECT MAX(EFFDT) FROM PS_JOB x WHERE x.EMPLID=j.EMPLID AND x.EFFDT<=?)
                                  AND j.EFFSEQ=(SELECT MAX(EFFSEQ) FROM PS_JOB y WHERE y.EMPLID=j.EMPLID AND y.EFFDT=j.EFFDT)
                                  AND j.HR_STATUS='A' ORDER BY p.EMPLID""", (d["DEPTID"], hr.today())):
            members.append({"value": r["EMPLID"], "display": r["NAME_DISPLAY"]})
    core, path = (CORE1, "v1") if version == 1 else (GROUP2, "v2")
    g = {"schemas": [core, CUSTOM_GROUP], "id": d["DEPTID"], "externalId": d["DEPTID"], "displayName": f"{d['DESCR']} ({d['DEPTID']})",
         "members": members, CUSTOM_GROUP: {"description": f"PeopleSoft department {d['DEPTID']} at {d['LOCATION']}", "managerId": d["MANAGER_ID"]},
         "meta": {"location": f"{base}/hr/scim/{path}/Groups/{d['DEPTID']}"}}
    if version == 2:
        g["meta"]["resourceType"] = "Group"
    return g


def _list(resources, start=1, total=None, version=1):
    return {"schemas": [LIST1] if version == 1 else [LIST2], "totalResults": total if total is not None else len(resources),
            "startIndex": start, "itemsPerPage": len(resources), "Resources": resources}


# ---------------------------------------------------------------------- queries
FILTER_RX = re.compile(r'^\s*([\w.:\-]+)\s+(eq|gt|ge|co|sw)\s+"?([^"]*)"?\s*$', re.I)


def _norm_ts(v):
    v = v.strip()
    if v.endswith("Z"):
        v = v[:-1]
    if "+" in v[10:]:
        v = v[:v.rfind("+")]
    v = v.split(".")[0]
    if len(v) == 10:
        v += "T00:00:00"
    return v + "Z"


def list_users(conn, base, version, filt=None, start=1, count=100):
    workers, _ = hr.list_workers(conn, limit=100000)
    workers = [w for w in workers if visible(w)]
    if filt:
        m = FILTER_RX.match(filt.replace("%20", " "))
        if not m:
            raise HrScimError(400, f"Unsupported filter: {filt}")
        attr, op, val = m.group(1).lower(), m.group(2).lower(), m.group(3)
        if attr == "meta.lastmodified" and op in ("gt", "ge"):
            ts = _norm_ts(val)
            workers = [w for w in workers if (last_modified(w) > ts if op == "gt" else last_modified(w) >= ts)]
        elif op == "eq":
            key = {"username": lambda w: w["workEmail"], "id": lambda w: w["emplid"], "externalid": lambda w: w["emplid"],
                   "employeenumber": lambda w: w["emplid"], "emails.value": lambda w: w["workEmail"],
                   "urn:scim:schemas:extension:enterprise:1.0.employeenumber": lambda w: w["emplid"],
                   "name.givenname": lambda w: w["firstName"], "name.familyname": lambda w: w["lastName"]}.get(attr)
            if key is None and attr.endswith("employeenumber"):
                key = lambda w: w["emplid"]  # noqa: E731
            if key is None:
                raise HrScimError(400, f"Unsupported filter attribute: {attr}")
            workers = [w for w in workers if (key(w) or "").lower() == val.lower()]
        else:
            raise HrScimError(400, f"Unsupported filter operator: {op}")
    total = len(workers)
    start = max(1, start)
    count = max(0, min(count, 1000))
    page = workers[start - 1:start - 1 + count]
    return _list([to_user(w, base, version) for w in page], start, total, version)


def get_user(conn, emplid, base, version):
    w = hr.get_worker(conn, emplid)
    if not w or not visible(w):
        raise HrScimError(404, f"User {emplid} not found")
    return to_user(w, base, version)


def list_groups(conn, base, version, start=1, count=100):
    depts = db.rows(conn, "SELECT * FROM PS_DEPT_TBL ORDER BY DEPTID")
    total = len(depts)
    page = depts[max(1, start) - 1:max(1, start) - 1 + max(0, min(count, 1000))]
    return _list([to_group(conn, d, base, version) for d in page], start, total, version)


def get_group(conn, deptid, base, version):
    d = db.row(conn, "SELECT * FROM PS_DEPT_TBL WHERE DEPTID=?", (deptid,))
    if not d:
        raise HrScimError(404, f"Group {deptid} not found")
    return to_group(conn, d, base, version)


# ---------------------------------------------------------------------- optional write-back (PUT /Users/{id})
def replace_user(conn, emplid, body, base, version, oprid="OKTA"):
    """Okta pushes a full user (PUT). Only used when PS_HR_SCIM_WRITEBACK=1: profile fields -> DTA, active false -> TER, active true -> REH."""
    if not config.hr_scim_writeback:
        raise HrScimError(405, "This HR master feed is read-only. Set PS_HR_SCIM_WRITEBACK=1 to accept profile/deactivation pushes.")
    w = hr.get_worker(conn, emplid)
    if not w:
        raise HrScimError(404, f"User {emplid} not found")
    name = body.get("name") or {}
    emails = body.get("emails") or []
    primary = next((e.get("value") for e in emails if e.get("primary")), None) or (emails[0].get("value") if emails else None)
    data = {"firstName": name.get("givenName"), "lastName": name.get("familyName"), "preferredFirstName": body.get("nickName"), "workEmail": primary}
    hr.update_personal(conn, emplid, {k: v for k, v in data.items() if v}, oprid=oprid, source="OPP")
    active = body.get("active")
    if active is False and w["emplStatus"] in hr.ACTIVE_STATUSES:
        hr.terminate(conn, emplid, hr.today(), "INV", oprid=oprid, source="OPP")
    elif active is True and w["emplStatus"] in ("T", "R"):
        hr.rehire(conn, emplid, hr.today(), oprid=oprid, source="OPP")
    return to_user(hr.get_worker(conn, emplid), base, version)
