"""Outbound connector: pushes HR lifecycle events from the PS_OKTA_EVENTS outbox to Okta.

Modes (OKTA_MODE):
  dryrun           - no network; records the exact Okta requests it would make (default, works with no tenant)
  webhook          - POST each event to OKTA_WEBHOOK_URL (e.g. an Okta Workflows "API Endpoint" card)
  users            - drive the Okta Users API directly (create / update / suspend / deactivate / reactivate)
  identity-source  - Okta "Anything-as-a-Source": bulk-upsert / bulk-delete through an Identity Source session
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from . import db
from .config import config

MASK = "SSWS ****"


class OktaClient:
    def __init__(self, cfg=None):
        self.cfg = cfg or config

    # ------------------------------------------------------------------ mapping
    def profile_from_worker(self, worker, include_custom=None):
        """Map a PeopleSoft worker composite onto Okta's base user profile (+ optional custom attributes)."""
        j = worker.get("job") or {}
        first = worker.get("preferredFirstName") or worker["firstName"]
        profile = {
            "login": worker["workEmail"],
            "email": worker["workEmail"],
            "firstName": worker["firstName"],
            "lastName": worker["lastName"],
            "middleName": worker.get("middleName") or None,
            "nickName": worker.get("preferredFirstName") or None,
            "displayName": f"{first} {worker['lastName']}",
            "title": j.get("jobTitle"),
            "department": j.get("deptDescr"),
            "employeeNumber": worker["emplid"],
            "managerId": j.get("supervisorId") or None,
            "manager": j.get("supervisorName") or None,
            "costCenter": j.get("deptid"),
            "organization": j.get("company"),
            "division": j.get("businessUnit"),
            "mobilePhone": worker.get("mobilePhone") or None,
            "primaryPhone": worker.get("workPhone") or None,
            "city": j.get("city") or None,
            "state": j.get("state") or None,
            "countryCode": _iso2(j.get("locationCountry") or worker.get("country")),
            "userType": j.get("emplClassDescr"),
            "secondEmail": worker.get("homeEmail") or None,
        }
        include_custom = self.cfg.okta_custom_attrs if include_custom is None else include_custom
        if include_custom:
            profile.update({
                "hireDate": worker.get("hireDate"),
                "terminationDate": worker.get("terminationDate"),
                "employeeStatus": worker.get("emplStatus"),
                "jobCode": j.get("jobcode"),
                "locationCode": j.get("location"),
                "managerEmail": j.get("supervisorEmail") or None,
                "regTemp": j.get("regTemp"),
                "fullPartTime": j.get("fullPartTime"),
            })
        return {k: v for k, v in profile.items() if v not in (None, "")}

    def desired_status(self, worker):
        """Translate PeopleSoft EMPL_STATUS into the Okta lifecycle state we want."""
        s = worker.get("emplStatus")
        if worker.get("preHire"):
            return "STAGED"
        if s in ("T", "R", "D", "V", "Q"):
            return "DEPROVISIONED"
        if s in ("L", "P", "S") and self.cfg.okta_loa_action == "suspend":
            return "SUSPENDED"
        return "ACTIVE"

    def prehire_ready(self, worker):
        """Pre-hires are only pushed once inside the pre-hire window (OKTA_PREHIRE_DAYS)."""
        if not worker.get("preHire"):
            return True
        hire = worker.get("hireDate")
        if not hire:
            return True
        return date.fromisoformat(hire) <= date.today() + timedelta(days=self.cfg.okta_prehire_days)

    # ------------------------------------------------------------------ HTTP
    def _headers(self, extra=None):
        h = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "peopleschoft/1.0"}
        if self.cfg.okta_api_token:
            h["Authorization"] = f"SSWS {self.cfg.okta_api_token}"
        h.update(extra or {})
        return h

    def request(self, method, url, body=None, headers=None, timeout=20):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers(headers))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode() or ""
                return resp.status, _maybe_json(text)
        except urllib.error.HTTPError as e:
            return e.code, _maybe_json(e.read().decode(errors="replace"))
        except (urllib.error.URLError, OSError) as e:
            return 0, {"error": str(e)}

    # ------------------------------------------------------------------ Users API
    def users_url(self, path=""):
        return f"{self.cfg.okta_org_url}/api/v1/users{path}"

    def find_user(self, worker):
        q = urllib.parse.quote(f'profile.employeeNumber eq "{worker["emplid"]}"')
        status, body = self.request("GET", self.users_url(f"?search={q}&limit=1"))
        if status == 200 and isinstance(body, list) and body:
            return body[0], None
        if status == 200 and worker.get("workEmail"):
            q = urllib.parse.quote(f'profile.login eq "{worker["workEmail"]}"')
            status, body = self.request("GET", self.users_url(f"?search={q}&limit=1"))
            if status == 200 and isinstance(body, list) and body:
                return body[0], None
        if status not in (200,):
            return None, {"status": status, "body": body}
        return None, None

    def plan_users_api(self, worker, existing=None):
        """Return the ordered list of Users API calls for this worker. `existing` is the Okta user if known."""
        desired = self.desired_status(worker)
        profile = self.profile_from_worker(worker)
        emplid = worker["emplid"]
        steps = [{"method": "GET", "url": self.users_url(f'?search=profile.employeeNumber eq "{emplid}"'),
                  "note": "Look up existing Okta user by employeeNumber (fallback: profile.login)"}]
        uid = existing["id"] if existing else "{userId}"
        current = existing["status"] if existing else None
        if existing is None:
            if desired == "DEPROVISIONED":
                steps.append({"method": "-", "url": "-", "note": "No Okta user exists; nothing to deactivate"})
                return steps
            activate = "false" if desired == "STAGED" else "true"
            steps.append({"method": "POST", "url": self.users_url(f"?activate={activate}"),
                          "body": {"profile": profile},
                          "note": "Create user" + (" as STAGED (pre-hire)" if desired == "STAGED" else " and activate")})
            if desired == "SUSPENDED":
                steps.append({"method": "POST", "url": self.users_url(f"/{uid}/lifecycle/suspend"), "note": "On leave -> suspend"})
            return steps
        steps.append({"method": "POST", "url": self.users_url(f"/{uid}"), "body": {"profile": profile},
                      "note": "Partial profile update"})
        if desired == "DEPROVISIONED" and current != "DEPROVISIONED":
            steps.append({"method": "POST", "url": self.users_url(f"/{uid}/lifecycle/deactivate?sendEmail=false"),
                          "note": "Terminated -> deactivate"})
        elif desired == "SUSPENDED" and current in (None, "ACTIVE"):
            steps.append({"method": "POST", "url": self.users_url(f"/{uid}/lifecycle/suspend"), "note": "On leave -> suspend"})
        elif desired == "ACTIVE":
            if current == "SUSPENDED":
                steps.append({"method": "POST", "url": self.users_url(f"/{uid}/lifecycle/unsuspend"), "note": "Return from leave -> unsuspend"})
            elif current == "DEPROVISIONED":
                steps.append({"method": "POST", "url": self.users_url(f"/{uid}/lifecycle/reactivate?sendEmail=false"), "note": "Rehire -> reactivate"})
            elif current in ("STAGED", "PROVISIONED"):
                steps.append({"method": "POST", "url": self.users_url(f"/{uid}/lifecycle/activate?sendEmail=false"), "note": "Start date reached -> activate"})
        return steps

    def execute_users_api(self, worker):
        existing, err = self.find_user(worker)
        if err:
            return False, {"step": "lookup", **err}, self.plan_users_api(worker)
        steps = self.plan_users_api(worker, existing)
        log = []
        for s in steps:
            if s["method"] in ("GET", "-"):
                continue
            status, body = self.request(s["method"], s["url"], s.get("body"))
            log.append({"method": s["method"], "url": s["url"], "status": status, "note": s["note"],
                        "response": body if status >= 300 else {"id": body.get("id"), "status": body.get("status")} if isinstance(body, dict) else body})
            if status >= 300 or status == 0:
                return False, log, steps
        return True, log or [{"note": "nothing to do"}], steps

    # ------------------------------------------------------------------ Webhook (Okta Workflows API Endpoint)
    def execute_webhook(self, payload):
        headers = {}
        if self.cfg.okta_webhook_token:
            headers["x-api-client-token"] = self.cfg.okta_webhook_token
        status, body = self.request("POST", self.cfg.okta_webhook_url, payload, headers)
        return 200 <= status < 300, {"status": status, "body": body}

    def webhook_body(self, payload):
        worker = payload["worker"]
        return {**payload, "oktaProfile": self.profile_from_worker(worker, include_custom=True),
                "oktaDesiredStatus": self.desired_status(worker)}

    # ------------------------------------------------------------------ Identity Source (Anything-as-a-Source)
    def ids_url(self, path=""):
        return f"{self.cfg.okta_org_url}/api/v1/identity-sources/{self.cfg.okta_identity_source_id or '{identitySourceId}'}/sessions{path}"

    def plan_identity_source(self, workers):
        upserts, deletes = [], []
        for w in workers:
            if self.desired_status(w) == "DEPROVISIONED":
                deletes.append({"externalId": w["emplid"]})
            else:
                p = self.profile_from_worker(w, include_custom=True)
                p["userName"] = p.pop("login")
                p["active"] = self.desired_status(w) == "ACTIVE"
                upserts.append({"externalId": w["emplid"], "profile": p})
        steps = [{"method": "POST", "url": self.ids_url(), "note": "Create import session"}]
        if upserts:
            steps.append({"method": "POST", "url": self.ids_url("/{sessionId}/bulk-upsert"), "body": {"profiles": upserts}, "note": "Upsert joiners/movers"})
        if deletes:
            steps.append({"method": "POST", "url": self.ids_url("/{sessionId}/bulk-delete"), "body": {"profiles": deletes}, "note": "Delete leavers"})
        steps.append({"method": "POST", "url": self.ids_url("/{sessionId}/start-import"), "note": "Trigger import"})
        return steps

    def execute_identity_source(self, workers):
        steps = self.plan_identity_source(workers)
        log = []
        status, body = self.request("POST", self.ids_url())
        log.append({"step": "create-session", "status": status, "response": body})
        if status >= 300 or status == 0 or not isinstance(body, dict) or "id" not in body:
            return False, log, steps
        sid = body["id"]
        for s in steps[1:]:
            url = s["url"].replace("{sessionId}", sid)
            status, resp = self.request("POST", url, s.get("body"))
            log.append({"step": s["note"], "status": status, "response": resp})
            if status >= 300 or status == 0:
                return False, log, steps
        return True, log, steps


