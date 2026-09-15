#!/usr/bin/env python3
"""Interactive setup for a fresh VM: asks the questions, writes .env, generates the container files,
then prints the exact values to paste into Okta.

    python3 scripts/vm_setup.py            # walk through the questions
    python3 scripts/vm_setup.py --verify   # check a running install and say what is wrong
    python3 scripts/vm_setup.py --okta     # reprint the Okta walkthrough for this install

Every answer has a default in [brackets]; press Enter to take it. Nothing is written until the summary
at the end is confirmed.
"""
import argparse
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

C_OK, C_WARN, C_ERR, C_HEAD, C_DIM, C_OFF = "\033[32m", "\033[33m", "\033[31m", "\033[1;36m", "\033[2m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    C_OK = C_WARN = C_ERR = C_HEAD = C_DIM = C_OFF = ""


def head(text):
    print(f"\n{C_HEAD}{text}{C_OFF}\n" + C_DIM + "-" * len(text) + C_OFF)


def ok(m):
    print(f"  {C_OK}OK{C_OFF}    {m}")


def warn(m):
    print(f"  {C_WARN}WARN{C_OFF}  {m}")


def bad(m):
    print(f"  {C_ERR}FAIL{C_OFF}  {m}")


def ask(label, default="", help_text="", validate=None):
    """Prompt until the answer validates. validate(value) -> error string or None."""
    if help_text:
        print(f"{C_DIM}  {help_text}{C_OFF}")
    while True:
        shown = f" [{default}]" if default else ""
        try:
            value = input(f"{label}{shown}: ").strip() or default
        except EOFError:
            print()
            return default
        if validate:
            err = validate(value)
            if err:
                print(f"  {C_ERR}{err}{C_OFF}")
                continue
        return value


def ask_yes(label, default=True):
    d = "Y/n" if default else "y/N"
    while True:
        try:
            v = input(f"{label} [{d}]: ").strip().lower()
        except EOFError:
            print()
            return default
        if not v:
            return default
        if v in ("y", "yes"):
            return True
        if v in ("n", "no"):
            return False


def valid_org(v):
    if not v:
        return "required - the Okta org this demo talks to"
    if not v.startswith("https://"):
        return "must start with https://"
    if not re.match(r"^https://[a-zA-Z0-9.-]+\.(okta|oktapreview|okta-emea)\.com/?$", v):
        return "expected something like https://your-org.oktapreview.com (no path)"
    return None


def valid_port(v):
    if not v.isdigit() or not (1 <= int(v) <= 65535):
        return "must be a port number"
    return None


def valid_domain(v):
    if not re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", v):
        return "expected a bare domain like atko.email"
    return None


def collect():
    head("PeopleSchoft VM setup")
    print("Answers go into .env. You can re-run this any time; nothing is destructive until you confirm.\n")

    org = ask("Okta org URL", "", "The org you will demo against. Your colleague should use their OWN org "
                                  "if you are both running this, or you will collide on logins.", valid_org).rstrip("/")
    port = ask("Port for the PeopleSchoft UI", "8080", "", valid_port)
    domain = ask("Email domain for demo staff", "atko.email",
                 "Logins are generated as first.last@<domain>.", valid_domain)
    company = ask("Company name shown in the UI", "GBI")

    print()
    db_pw = ask("Password for the okta_ops database user", secrets.token_urlsafe(12),
                "The connector logs into the mirror database with this. A random one is fine - "
                "you will paste it into Okta once.")
    interval = ask("Seconds between mirror refreshes", "30",
                   "30 is a good demo rhythm (a change reaches the database in under a minute). "
                   "Use 10 if the pauses feel long.", valid_port)

    print()
    print(f"{C_DIM}  The agent installs Okta's On-prem SCIM Server, covered by https://www.okta.com/legal/{C_OFF}")
    eula = ask_yes("Accept the Okta On-prem SCIM Server EULA?", True)
    if not eula:
        print(f"  {C_WARN}Without this the agent container refuses to install. Setup continues; "
              f"set OKTA_EULA_ACCEPT=yes in .env when ready.{C_OFF}")

    print()
    outbound = ask_yes("Keep the connector import as the only path into Okta?", True)
    if outbound:
        mode = "dryrun"
    else:
        mode = "users"
        print(f"  {C_WARN}OKTA_MODE=users also pushes changes straight to Okta every 10s. People will appear "
              f"in Okta without an import, which undercuts a connector demo.{C_OFF}")

    token = ""
    if mode == "users":
        token = ask("Okta API token (SSWS)", "", "Needed only for the outbound push path.")

    return {
        "OKTA_ORG_URL": org,
        "PS_PORT": port,
        "PS_EMAIL_DOMAIN": domain,
        "PS_COMPANY": company,
        "PS_SQL_EXPORT_DIALECT": "postgres",
        "PS_HR_DB_HOST": "hr-db",
        "OKTA_EULA_ACCEPT": "yes" if eula else "",
        "OKTA_MODE": mode,
        "OKTA_API_TOKEN": token,
        "PS_PUBLIC_URL": f"http://localhost:{port}",
        "_db_password": db_pw,
        "_interval": interval,
    }


