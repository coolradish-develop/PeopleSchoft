#!/usr/bin/env python3
"""Mock Okta org for demos without a real tenant.

Implements just enough of the Okta API for PeopleSchoft's three live modes:
  users            GET/POST /api/v1/users, POST /api/v1/users/{id}, POST /api/v1/users/{id}/lifecycle/*
  identity-source  POST /api/v1/identity-sources/{id}/sessions[/{sid}/bulk-upsert|bulk-delete|start-import]
  webhook          POST /webhook  (stores the event; browse at GET /)

Run:  python3 scripts/mock_okta.py [--port 9090]
Then: OKTA_MODE=users OKTA_ORG_URL=http://localhost:9090 OKTA_API_TOKEN=mock ./start.sh
"""
import argparse
import json
import re
import sys
import urllib.parse
import uuid
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USERS = {}        # id -> user
EVENTS = []       # webhook payloads
SESSIONS = {}     # identity source sessions
LOG = []


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body=None, ctype="application/json"):
        data = (json.dumps(body, indent=1) if body is not None and ctype == "application/json" else (body or "")).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {"_raw": raw.decode(errors="replace")}

    def _auth_ok(self):
        return self.headers.get("Authorization", "").startswith(("SSWS ", "Bearer "))

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path == "/":
            return self._send(200, self._page(), "text/html; charset=utf-8")
        if u.path == "/webhook/events":
            return self._send(200, EVENTS)
        if u.path == "/api/v1/users":
            users = list(USERS.values())
            if "search" in q:
                m = re.match(r'profile\.(\w+) eq "([^"]*)"', q["search"])
                if m:
                    users = [x for x in users if str(x["profile"].get(m.group(1), "")).lower() == m.group(2).lower()]
            self._log("GET", self.path, 200)
            return self._send(200, users)
        m = re.match(r"^/api/v1/users/([^/]+)$", u.path)
        if m and m.group(1) in USERS:
            return self._send(200, USERS[m.group(1)])
        self._log("GET", self.path, 404)
        return self._send(404, {"errorCode": "E0000007", "errorSummary": "Not found"})

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        body = self._body()
        p = u.path
        if p.startswith("/api/") and not self._auth_ok():
            self._log("POST", p, 401)
            return self._send(401, {"errorCode": "E0000011", "errorSummary": "Invalid token provided"})
        if p == "/api/v1/users":
            profile = body.get("profile", {})
            for x in USERS.values():
                if x["profile"].get("login", "").lower() == profile.get("login", "").lower():
                    self._log("POST", p, 400, profile.get("login"))
                    return self._send(400, {"errorCode": "E0000001", "errorSummary": "Api validation failed: login",
                                            "errorCauses": [{"errorSummary": "login: An object with this field already exists in the current organization"}]})
            uid = "00u" + uuid.uuid4().hex[:17]
            status = "ACTIVE" if q.get("activate", "true") == "true" else "STAGED"
            USERS[uid] = {"id": uid, "status": status, "created": now(), "lastUpdated": now(), "profile": profile}
            self._log("POST", p, 200, f"{profile.get('login')} -> {status}")
            return self._send(200, USERS[uid])
        m = re.match(r"^/api/v1/users/([^/]+)$", p)
        if m and m.group(1) in USERS:
            usr = USERS[m.group(1)]
            usr["profile"].update(body.get("profile", {}))
            usr["lastUpdated"] = now()
            self._log("POST", p, 200, f"update {usr['profile'].get('login')}")
            return self._send(200, usr)
        m = re.match(r"^/api/v1/users/([^/]+)/lifecycle/(\w+)$", p)
        if m and m.group(1) in USERS:
            usr, op = USERS[m.group(1)], m.group(2)
            new = {"deactivate": "DEPROVISIONED", "suspend": "SUSPENDED", "unsuspend": "ACTIVE", "reactivate": "PROVISIONED",
                   "activate": "ACTIVE", "unlock": usr["status"]}.get(op)
            if new is None:
                return self._send(404, {"errorSummary": "unknown lifecycle op"})
            if op == "suspend" and usr["status"] != "ACTIVE":
                self._log("POST", p, 400, f"{usr['profile'].get('login')} cannot suspend from {usr['status']}")
                return self._send(400, {"errorCode": "E0000001", "errorSummary": f"Cannot suspend user in status {usr['status']}"})
            usr["status"], usr["lastUpdated"] = new, now()
            self._log("POST", p, 200, f"{usr['profile'].get('login')} -> {new}")
            return self._send(200, {} if op != "reactivate" else {"activationUrl": "https://mock.okta/welcome"})
        m = re.match(r"^/api/v1/identity-sources/([^/]+)/sessions$", p)
        if m:
            sid = "ses" + uuid.uuid4().hex[:12]
            SESSIONS[sid] = {"id": sid, "identitySourceId": m.group(1), "status": "CREATED", "importType": "INCREMENTAL", "upserts": [], "deletes": []}
            self._log("POST", p, 200, f"session {sid}")
            return self._send(200, {"id": sid, "identitySourceId": m.group(1), "status": "CREATED", "importType": "INCREMENTAL"})
        m = re.match(r"^/api/v1/identity-sources/([^/]+)/sessions/([^/]+)/(bulk-upsert|bulk-delete|start-import)$", p)
        if m and m.group(2) in SESSIONS:
            s, op = SESSIONS[m.group(2)], m.group(3)
            if op == "bulk-upsert":
                s["upserts"] += body.get("profiles", [])
                for pr in body.get("profiles", []):
                    self._upsert_from_ids(pr)
            elif op == "bulk-delete":
                s["deletes"] += body.get("profiles", [])
                for pr in body.get("profiles", []):
                    for x in USERS.values():
                        if x["profile"].get("employeeNumber") == pr.get("externalId"):
                            x["status"] = "DEPROVISIONED"
            else:
                s["status"] = "TRIGGERED"
            self._log("POST", p, 200 if op != "start-import" else 202, f"{op} {len(body.get('profiles', []))} profiles")
            return self._send(200 if op != "start-import" else 202, {"id": s["id"], "status": s["status"]})
        if p.startswith("/webhook"):
            EVENTS.append({"receivedAt": now(), "clientToken": self.headers.get("x-api-client-token"), "body": body})
            self._log("POST", p, 200, f"{body.get('eventType')} {body.get('emplid')}")
            return self._send(200, {"ok": True, "received": body.get("eventType")})
        self._log("POST", p, 404)
        return self._send(404, {"errorCode": "E0000007", "errorSummary": "Not found: " + p})

    def _upsert_from_ids(self, pr):
        prof = dict(pr.get("profile", {}))
        prof["login"] = prof.pop("userName", prof.get("login"))
        active = prof.pop("active", True)
        for x in USERS.values():
            if x["profile"].get("employeeNumber") == pr.get("externalId"):
                x["profile"].update(prof)
                x["status"] = "ACTIVE" if active else "SUSPENDED"
                return
        uid = "00u" + uuid.uuid4().hex[:17]
        USERS[uid] = {"id": uid, "status": "ACTIVE" if active else "SUSPENDED", "created": now(), "lastUpdated": now(), "profile": prof}

    def _log(self, method, path, code, note=""):
        line = f"{now()} {method} {path} -> {code} {note}"
        LOG.append(line)
        print(line, flush=True)

    def _page(self):
        rows = "".join(f"<tr><td>{escape(u['id'])}</td><td>{escape(u['profile'].get('login',''))}</td><td>{escape(u['profile'].get('displayName',''))}</td>"
                       f"<td>{escape(u['profile'].get('employeeNumber',''))}</td><td>{escape(u['profile'].get('title',''))}</td><td>{escape(u['profile'].get('department',''))}</td>"
                       f"<td><b>{escape(u['status'])}</b></td><td>{escape(u['lastUpdated'])}</td></tr>" for u in USERS.values())
        ev = "".join(f"<tr><td>{escape(x['receivedAt'])}</td><td>{escape(str(x['body'].get('eventType')))}</td><td>{escape(str(x['body'].get('emplid')))}</td><td>{escape(str(x['body'].get('summary')))}</td><td>{escape(str(x['body'].get('oktaDesiredStatus')))}</td></tr>" for x in reversed(EVENTS))
        log = "\n".join(escape(x) for x in LOG[-60:])
        return f"""<!doctype html><html><head><meta charset="utf-8"><title>Mock Okta</title><meta http-equiv="refresh" content="5">
<style>body{{font:13px Arial;margin:20px;color:#222}}table{{border-collapse:collapse;margin-bottom:20px}}td,th{{border:1px solid #ccc;padding:4px 8px;text-align:left}}th{{background:#eef}}pre{{background:#f5f5f5;padding:8px;font-size:11px}}h1{{color:#00297a}}</style></head>
<body><h1>Mock Okta org <small>(auto-refreshes)</small></h1>
<h2>Users ({len(USERS)})</h2><table><tr><th>id</th><th>login</th><th>displayName</th><th>employeeNumber</th><th>title</th><th>department</th><th>status</th><th>lastUpdated</th></tr>{rows}</table>
<h2>Webhook events received ({len(EVENTS)})</h2><table><tr><th>received</th><th>eventType</th><th>emplid</th><th>summary</th><th>desired status</th></tr>{ev}</table>
<h2>Request log</h2><pre>{log}</pre></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9090)
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()
    print(f"Mock Okta listening on http://localhost:{a.port}  (org URL for PeopleSchoft: http://localhost:{a.port}, webhook: http://localhost:{a.port}/webhook)", flush=True)
    s = ThreadingHTTPServer((a.host, a.port), H)
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