def _iso2(country):
    return {"USA": "US", "GBR": "GB", "CAN": "CA", "DEU": "DE", "FRA": "FR", "IND": "IN", "AUS": "AU"}.get(country, country[:2] if country else None)


def _maybe_json(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


# ---------------------------------------------------------------------- outbox processing
# What the dry run assumes about the Okta user before each event type (None = does not exist yet).
DRYRUN_ASSUMED_STATE = {"worker.hired": None, "worker.snapshot": None, "worker.rehired": "DEPROVISIONED",
                        "worker.leave_ended": "SUSPENDED", "worker.started": "STAGED"}


def pending_events(conn, limit=200):
    return db.rows(conn, "SELECT * FROM PS_OKTA_EVENTS WHERE STATUS IN ('PENDING','SCHEDULED','FAILED') AND ATTEMPTS < 5 ORDER BY EVENT_ID LIMIT ?", (limit,))


def event_ready(ev, worker, cfg):
    """Events fire on their effective date. Hires/rehires fire early, inside the pre-hire window."""
    from .hr import today
    effdt = ev["EFFDT"] or today()
    if ev["EVENT_TYPE"] in ("worker.hired", "worker.rehired"):
        return effdt <= (date.today() + timedelta(days=cfg.okta_prehire_days)).isoformat(), \
            f"pre-hire: sends {cfg.okta_prehire_days} days before start date {effdt}"
    return effdt <= today(), f"scheduled: sends on effective date {effdt}"


def _mark(conn, event_id, status, target, preview, response, sent=True):
    conn.execute("UPDATE PS_OKTA_EVENTS SET STATUS=?, TARGET=?, REQUEST_PREVIEW=?, RESPONSE=?, SENT_DTTM=?, ATTEMPTS=ATTEMPTS+1 WHERE EVENT_ID=?",
                 (status, target, json.dumps(preview, indent=1)[:20000], json.dumps(response, indent=1)[:20000],
                  db.now_iso() if sent else None, event_id))


def sync_pending(conn, cfg=None, client=None):
    """Flush the outbox. Returns a summary dict. Safe to call repeatedly."""
    cfg = cfg or config
    client = client or OktaClient(cfg)
    mode = cfg.okta_mode
    events = pending_events(conn)
    summary = {"mode": mode, "processed": 0, "sent": 0, "failed": 0, "dryrun": 0, "deferred": 0, "errors": []}
    if not events:
        return summary

    from . import hr
    ready = []
    for ev in events:
        payload = json.loads(ev["PAYLOAD"])
        ok, why = event_ready(ev, payload["worker"], cfg)
        if not ok:
            conn.execute("UPDATE PS_OKTA_EVENTS SET STATUS='SCHEDULED', RESPONSE=? WHERE EVENT_ID=?",
                         (json.dumps({"deferred": why}), ev["EVENT_ID"]))
            summary["deferred"] += 1
            continue
        # Events created for a future effective date carry a stale snapshot: refresh so they reflect
        # the state as of the send date. Same-day events keep their snapshot, preserving the sequence
        # of transitions (leave -> suspend, terminate -> deactivate, rehire -> reactivate) in a batch.
        fresh = hr.get_worker(conn, ev["EMPLID"]) if (ev["EFFDT"] or "") > ev["CREATED_DTTM"][:10] else None
        if fresh:
            payload["worker"] = fresh
            conn.execute("UPDATE PS_OKTA_EVENTS SET PAYLOAD=? WHERE EVENT_ID=?", (json.dumps(payload), ev["EVENT_ID"]))
        ev["PAYLOAD"] = json.dumps(payload)
        ready.append(ev)
    if not ready:
        conn.commit()
        return summary

    if mode == "identity-source":
        # One Okta import session for the whole batch; latest snapshot per EMPLID wins.
        latest = {}
        for ev in ready:
            latest[ev["EMPLID"]] = json.loads(ev["PAYLOAD"])["worker"]
        workers = list(latest.values())
        if not cfg.okta_api_token or not cfg.okta_identity_source_id:
            ok, log, steps = False, {"error": "OKTA_API_TOKEN and OKTA_IDENTITY_SOURCE_ID are required for identity-source mode"}, client.plan_identity_source(workers)
        else:
            ok, log, steps = client.execute_identity_source(workers)
        for ev in ready:
            _mark(conn, ev["EVENT_ID"], "SENT" if ok else "FAILED", f"identity-source {cfg.okta_identity_source_id}", steps, log, sent=ok)
        summary["processed"] = len(ready)
        summary["sent" if ok else "failed"] = len(ready)
        if not ok:
            summary["errors"].append(log)
        conn.commit()
        return summary

    for ev in ready:
        payload = json.loads(ev["PAYLOAD"])
        worker = payload["worker"]
        summary["processed"] += 1
        try:
            if mode == "dryrun":
                assumed = DRYRUN_ASSUMED_STATE.get(payload.get("eventType"), "ACTIVE")
                existing = None if assumed is None else {"id": "{userId}", "status": assumed}
                preview = {"assumption": "no Okta user exists yet" if existing is None else f"an Okta user exists with status {assumed}",
                           "usersApi": client.plan_users_api(worker, existing),
                           "webhook": {"method": "POST", "url": cfg.okta_webhook_url or "{OKTA_WEBHOOK_URL}", "body": client.webhook_body(payload)},
                           "identitySource": client.plan_identity_source([worker])}
                _mark(conn, ev["EVENT_ID"], "DRYRUN", "dryrun", preview, {"note": "Dry run: no request sent. Set OKTA_MODE to webhook, users or identity-source."})
                summary["dryrun"] += 1
            elif mode == "webhook":
                if not cfg.okta_webhook_url:
                    raise RuntimeError("OKTA_WEBHOOK_URL is not set")
                body = client.webhook_body(payload)
                ok, resp = client.execute_webhook(body)
                _mark(conn, ev["EVENT_ID"], "SENT" if ok else "FAILED", cfg.okta_webhook_url,
                      {"method": "POST", "url": cfg.okta_webhook_url, "body": body}, resp, sent=ok)
                summary["sent" if ok else "failed"] += 1
                if not ok:
                    summary["errors"].append(resp)
            elif mode == "users":
                if not cfg.okta_api_token:
                    raise RuntimeError("OKTA_API_TOKEN is not set")
                ok, log, steps = client.execute_users_api(worker)
                _mark(conn, ev["EVENT_ID"], "SENT" if ok else "FAILED", f"{cfg.okta_org_url} (Users API)", steps, log, sent=ok)
                summary["sent" if ok else "failed"] += 1
                if not ok:
                    summary["errors"].append(log)
            else:
                raise RuntimeError(f"Unknown OKTA_MODE {mode!r}")
        except Exception as e:  # noqa: BLE001 - keep the sync loop alive
            _mark(conn, ev["EVENT_ID"], "FAILED", mode, {}, {"error": str(e)}, sent=False)
            summary["failed"] += 1
            summary["errors"].append(str(e))
        conn.commit()
    return summary


def retry_event(conn, event_id):
    conn.execute("UPDATE PS_OKTA_EVENTS SET STATUS='PENDING', ATTEMPTS=0 WHERE EVENT_ID=?", (event_id,))
    conn.commit()


def requeue_all(conn):
    conn.execute("UPDATE PS_OKTA_EVENTS SET STATUS='PENDING', ATTEMPTS=0")
    conn.commit()


def full_export(conn, cfg=None):
    """Enqueue a snapshot event for every worker (initial load / reconciliation)."""
    from . import hr
    workers, _ = hr.list_workers(conn, limit=100000)
    n = 0
    for w in workers:
        hr.enqueue_event(conn, w["emplid"], w["job"]["action"] if w["job"] else "DTA", "", hr.today(),
                         "Full export snapshot", event_type="worker.snapshot")
        n += 1
    conn.commit()
    return n