def write_env(values, force=False):
    env_path = ROOT / ".env"
    example = ROOT / ".env.example"
    if env_path.exists() and not force:
        if not ask_yes(f"\n.env already exists. Overwrite it?", False):
            print("  keeping the existing .env")
            return False
    lines = example.read_text().splitlines(keepends=True) if example.exists() else []
    settable = {k: v for k, v in values.items() if not k.startswith("_")}
    out, seen = [], set()
    for line in lines:
        m = re.match(r"^#?\s*([A-Z_]+)=", line)
        if m and m.group(1) in settable:
            key = m.group(1)
            out.append(f"{key}={settable[key]}\n")
            seen.add(key)
        else:
            out.append(line)
    missing = [f"{k}={v}\n" for k, v in settable.items() if k not in seen]
    if missing:
        out.append("\n# added by vm_setup.py\n")
        out.extend(missing)
    env_path.write_text("".join(out))
    ok(f"wrote {env_path}")
    return True


def generate(values):
    cmd = [sys.executable, str(ROOT / "scripts" / "generate_docker.py"), "--with-hr-db",
           "--port", values["PS_PORT"], "--mirror-interval", values["_interval"],
           "--okta-ops-password", values["_db_password"], "--force"]
    print()
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        bad("generation failed")
        return False
    return True


def okta_guide(values):
    from peopleschoft import sqlexport
    port = values.get("PS_PORT", "8080")
    head("Now configure Okta (the part containers cannot do for you)")
    print(f"""1. Applications > Browse App Catalog > "On-prem Connector for Generic Databases" > Add.

2. Provisioning tab > Configure API Integration:

     Host        {C_OK}hr-db{C_OFF}          (the agent runs beside the database)
     Port        {C_OK}5432{C_OFF}
     Database    {C_OK}hrmaster{C_OFF}
     User        {C_OK}okta_ops{C_OFF}
     Password    {C_OK}{values.get('_db_password', '(the one in your compose file)')}{C_OFF}

   Test the connection before continuing, then enable Profile & Lifecycle Sourcing and,
   under To Okta, turn on Create Users / Update User Attributes / Deactivate Users.

3. Provisioning > To Okta > Schema discovery & Import. Paste each statement and SAVE EACH ONE
   {C_DIM}(an unsaved Get Users is what causes "No getUsers operation defined" at import time){C_OFF}:
""")
    keys = ["Get Users query", "Get Users - user ID column", "Account Status Attribute (optional but recommended)",
            "Incremental Import query", "Incremental Import - Database Field / Timestamp Column",
            "Get All Entitlements query", "Get All Entitlements - entitlement ID column / display column",
            "Get User by ID (User Specific Import)", "Get User Entitlements (User Specific Import)"]
    settings = sqlexport.connector_settings()
    for k in keys:
        if k in settings:
            print(f"   {C_HEAD}{k}{C_OFF}\n     {settings[k]}\n")
    print(f"""4. Run Import > Import Now once. Okta discovers the schema and publishes every column as an
   {C_OK}ext_<column>{C_OFF} attribute. You will now see two sets of attributes in the profile editor -
   {C_WARN}the ext_ ones are the real ones.{C_OFF}

   Directory > Profile Editor > your app > Mappings > app to Okta:

     firstName       <- appuser.ext_first_name
     lastName        <- appuser.ext_last_name
     email, login    <- appuser.ext_email
     title           <- appuser.ext_title
     department      <- appuser.ext_department
     employeeNumber  <- appuser.userName
     manager         <- appuser.ext_manager_name
     managerId       <- appuser.ext_manager_id

   {C_DIM}Mapping plain appuser.first_name fails with "Invalid property first_name in expression".
   Blank names after an import always mean the mappings point at the wrong set.{C_OFF}

5. Import Now again (full import) - about 32 people with titles, departments and managers.

6. Put the app id from the browser URL (0oa...) into OKTA_OPC_APP_ID in .env, then open
   http://<this-vm>:{port}/hr-master - it links straight to your app and shows these values live.
""")


