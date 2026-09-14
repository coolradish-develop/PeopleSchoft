"""JSON REST API (clean /api/v1 routes + PeopleSoft Integration Broker style aliases) and SCIM routes."""
import json

from . import db, hr, okta, scim
from .config import config
from .journey import run_journey
from .routing import Response, json_response, route

IB = r"/PSIGW/RESTListeningConnector/PSFT_HR"


def _worker_or_404(conn, emplid, asof=None):
    w = hr.get_worker(conn, emplid, asof=asof)
    if not w:
        return None, json_response({"error": f"EMPLID {emplid} not found"}, 404)
    return w, None


# ---------------------------------------------------------------------- health / meta
@route("GET", r"/api/v1/health")
def health(req, conn):
    return json_response({"status": "ok", "service": "peopleschoft", "version": "1.0.0", "oktaMode": config.okta_mode,
                          "workers": conn.execute("SELECT COUNT(*) FROM PS_PERSONAL_DATA").fetchone()[0]})


@route("GET", r"/api/v1/meta")
def meta(req, conn):
    return json_response({"actions": hr.ACTIONS, "actionReasons": hr.REASONS, "emplStatus": hr.STATUS_LABELS,
                          "emplClass": hr.EMPL_CLASS, "eventTypes": sorted(set(hr.EVENT_FOR_ACTION.values()))})


# ---------------------------------------------------------------------- workers
@route("GET", r"/api/v1/workers")
@route("GET", IB + r"/WORKER\.v1")
@route("GET", IB + r"/EMPLOYEE\.v1")
def list_workers(req, conn):
    q = req.query
    workers, total = hr.list_workers(conn, status=q.get("status"), changed_since=q.get("changedSince"), q=q.get("q"),
                                     asof=q.get("asOf"), deptid=q.get("deptid"), limit=req.int_query("limit", 500),
                                     offset=req.int_query("offset", 0), include_inactive=q.get("active") not in ("true", "1"))
    return json_response({"count": len(workers), "total": total, "asOf": q.get("asOf") or hr.today(), "workers": workers})


@route("GET", r"/api/v1/workers/(?P<emplid>[^/]+)")
@route("GET", IB + r"/WORKER\.v1/(?P<emplid>[^/]+)")
@route("GET", IB + r"/EMPLOYEE\.v1/(?P<emplid>[^/]+)")
def get_worker(req, conn, emplid):
    w, err = _worker_or_404(conn, emplid, req.query.get("asOf"))
    return err or json_response(w)


@route("POST", r"/api/v1/workers")
@route("POST", IB + r"/WORKER\.v1")
def create_worker(req, conn):
    return json_response(hr.hire(conn, req.json(), oprid=req.headers.get("X-Oprid", "API"), source="API"), 201)


@route("PATCH,PUT", r"/api/v1/workers/(?P<emplid>[^/]+)")
def update_worker(req, conn, emplid):
    return json_response(hr.update_personal(conn, emplid, req.json(), oprid=req.headers.get("X-Oprid", "API")))


@route("GET", r"/api/v1/workers/(?P<emplid>[^/]+)/job-history")
@route("GET", IB + r"/JOB\.v1/(?P<emplid>[^/]+)")
def job_history(req, conn, emplid):
    w, err = _worker_or_404(conn, emplid)
    return err or json_response({"emplid": emplid, "rows": hr.job_history(conn, emplid)})


@route("POST", r"/api/v1/workers/(?P<emplid>[^/]+)/actions")
@route("POST", IB + r"/JOB\.v1/(?P<emplid>[^/]+)")
def worker_action(req, conn, emplid):
    return json_response(hr.generic_action(conn, emplid, req.json(), oprid=req.headers.get("X-Oprid", "API")))


_SHORTCUTS = {"transfer": "XFR", "promote": "PRO", "demote": "DEM", "pay": "PAY", "manager": "DTA", "leave": "LOA",
              "return": "RFL", "terminate": "TER", "retire": "RET", "rehire": "REH", "suspend": "SUS"}


