"""HTTP server (stdlib only): routes, auth, background Okta sync thread."""
import base64
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import db, hr, okta, sso
from .config import config
from .routing import BadRequest, Request, Response, json_response, match
from .scim import ScimError

# Register routes.
from . import api, web  # noqa: E402,F401


class Handler(BaseHTTPRequestHandler):
    server_version = "PeopleSchoft/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _dispatch(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        host = self.headers.get("Host") or f"localhost:{config.port}"
        proto = self.headers.get("X-Forwarded-Proto", "http")
        req = Request(self.command, self.path, self.headers, body, f"{proto}://{host}")
        req.client_ip = self.client_address[0]
        resp = self._handle(req)
        self.send_response(resp.status)
        for k, v in resp.headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(resp.body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(resp.body)

    def _handle(self, req):
        fn, params = match(req.method, req.path)
        if fn is None:
            if req.path.startswith(("/api/", "/PSIGW/")):
                return json_response({"error": "Not found", "path": req.path}, 404)
            if req.path.startswith("/scim/"):
                return json_response(ScimError(404, "Not found").body(), 404, "application/scim+json")
            return Response("<h1>404 Not Found</h1>", 404)
        conn = db.connect()
        try:
            with db._lock:
                auth_err = check_auth(req, conn)
                if auth_err:
                    return auth_err
                gate = gateway_signon(req, conn)
                if gate:
                    return gate
                return fn(req, conn, **params)
        except hr.HRError as ex:
            if req.path.startswith(("/api/", "/PSIGW/")):
                return json_response({"error": str(ex), "type": "HRError"}, 400)
            from .routing import redirect
            return redirect(req.headers.get("Referer") or "/", err=str(ex))
        except BadRequest as ex:
            return json_response({"error": str(ex)}, 400)
        except ScimError as ex:
            return json_response(ex.body(), ex.status, "application/scim+json")
        except Exception as ex:  # noqa: BLE001
            traceback.print_exc()
            return json_response({"error": f"Internal error: {ex}"}, 500)
        finally:
            conn.close()

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _dispatch


API_PATHS = ("/api/", "/PSIGW/")
SIGNON_PATHS = ("/signon", "/signout")


def gateway_signon(req, conn):
    """PS_UI_AUTH=header: every UI request must carry the gateway identity headers (Okta Access Gateway)."""
    if config.ui_auth != "header" or req.path.startswith("/scim/"):
        return None
    if req.user is None and req.path.startswith(API_PATHS):
        return None   # API request already authenticated by Basic/Bearer in check_auth
    if req.user is None:
        try:
            req.user = sso.authenticate(conn, req.headers, req.client_ip)
        except sso.SSOError as ex:
            if req.path.startswith(API_PATHS):
                return json_response({"error": ex.detail, "title": ex.title}, ex.status)
            return web.sso_error_page(req, ex)
    if req.method not in ("GET", "HEAD") and not req.user.is_admin and req.path not in SIGNON_PATHS:
        detail = (f"{req.user.oprid} is signed on but has no administrator role. Roles: {', '.join(req.user.roles) or 'none'}. "
                  f"Administrator roles: {config.sso_admin_roles}.")
        if req.path.startswith(API_PATHS):
            return json_response({"error": detail, "title": "Not authorized"}, 403)
        return web.sso_error_page(req, sso.SSOError(403, "Not authorized", detail))
    return None


def check_auth(req, conn=None):
    """API + PSIGW: Basic (PS_API_USER/PS_API_PASSWORD), Bearer PS_API_TOKEN, or (when PS_UI_AUTH=header) the
    gateway identity headers. SCIM: Bearer PS_SCIM_TOKEN. UI: open unless PS_UI_AUTH=header."""
    p = req.path
    header = req.headers.get("Authorization", "")
    if p.startswith("/scim/"):
        if header.strip() == f"Bearer {config.scim_token}":
            return None
        return json_response(ScimError(401, "Invalid or missing bearer token").body(), 401, "application/scim+json")
    if p.startswith(("/api/", "/PSIGW/")):
        if config.api_auth == "off" or p in ("/api/v1/health",):
            return None
        if header.startswith("Bearer ") and header[7:].strip() == config.api_token:
            return None
        if header.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(header[6:].strip()).decode().partition(":")
            except Exception:  # noqa: BLE001
                user = pw = None
            if user == config.api_user and pw == config.api_password:
                return None
        if config.ui_auth == "header" and conn is not None and sso.identity_from_headers(req.headers)[0]:
            try:
                req.user = sso.authenticate(conn, req.headers, req.client_ip)
                return None
            except sso.SSOError as ex:
                return json_response({"error": ex.detail, "title": ex.title}, ex.status)
        return Response(json.dumps({"error": "Unauthorized. Use Basic auth (PS_API_USER/PS_API_PASSWORD) or Bearer PS_API_TOKEN."}),
                        401, "application/json", {"WWW-Authenticate": f'Basic realm="{config.brand} Integration Broker"'})
    return None


def ensure_ready():
    conn = db.connect()
    db.init_db(conn)
    if not db.is_seeded(conn):
        print("Seeding demo organisation ...")
        hr.seed(conn)
    conn.close()


def sync_loop(stop_event):
    interval = config.okta_sync_interval
    while not stop_event.is_set():
        stop_event.wait(interval)
        if stop_event.is_set():
            break
        try:
            conn = db.connect()
            with db._lock:
                s = okta.sync_pending(conn)
            conn.close()
            if s["processed"] or s["deferred"]:
                print(f"[okta-sync] mode={s['mode']} processed={s['processed']} sent={s['sent']} dryrun={s['dryrun']} failed={s['failed']} deferred={s['deferred']}")
        except Exception:  # noqa: BLE001
            traceback.print_exc()


def _source_mtimes():
    root = Path(__file__).resolve().parent
    return {p: p.stat().st_mtime for p in root.glob("*.py")}


def reload_watcher(stop_event, interval=1.0):
    """Live reload: when any module file changes, re-exec the server so the new code is served."""
    seen = _source_mtimes()
    while not stop_event.is_set():
        stop_event.wait(interval)
        try:
            now = _source_mtimes()
        except OSError:
            continue
        if now != seen:
            changed = sorted(p.name for p in set(now) | set(seen) if now.get(p) != seen.get(p))
            print(f"[reload] {', '.join(changed)} changed; restarting server", flush=True)
            time.sleep(0.3)  # let editors finish writing
            os.execv(sys.executable, [sys.executable, "-m", "peopleschoft", "serve"] + sys.argv[2:])


def serve(host=None, port=None):
    host, port = host or config.host, port or config.port
    ensure_ready()
    stop = threading.Event()
    if config.okta_sync_interval > 0:
        threading.Thread(target=sync_loop, args=(stop,), daemon=True).start()
    if config.reload:
        threading.Thread(target=reload_watcher, args=(stop,), daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    banner(host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.server_close()


def banner(host, port):
    o = config.okta_summary()
    print(f"""
==================================================================
  PeopleSchoft  -  PeopleSoft HCM emulator for identity lifecycle demos
==================================================================
  Web UI        http://localhost:{port}/
  REST API      http://localhost:{port}/api/v1/workers   (Basic {config.api_user}/{config.api_password} or Bearer {config.api_token})
  PS IB alias   http://localhost:{port}/PSIGW/RESTListeningConnector/PSFT_HR/WORKER.v1/
  SCIM 2.0      http://localhost:{port}/scim/v2          (Bearer {config.scim_token})
  API docs      http://localhost:{port}/api-docs
  Database      {config.db_path}
  Okta mode     {o['mode']}   org={o['orgUrl']}   token={'set' if o['apiTokenSet'] else 'NOT SET'}   sync every {o['syncIntervalSeconds']}s
  UI sign-on    {'header-based (Okta Access Gateway): user id from ' + config.sso_header + ', trusted proxies ' + (config.sso_trusted_proxies or 'any') + ', secret ' + ('set' if config.sso_secret else 'not set') if config.ui_auth == 'header' else 'off (open UI; set PS_UI_AUTH=header for Okta Access Gateway)'}
  Live reload   {'on (PS_RELOAD=1): edits to peopleschoft/*.py restart the server' if config.reload else 'off (set PS_RELOAD=1 to restart on code changes)'}
  Listening on  {host}:{port}
==================================================================
""", flush=True)
