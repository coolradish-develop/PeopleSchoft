"""Tiny router + request/response helpers shared by the API, SCIM and web modules."""
import json
import re
import urllib.parse
from html import escape as html_escape

ROUTES = []


def route(method, pattern):
    """Register a handler for METHOD + regex pattern (named groups become kwargs)."""
    def deco(fn):
        for m in method.split(","):
            ROUTES.append((m.strip().upper(), re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


def match(method, path):
    for m, rx, fn in ROUTES:
        if m == method:
            mo = rx.match(path)
            if mo:
                return fn, mo.groupdict()
    return None, None


class Request:
    def __init__(self, method, raw_path, headers, body, base_url):
        self.method = method
        parsed = urllib.parse.urlsplit(raw_path)
        self.path = parsed.path.rstrip("/") or "/"
        self.query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
        self.headers = headers
        self.body = body or b""
        self.base_url = base_url
        self._json = None

    def json(self):
        if self._json is None:
            if not self.body.strip():
                self._json = {}
            else:
                try:
                    self._json = json.loads(self.body.decode())
                except ValueError as e:
                    raise BadRequest(f"Invalid JSON body: {e}")
        return self._json

    def form(self):
        ctype = self.headers.get("Content-Type", "")
        if "json" in ctype:
            return self.json()
        return {k: v[0] for k, v in urllib.parse.parse_qs(self.body.decode(), keep_blank_values=True).items()}

    def data(self):
        """JSON or form body, whichever was sent."""
        return self.form()

    def int_query(self, key, default):
        try:
            return int(self.query.get(key, default))
        except (TypeError, ValueError):
            return default


class BadRequest(Exception):
    pass


class Response:
    def __init__(self, body=b"", status=200, content_type="text/html; charset=utf-8", headers=None):
        self.body = body if isinstance(body, bytes) else str(body).encode()
        self.status = status
        self.headers = {"Content-Type": content_type, **(headers or {})}


def json_response(data, status=200, content_type="application/json"):
    return Response(json.dumps(data, indent=2, default=str), status, content_type)


def html_response(html, status=200):
    return Response(html, status)


def redirect(url, msg=None, err=None):
    if msg or err:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{'msg' if msg else 'err'}={urllib.parse.quote(msg or err)}"
    return Response(b"", 303, headers={"Location": url})


def e(v):
    return html_escape("" if v is None else str(v), quote=True)