def verify(values=None):
    head("Checking this install")
    problems = 0
    env_path = ROOT / ".env"
    env = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            m = re.match(r"^\s*([A-Z_]+)=(.*)$", line)
            if m:
                env[m.group(1)] = m.group(2).strip()
        ok(".env found")
    else:
        bad(".env missing - run this script with no arguments")
        return 1

    dialect = env.get("PS_SQL_EXPORT_DIALECT", "")
    if dialect:
        ok(f"PS_SQL_EXPORT_DIALECT={dialect}")
    else:
        bad("PS_SQL_EXPORT_DIALECT is empty - the SQL mirror is OFF. The UI will look fine and Okta "
            "will import nothing, silently. Set it to postgres.")
        problems += 1

    if env.get("OKTA_MODE") == "users":
        warn("OKTA_MODE=users - people will also be pushed to Okta directly every 10s, without an import. "
             "Set it to dryrun for a connector demo.")

    org = env.get("OKTA_ORG_URL", "")
    if valid_org(org):
        warn(f"OKTA_ORG_URL looks wrong: {org or '(empty)'}")
    else:
        ok(f"org {org}")

    if env.get("OKTA_EULA_ACCEPT") != "yes":
        warn("OKTA_EULA_ACCEPT is not yes - the agent container will not install the rpm")

    for name in ("docker-compose.yml", "Dockerfile"):
        if (ROOT / name).exists():
            ok(f"{name} generated")
        else:
            bad(f"{name} missing - run: python3 scripts/generate_docker.py --with-hr-db")
            problems += 1

    agents = ROOT / "OktaOnPremAgentResources"
    if agents.is_dir():
        rpms = list(agents.glob("OktaOnPremScimServer-*.rpm"))
        jars = list(agents.glob("*.jar"))
        (ok if rpms else bad)(f"agent rpm: {rpms[0].name if rpms else 'MISSING - Admin Console > Settings > Downloads'}")
        (ok if jars else bad)(f"JDBC driver: {jars[0].name if jars else 'MISSING - https://jdbc.postgresql.org/download/'}")
        problems += (not rpms) + (not jars)
    else:
        warn(f"{agents.name}/ not found - create it and drop the agent rpm + JDBC jar in")

    export = ROOT / "data" / "export" / f"hr_master.{dialect or 'postgres'}.sql"
    if export.exists():
        age = time.time() - export.stat().st_mtime
        if age < 180:
            ok(f"SQL export is fresh ({int(age)}s old, {export.stat().st_size // 1024} KB)")
        else:
            bad(f"SQL export is {int(age // 60)} min old - the app is not running or the export is off")
            problems += 1
    else:
        warn(f"{export} not written yet - start the stack and wait {env.get('PS_SQL_EXPORT_INTERVAL', '30')}s")

    print()
    if problems:
        print(f"{C_ERR}{problems} problem(s) to fix.{C_OFF}")
    else:
        print(f"{C_OK}Local side looks healthy.{C_OFF} Next: configure Okta "
              f"(python3 scripts/vm_setup.py --okta).")
    return 1 if problems else 0


def main():
    ap = argparse.ArgumentParser(description="Interactive VM setup for PeopleSchoft")
    ap.add_argument("--verify", action="store_true", help="check an existing install instead of setting up")
    ap.add_argument("--okta", action="store_true", help="reprint the Okta walkthrough for this install")
    a = ap.parse_args()

    if a.verify:
        return verify()
    if a.okta:
        env = {}
        if (ROOT / ".env").exists():
            for line in (ROOT / ".env").read_text().splitlines():
                m = re.match(r"^\s*([A-Z_]+)=(.*)$", line)
                if m:
                    env[m.group(1)] = m.group(2).strip()
        # the connector logs in as okta_ops, created by hr-db/init.sql - not the POSTGRES_PASSWORD superuser
        pw = ""
        init_sql = ROOT / "hr-db" / "init.sql"
        if init_sql.exists():
            m = re.search(r"CREATE ROLE okta_ops[^;]*PASSWORD\s+'([^']+)'", init_sql.read_text())
            if m:
                pw = m.group(1)
        env["_db_password"] = pw or "(see hr-db/init.sql)"
        okta_guide(env)
        return 0

    values = collect()

    head("Summary")
    for k, v in values.items():
        if k.startswith("_"):
            continue
        shown = "(set)" if k == "OKTA_API_TOKEN" and v else v or "(empty)"
        print(f"  {k:<24} {shown}")
    print(f"  {'okta_ops password':<24} {values['_db_password']}")
    print(f"  {'mirror interval':<24} {values['_interval']}s")
    if not ask_yes("\nWrite .env and generate the container files?", True):
        print("nothing written")
        return 1

    write_env(values)
    if not generate(values):
        return 1

    head("Start it")
    print(f"""  docker compose up -d --build
  docker compose ps                        {C_DIM}# peopleschoft, hr-db, hr-mirror Up{C_OFF}
  docker compose logs --tail 3 hr-mirror   {C_DIM}# "mirrored hr_master.postgres.sql" within {values['_interval']}s{C_OFF}

  open http://<this-vm>:{values['PS_PORT']}

Then put the Okta agent rpm and the JDBC jar in OktaOnPremAgentResources/ and:

  docker compose --profile agents up -d --build
  docker compose logs -f opc-agent         {C_DIM}# approve the URL + code it prints, as an Okta admin{C_OFF}

Check yourself at any point:   python3 scripts/vm_setup.py --verify""")
    okta_guide(values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
