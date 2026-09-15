# PeopleSchoft on a VM — setup for the Okta On-prem Connector (Generic Databases)

Everything runs in containers on one VM. Okta never connects inbound: the Okta agent dials out to your org
and polls, so no firewall rules or public DNS are needed.

```
  VM
  ├── peopleschoft   HR app + UI (port 8080)      writes data/export/hr_master.postgres.sql every 30s
  ├── hr-mirror      loads that file into hr-db   every 30s
  ├── hr-db          Postgres 16, database hrmaster, tables hr_worker / hr_entitlement / hr_worker_v
  └── opc-agent      Okta On-prem SCIM Server agent  ──outbound──▶  your Okta org
```

## Fast path

```bash
git clone git@github.com:coolradish-develop/PeopleSchoft.git && cd PeopleSchoft
python3 scripts/vm_setup.py        # asks the questions, writes .env, generates the files
docker compose up -d --build
```

`vm_setup.py` prompts for the org URL, port, email domain and database password (every answer has a
default), then prints the Okta console values for *your* install at the end. Two more commands worth
knowing:

```bash
python3 scripts/vm_setup.py --verify   # tells you what is misconfigured, including the silent failures
python3 scripts/vm_setup.py --okta     # reprint the Okta walkthrough
```

The rest of this document is the same thing done by hand, plus the reasoning — read it if something
breaks or if you want to understand what the script did.

## 0. What you need before starting

* A Linux VM with Docker and the compose plugin, ~4 GB RAM, ~10 GB free disk. Git.
* Okta admin access to the org you'll demo against (Super Admin, to approve the agent).
* Two files Okta licenses and we cannot ship in the repo:
  * `OktaOnPremScimServer-<version>.rpm` — Okta Admin Console → **Settings → Downloads** → *Okta On-prem SCIM Server agent* (1.5.0+).
  * `postgresql-<version>.jar` — JDBC driver, https://jdbc.postgresql.org/download/

## 1. Clone and configure

```bash
git clone git@github.com:coolradish-develop/PeopleSchoft.git
cd PeopleSchoft
cp .env.example .env
```

Edit `.env`. These are the ones that matter — the rest of the defaults are fine:

```ini
PS_SQL_EXPORT_DIALECT=postgres      # ⚠ empty in the example file = no export at all, nothing works
OKTA_EULA_ACCEPT=yes                # accepts Okta's On-prem SCIM Server EULA (https://www.okta.com/legal/)
PS_HR_DB_HOST=hr-db                 # how the agent reaches the DB; hr-db while the agent runs in compose
OKTA_ORG_URL=https://<your-org>.oktapreview.com
OKTA_MODE=dryrun                    # keep the connector import as the ONLY path into Okta (see note below)
PS_EMAIL_DOMAIN=atko.email
OKTA_OPC_APP_ID=                    # fill in after step 4; makes /hr-master link straight to your app
```

**`PS_SQL_EXPORT_DIALECT` is the one people miss.** It ships empty, which turns the SQL mirror off entirely.
The app will run, the UI will look perfect, and Okta will import nothing, with no error anywhere.

**Leave `OKTA_MODE=dryrun`.** Setting it to `users` turns on a second, unrelated path that pushes changes
straight to Okta via the Users API every 10s, so people appear in Okta without any import and the demo
loses its point. Outbound events get logged instead of sent.

## 2. Generate the container files and start

The compose/Dockerfile are generated, not checked in:

```bash
python3 scripts/generate_docker.py --with-hr-db
docker compose up -d --build
```

Useful flags: `--port 9000` (if 8080 is taken), `--mirror-interval 10` (faster demo loop),
`--okta-ops-password '<something>'` (the DB login the connector uses; default `okta-ops-change-me`),
`--hr-db-engine mysql`. Run with `--print` first if you want to read the files before they're written.

Check it:

```bash
docker compose ps                        # peopleschoft, hr-db, hr-mirror all Up
docker compose logs --tail 3 hr-mirror   # "mirrored hr_master.postgres.sql" within 30s
```

Open `http://<vm>:8080` — 32 seeded employees with `@atko.email` logins. Open **HR as a Source**; it shows
every connector value for this install, including the ones below. Keep that page open during step 5.

The source tree is mounted and `PS_RELOAD=1`, so code changes restart the server by themselves. Rebuild only
if the Dockerfile changes.

## 3. Start the Okta agent

Drop both licensed files into `OktaOnPremAgentResources/` (git-ignored), then:

```bash
docker compose --profile agents up -d --build
docker compose logs -f opc-agent
```

The log prints a URL and a code. Open it as an Okta admin and approve — that's Okta's device-authorization
flow; the agent registers itself and starts polling. Approval state lives in a volume, so restarts don't
re-prompt. In Okta, confirm under **Settings → Downloads → On-prem SCIM Server agents** that it shows
connected.

On an arm64 host (Apple silicon, Ampere VMs) the rpm installs with `--ignorearch` — already handled in the
generated entrypoint, since the package is pure Java.

## 4. Create the Okta app

**Applications → Browse App Catalog → "On-prem Connector for Generic Databases" → Add.**
Provisioning tab → **Configure API Integration**, using:

| Setting | Value |
|---|---|
| Host | `hr-db` (the agent runs in the same compose network) |
| Port | `5432` |
| Database | `hrmaster` |
| User | `okta_ops` |
| Password | whatever you passed to `--okta-ops-password` |

Test the connection before moving on. Then enable **Profile & Lifecycle Sourcing** ("Allow … to source Okta
users") and, under **To Okta**, turn on *Create Users*, *Update User Attributes* and *Deactivate Users*.

Put the resulting app id (`0oa…`, from the browser URL) into `OKTA_OPC_APP_ID` in `.env`.

## 5. Connector SQL

**Provisioning → To Okta → Schema discovery & Import.** Enable each operation, paste the statement, **Save
each one** — an unsaved Get Users is what produces `No getUsers operation defined` at import time.

| Operation | Statement | Extra fields |
|---|---|---|
| Get Users | `SELECT * FROM hr_worker_v WHERE is_deleted = 0` | User ID column: `emplid` |
| Account status | — | Attribute `account_status`, active value `ACTIVE` |
| Incremental import | `SELECT * FROM hr_worker_v WHERE is_deleted = 0 AND last_update_dttm > CAST(? AS TIMESTAMP)` | Parameter 1: `DATABASE_FIELD` / `last_update_dttm`; timestamp column `last_update_dttm` |
| Get User by ID | `SELECT * FROM hr_worker_v WHERE emplid = ?` | |
| Get All Entitlements | `SELECT entitlement_id, entitlement_name, entitlement_type FROM hr_entitlement WHERE is_deleted = 0` | ID `entitlement_id`, display `entitlement_name`, multiple values per user |
| Get User Entitlements | `SELECT entitlement_id FROM hr_worker_entitlement WHERE emplid = ? AND is_deleted = 0` | |

`CAST(? AS TIMESTAMP)` is not optional — the agent binds that parameter as text, and Postgres refuses
`timestamp > character varying`.

## 6. Mappings — the step that surprises people

Run **Import → Import Now** once. Okta discovers the schema and publishes every column as `ext_<column>`
(`ext_first_name`, `ext_title`, …) under the enterprise extension namespace. You now have two sets of
attributes in the profile editor; **the `ext_` ones are the real ones**.

**Directory → Profile Editor →** your app **→ Mappings → app to Okta**, map at minimum:

```
firstName       ← appuser.ext_first_name
lastName        ← appuser.ext_last_name
email, login    ← appuser.ext_email
title           ← appuser.ext_title
department      ← appuser.ext_department
employeeNumber  ← appuser.userName
manager         ← appuser.ext_manager_name
managerId       ← appuser.ext_manager_id
```

Mapping plain `appuser.first_name` fails with `Invalid property first_name in expression` — those attributes
don't exist. Blank names after an import always mean the mappings point at the wrong set.

Then **Import Now** again (full import). You should get ~32 people with titles, departments and managers.
Turn on auto-confirm, or confirm the matches by hand.

## 7. Verify

```bash
docker compose logs --tail 20 opc-agent     # "getAllUsers returned 36 users"
docker compose exec peopleschoft python3 -m peopleschoft status
```

In Okta: Directory → People shows the staff; pick anyone and their profile fields are read-only with the app
as source. The app's Governance tab lists entitlements (`Department - Engineering`, job codes, roles).

Then walk `docs/DEMO-RUNBOOK.md` — hire someone, promote them, transfer them, terminate them, importing
between each step.

## Timing

Change in PeopleSchoft → SQL export (30s) → mirror load (30s) → **Import Now**. Budget a minute before
importing; the two loops are independent and can be out of phase. Okta's scheduled imports bottom out at
hourly, so during a demo you always click Import Now.

## Agent on a separate RHEL host instead

Okta supports the agent on a dedicated RHEL 8/9/10 server. Install the rpm there, point it at the VM
(`PS_HR_DB_HOST=<vm-ip>`, open 5432), and check the host first:

```bash
python3 scripts/opc_preflight.py --db postgres --db-host <vm-ip> \
  --jdbc /path/postgresql.jar --okta-org https://<your-org>.oktapreview.com
```

It checks OS, cores/RAM/disk, JDK 21, OpenSSL 3, the JDBC driver, agent versions and port reachability.

## When it goes wrong

| Symptom | Cause |
|---|---|
| Import returns nothing, no error | `PS_SQL_EXPORT_DIALECT` is empty in `.env` |
| `No getUsers operation defined` | The Get Users statement wasn't saved |
| `operator does not exist: timestamp > character varying` | Missing `CAST(? AS TIMESTAMP)` |
| Names blank after import | Mappings point at plain columns, not `ext_*` |
| `Invalid property first_name in expression` | Same — use `appuser.ext_first_name` |
| New person missing from import | Mirror hasn't run yet; `docker compose logs --tail 3 hr-mirror`, wait, retry |
| Users appear without importing | `OKTA_MODE=users` — set it to `dryrun` |
| Old `gbi.example.com` addresses | `docker compose exec peopleschoft python3 -m peopleschoft reset --yes` |
| Agent disconnected | `docker compose restart opc-agent`; approval survives in the volume |