@route("POST", r"/api/v1/workers/(?P<emplid>[^/]+)/(?P<verb>transfer|promote|demote|pay|manager|leave|return|terminate|retire|rehire|suspend)")
def worker_verb(req, conn, emplid, verb):
    body = dict(req.json())
    body["action"] = _SHORTCUTS[verb]
    if verb == "leave" and body.get("paid") in (True, "true", "1"):
        body["action"] = "PLA"
    return json_response(hr.generic_action(conn, emplid, body, oprid=req.headers.get("X-Oprid", "API")))


@route("GET", r"/api/v1/workers/(?P<emplid>[^/]+)/events")
def worker_events(req, conn, emplid):
    return json_response({"emplid": emplid, "events": _events(conn, "EMPLID=?", (emplid,))})


# ---------------------------------------------------------------------- setup tables
@route("GET", r"/api/v1/departments")
def departments(req, conn):
    return json_response({"departments": db.rows(conn, "SELECT * FROM PS_DEPT_TBL ORDER BY DEPTID")})


@route("GET", r"/api/v1/jobcodes")
def jobcodes(req, conn):
    return json_response({"jobcodes": db.rows(conn, "SELECT * FROM PS_JOBCODE_TBL ORDER BY JOBCODE")})


@route("GET", r"/api/v1/locations")
def locations(req, conn):
    return json_response({"locations": db.rows(conn, "SELECT * FROM PS_LOCATION_TBL ORDER BY LOCATION")})


@route("GET", r"/api/v1/companies")
def companies(req, conn):
    return json_response({"companies": db.rows(conn, "SELECT * FROM PS_COMPANY_TBL")})


@route("GET", r"/api/v1/audit")
def audit_log(req, conn):
    return json_response({"audit": db.rows(conn, "SELECT * FROM PS_AUDIT_LOG ORDER BY AUDIT_ID DESC LIMIT ?", (req.int_query("limit", 200),))})


# ---------------------------------------------------------------------- Okta outbox
def _events(conn, where="1=1", params=(), limit=200):
    out = []
    for r in db.rows(conn, f"SELECT * FROM PS_OKTA_EVENTS WHERE {where} ORDER BY EVENT_ID DESC LIMIT ?", (*params, limit)):
        r["PAYLOAD"] = json.loads(r["PAYLOAD"])
        for k in ("REQUEST_PREVIEW", "RESPONSE"):
            if r.get(k):
                try:
                    r[k] = json.loads(r[k])
                except ValueError:
                    pass
        out.append({k.lower(): v for k, v in r.items()})
    return out


@route("GET", r"/api/v1/events")
def list_events(req, conn):
    status = req.query.get("status")
    where, params = ("STATUS=?", (status.upper(),)) if status else ("1=1", ())
    return json_response({"events": _events(conn, where, params, req.int_query("limit", 200))})


@route("GET", r"/api/v1/events/(?P<event_id>\d+)")
def get_event(req, conn, event_id):
    ev = _events(conn, "EVENT_ID=?", (event_id,))
    return json_response(ev[0]) if ev else json_response({"error": "not found"}, 404)


@route("POST", r"/api/v1/events/(?P<event_id>\d+)/retry")
def retry_event(req, conn, event_id):
    okta.retry_event(conn, event_id)
    return json_response({"ok": True, "eventId": int(event_id), "status": "PENDING"})


@route("POST", r"/api/v1/okta/sync")
def okta_sync(req, conn):
    return json_response(okta.sync_pending(conn))


@route("GET", r"/api/v1/okta/status")
def okta_status(req, conn):
    counts = {r["STATUS"]: r["n"] for r in db.rows(conn, "SELECT STATUS, COUNT(*) AS n FROM PS_OKTA_EVENTS GROUP BY STATUS")}
    return json_response({"config": config.okta_summary(), "outbox": counts})


@route("POST", r"/api/v1/okta/export")
def okta_export(req, conn):
    return json_response({"queued": okta.full_export(conn)})


