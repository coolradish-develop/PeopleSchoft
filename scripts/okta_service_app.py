#!/usr/bin/env python3
"""Create durable Okta credentials that outlive a person and a 30-day token.

Why: SSWS API tokens expire 30 days after last use and only a console Super Admin can mint new ones.
An OAuth service app (client_credentials) has no such expiry and is not tied to anyone's account.

    python3 scripts/okta_service_app.py --dry-run    # show exactly what it will do
    python3 scripts/okta_service_app.py              # do it, then print the secret once

Reads OKTA_ORG_URL and OKTA_API_TOKEN from .env. The token must have Super Admin
(check: it can list /api/v1/api-tokens).

Steps:
  1. create an OAuth service app with grant_type=client_credentials
  2. assign USER_ADMIN + APP_ADMIN roles to it (Okta requires an admin role for API access)
  3. grant the okta.users.* / okta.apps.* scopes
  4. add peopleschoft.operate / peopleschoft.destroy to the MCP authorization server
  5. append OKTA_SVC_CLIENT_ID / OKTA_SVC_CLIENT_SECRET to .env

Everything here is reversible: delete the app in Admin Console > Applications, and the scopes
under Security > API > Authorization Servers.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP_AUTH_SERVER = "aus10mahmrkHMOSxb1d8"
ADMIN_ROLES = ["USER_ADMIN", "APP_ADMIN"]
API_SCOPES = ["okta.users.read", "okta.users.manage", "okta.apps.read", "okta.apps.manage", "okta.logs.read"]
WISHLIST_SCOPES = [
    ("peopleschoft.operate", "Drive a demo: HR actions, pipeline flush, snapshots"),
    ("peopleschoft.destroy", "Reset the database, restore snapshots, delete demo Okta users"),
]


def load_env():
    env = {}
    path = ROOT / ".env"
    if not path.exists():
        sys.exit(".env not found - run scripts/vm_setup.py first")
    for line in path.read_text().splitlines():
        m = re.match(r"^\s*([A-Z_]+)=(.*)$", line)
        if m:
            env[m.group(1)] = m.group(2).strip()
    for key in ("OKTA_ORG_URL", "OKTA_API_TOKEN"):
        if not env.get(key):
            sys.exit(f"{key} is not set in .env")
    return env


def make_caller(org, token):
    def call(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            org + path, data=data, method=method,
            headers={"Authorization": "SSWS " + token, "Accept": "application/json",
                     "Content-Type": "application/json"})
        try:
            return "OK", json.load(urllib.request.urlopen(req, timeout=45))
        except urllib.error.HTTPError as e:
            return f"HTTP {e.code}", e.read().decode()[:300]
        except Exception as e:  # noqa: BLE001 - surface anything, this is a one-shot admin script
            return "ERR", str(e)[:200]
    return call


def main():
    ap = argparse.ArgumentParser(description="Create a durable Okta service app for PeopleSchoft automation")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and exit without changing anything")
    ap.add_argument("--label", default="PeopleSchoft Automation (service)")
    ap.add_argument("--skip-scopes", action="store_true", help="do not touch the MCP authorization server")
    a = ap.parse_args()

    env = load_env()
    org = env["OKTA_ORG_URL"].rstrip("/")
    call = make_caller(org, env["OKTA_API_TOKEN"])

    print(f"org: {org}")
    if a.dry_run:
        print("\nDRY RUN - would:")
        print(f"  1. POST /api/v1/apps                  create service app {a.label!r}")
        print(f"  2. POST /api/v1/apps/<id>/roles       {', '.join(ADMIN_ROLES)}")
        print(f"  3. POST /api/v1/apps/<id>/grants      {', '.join(API_SCOPES)}")
        if not a.skip_scopes:
            print(f"  4. POST /api/v1/authorizationServers/{MCP_AUTH_SERVER}/scopes"
                  f"   {', '.join(n for n, _ in WISHLIST_SCOPES)}")
        print("  5. append OKTA_SVC_CLIENT_ID / OKTA_SVC_CLIENT_SECRET to .env")
        return 0

    print("\n=== 1. create OAuth service app (client_credentials) ===")
    st, app = call("POST", "/api/v1/apps", {
        "name": "oidc_client", "label": a.label, "signOnMode": "OPENID_CONNECT",
        "credentials": {"oauthClient": {"token_endpoint_auth_method": "client_secret_post"}},
        "settings": {"oauthClient": {"grant_types": ["client_credentials"],
                                     "response_types": ["token"], "application_type": "service"}}})
    if st != "OK":
        print("  FAILED:", st, app)
        return 1
    app_id = app["id"]
    creds = app["credentials"]["oauthClient"]
    client_id, secret = creds["client_id"], creds.get("client_secret", "(not returned)")
    print(f"  app id      {app_id}\n  client_id   {client_id}\n  status      {app.get('status')}")

    print("\n=== 2. assign admin roles ===")
    for role in ADMIN_ROLES:
        st, r = call("POST", f"/api/v1/apps/{app_id}/roles", {"type": role})
        print(f"  {role:<11} {st}{'' if st == 'OK' else ' ' + str(r)[:140]}")

    print("\n=== 3. grant Okta API scopes ===")
    for scope in API_SCOPES:
        st, r = call("POST", f"/api/v1/apps/{app_id}/grants", {"scopeId": scope, "issuer": org})
        print(f"  {scope:<20} {st}{'' if st == 'OK' else ' ' + str(r)[:120]}")

    if not a.skip_scopes:
        print("\n=== 4. add wishlist scopes to the MCP authorization server ===")
        for name, desc in WISHLIST_SCOPES:
            st, r = call("POST", f"/api/v1/authorizationServers/{MCP_AUTH_SERVER}/scopes",
                         {"name": name, "displayName": name, "description": desc,
                          "consent": "IMPLICIT", "metadataPublish": "NO_CLIENTS"})
            print(f"  {name:<22} {st}{'' if st == 'OK' else ' ' + str(r)[:140]}")

    print("\n=== 5. write to .env ===")
    with (ROOT / ".env").open("a") as f:
        f.write(f"\n# OAuth service app {app_id} - no 30-day expiry, not tied to a person\n")
        f.write(f"OKTA_SVC_CLIENT_ID={client_id}\nOKTA_SVC_CLIENT_SECRET={secret}\n")
    print("  appended OKTA_SVC_CLIENT_ID / OKTA_SVC_CLIENT_SECRET to .env (git-ignored)")

    print("\n" + "=" * 62)
    print("CLIENT SECRET - Okta shows this once. Store it in a password manager now:")
    print("   ", secret)
    print("=" * 62)
    print("\nVerify it works:")
    print(f"  curl -s -X POST '{org}/oauth2/v1/token' \\")
    print("    -d grant_type=client_credentials -d scope=okta.users.read \\")
    print(f"    -d client_id={client_id} -d client_secret='<secret>'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
