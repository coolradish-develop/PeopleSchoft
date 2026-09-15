#!/usr/bin/env python3
"""Mock Okta Access Gateway: a reverse proxy that performs a fake Okta sign-in and injects identity headers.

Lets you demo PS_UI_AUTH=header without a real OAG appliance.

  python3 scripts/mock_oag.py --port 8443 --upstream http://localhost:8080 [--secret s3cret]
  open http://localhost:8443/          -> "Okta" sign-in page, pick a user and groups, then browse the app

Headers injected (same names PeopleSchoft expects by default): PS_SSO_UID, PS_SSO_EMAIL, PS_SSO_NAME, PS_SSO_GROUPS,
and PS_SSO_SECRET when --secret is given. Paths /oag/login and /oag/logout are handled by the gateway itself.
"""
import argparse
import base64
import http.client
import json
import sys
import urllib.parse
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARGS = None
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade", "content-length", "host"}
PRESETS = [
    ("margaret.chen@atko.email", "Margaret Chen", "Everyone,Executives,HR Administrator"),
    ("aisha.mohammed@atko.email", "Aisha Mohammed", "Everyone,HR Administrator"),
    ("hannah.schmidt@atko.email", "Hannah Schmidt", "Everyone,Engineering"),
    ("amara.diallo@atko.email", "Amara Diallo", "Everyone,IT,Okta Administrators"),
    ("new.contractor@partner.example", "New Contractor", "Everyone"),
]

LOGIN = """<!doctype html><html><head><meta charset="utf-8"><title>Sign In - Okta (mock)</title>
<style>body{font:14px Arial;background:#f5f5f5;margin:0}.card{width:400px;margin:70px auto;background:#fff;border:1px solid #ddd;border-radius:4px;padding:30px;box-shadow:0 2px 6px rgba(0,0,0,.1)}
h1{font-size:15px;color:#5e5e5e;text-align:center;margin:0 0 6px}.logo{text-align:center;font-weight:700;font-size:26px;color:#00297a;letter-spacing:1px;margin-bottom:18px}
label{display:block;font-size:12px;color:#5e5e5e;margin:12px 0 4px}input,select{width:100%;padding:8px;border:1px solid #bbb;border-radius:3px;font-size:13px}
button{width:100%;margin-top:18px;padding:10px;background:#007dc1;color:#fff;border:none;border-radius:3px;font-size:14px;cursor:pointer}
.note{font-size:11px;color:#777;margin-top:14px;text-align:center}</style></head><body><div class="card"><div class="logo">okta</div><h1>Sign In (mock Okta Access Gateway)</h1>
<form method="post" action="/oag/login"><input type="hidden" name="next" value="{next}">
<label>Username</label><select name="uid" onchange="var o=this.options[this.selectedIndex];document.getElementById('name').value=o.dataset.name;document.getElementById('groups').value=o.dataset.groups">{opts}</select>
<label>Display name</label><input id="name" name="name" value="{name0}"><label>Groups (sent as PS_SSO_GROUPS)</label><input id="groups" name="groups" value="{groups0}">
<label>Password</label><input type="password" value="password"><button>Sign In</button></form>
<div class="note">Any password works. The gateway then forwards your requests to {upstream} with PS_SSO_UID / PS_SSO_EMAIL / PS_SSO_NAME / PS_SSO_GROUPS headers{secret}.</div></div></body></html>"""


def session_from_cookie(cookie):
    for part in (cookie or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == "oag_session" and v:
            try:
                return json.loads(base64.urlsafe_b64decode(v + "=" * (-len(v) % 4)).decode())
            except Exception:  # noqa: BLE001
                return None
    return None


class Gateway(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        sys.stderr.write("[oag] " + fmt % a + "\n")

    def _send(self, code, body=b"", headers=None):
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _login_page(self, nxt):
        opts = "".join(f'<option value="{escape(u)}" data-name="{escape(n)}" data-groups="{escape(g)}">{escape(u)}</option>' for u, n, g in PRESETS)
        html = LOGIN.replace("{next}", escape(nxt)).replace("{opts}", opts).replace("{name0}", escape(PRESETS[0][1])).replace("{groups0}", escape(PRESETS[0][2])) \
            .replace("{upstream}", escape(ARGS.upstream)).replace("{secret}", " and PS_SSO_SECRET" if ARGS.secret else "")
        self._send(200, html.encode(), {"Content-Type": "text/html; charset=utf-8"})

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path == "/oag/login":
            return self._login_page(urllib.parse.parse_qs(u.query).get("next", ["/"])[0])
        if u.path == "/oag/logout":
            return self._send(302, b"", {"Location": "/oag/login", "Set-Cookie": "oag_session=; Path=/; Max-Age=0"})
        self._proxy()

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path == "/oag/login":
            n = int(self.headers.get("Content-Length") or 0)
            form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode()).items()}
            sess = {"uid": form.get("uid", ""), "name": form.get("name", ""), "groups": form.get("groups", "")}
            token = base64.urlsafe_b64encode(json.dumps(sess).encode()).decode().rstrip("=")
            return self._send(302, b"", {"Location": form.get("next") or "/", "Set-Cookie": f"oag_session={token}; Path=/; HttpOnly"})
        self._proxy()

    do_PUT = do_PATCH = do_DELETE = do_POST

    def _proxy(self):
        sess = session_from_cookie(self.headers.get("Cookie"))
        if not sess:
            return self._send(302, b"", {"Location": "/oag/login?next=" + urllib.parse.quote(self.path)})
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        up = urllib.parse.urlsplit(ARGS.upstream)
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP and not k.upper().startswith("PS_SSO")}
        headers.update({"Host": up.netloc, "PS_SSO_UID": sess["uid"], "PS_SSO_EMAIL": sess["uid"], "PS_SSO_NAME": sess["name"],
                        "PS_SSO_GROUPS": sess["groups"], "X-Forwarded-For": self.client_address[0], "X-Forwarded-Proto": "http"})
        if ARGS.secret:
            headers["PS_SSO_SECRET"] = ARGS.secret
        if body is not None:
            headers["Content-Length"] = str(len(body))
        try:
            conn = http.client.HTTPConnection(up.hostname, up.port or 80, timeout=30)
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            out = {k: v for k, v in resp.getheaders() if k.lower() not in HOP}
            self._send(resp.status, data, out)
            conn.close()
        except OSError as ex:
            self._send(502, f"Mock OAG could not reach {ARGS.upstream}: {ex}".encode(), {"Content-Type": "text/plain"})


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--upstream", default="http://localhost:8080")
    ap.add_argument("--secret", default="", help="value to send in PS_SSO_SECRET (match PS_SSO_SECRET in the app)")
    ARGS = ap.parse_args()
    print(f"Mock Okta Access Gateway on http://localhost:{ARGS.port} -> {ARGS.upstream}  (sign-in page: /oag/login, logout: /oag/logout)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", ARGS.port), Gateway).serve_forever()


if __name__ == "__main__":
    main()