@route("POST", r"/api/v1/okta/requeue")
def okta_requeue(req, conn):
    okta.requeue_all(conn)
    return json_response({"ok": True})


@route("GET", r"/api/v1/okta/preview/(?P<emplid>[^/]+)")
def okta_preview(req, conn, emplid):
    w, err = _worker_or_404(conn, emplid)
    if err:
        return err
    c = okta.OktaClient()
    return json_response({"emplid": emplid, "desiredStatus": c.desired_status(w), "profile": c.profile_from_worker(w, include_custom=True),
                          "usersApiPlan": c.plan_users_api(w), "identitySourcePlan": c.plan_identity_source([w])})


# ---------------------------------------------------------------------- user profiles (SCIM inbound result)
@route("GET", r"/api/v1/users")
def list_user_profiles(req, conn):
    users = db.rows(conn, "SELECT * FROM PSOPRDEFN ORDER BY OPRID")
    for u in users:
        u["ROLES"] = [r["ROLENAME"] for r in db.rows(conn, "SELECT ROLENAME FROM PSROLEUSER WHERE ROLEUSER=?", (u["OPRID"],))]
        u.pop("RAW_JSON", None)
    return json_response({"users": users})


# ---------------------------------------------------------------------- admin
@route("POST", r"/api/v1/admin/reset")
def admin_reset(req, conn):
    db.reset_db(conn)
    hr.seed(conn)
    return json_response({"ok": True, "message": "Database reset and re-seeded"})


@route("POST", r"/api/v1/admin/journey")
def admin_journey(req, conn):
    result = run_journey(conn, oprid=req.headers.get("X-Oprid", "API"))
    if req.query.get("sync", "true") != "false":
        result["oktaSync"] = okta.sync_pending(conn)
    return json_response(result)


# ---------------------------------------------------------------------- SCIM 2.0
S = r"/scim/v2"


def _scim(data, status=200):
    return json_response(data, status, "application/scim+json")


@route("GET", S + r"/ServiceProviderConfig")
def scim_spc(req, conn):
    return _scim(scim.service_provider_config(req.base_url))


@route("GET", S + r"/ResourceTypes")
def scim_rt(req, conn):
    return _scim(scim.resource_types(req.base_url))


@route("GET", S + r"/Schemas")
def scim_schemas(req, conn):
    return _scim(scim.schemas(req.base_url))


@route("GET", S + r"/Users")
def scim_list(req, conn):
    return _scim(scim.list_users(conn, req.base_url, req.query.get("filter"), req.int_query("startIndex", 1), req.int_query("count", 100)))


@route("POST", S + r"/Users")
def scim_create(req, conn):
    return _scim(scim.create_user(conn, req.json(), req.base_url), 201)


@route("GET", S + r"/Users/(?P<scim_id>[^/]+)")
def scim_get(req, conn, scim_id):
    r = scim.get_by_id(conn, scim_id)
    if not r:
        raise scim.ScimError(404, f"User {scim_id} not found")
    return _scim(scim.to_scim(conn, r, req.base_url))


@route("PUT", S + r"/Users/(?P<scim_id>[^/]+)")
def scim_put(req, conn, scim_id):
    return _scim(scim.replace_user(conn, scim_id, req.json(), req.base_url))


@route("PATCH", S + r"/Users/(?P<scim_id>[^/]+)")
def scim_patch(req, conn, scim_id):
    return _scim(scim.patch_user(conn, scim_id, req.json(), req.base_url))


@route("DELETE", S + r"/Users/(?P<scim_id>[^/]+)")
def scim_delete(req, conn, scim_id):
    scim.delete_user(conn, scim_id)
    return Response(b"", 204, "application/scim+json")


@route("GET", S + r"/Groups")
def scim_groups(req, conn):
    return _scim(scim._list([]))


@route("POST,PUT,PATCH,DELETE", S + r"/Groups(?:/[^/]+)?")
def scim_groups_unsupported(req, conn):
    raise scim.ScimError(501, "Group provisioning is not supported by this emulator")
