# PeopleSchoft - PeopleSoft HCM emulator for identity lifecycle demos

A self-contained, zero-dependency emulation of PeopleSoft HCM built for demonstrating
**joiner / mover / leaver** identity lifecycle management with **Okta**. It runs on plain
Python 3 (standard library only), stores data in SQLite, and is ready the moment you start it.

```
./start.sh            # http://localhost:8080  (seeds the demo organisation on first run)
```

| What | Where |
|---|---|
| Web UI (PeopleSoft-style Job Data pages, actions, Okta outbox) | http://localhost:8080/ |
| REST API | http://localhost:8080/api/v1/workers (Basic `PS` / `PS`) |
| PeopleSoft Integration Broker style alias | http://localhost:8080/PSIGW/RESTListeningConnector/PSFT_HR/WORKER.v1/ |
| SCIM 2.0 endpoint for Okta to push into | http://localhost:8080/scim/v2 (Bearer `peopleschoft-scim-token`) |
| API reference | http://localhost:8080/api-docs |

## What it emulates

* **Effective-dated job data** (`PS_JOB` with `EFFDT` / `EFFSEQ`) driven by PeopleSoft action codes:
  `HIR` hire, `REH` rehire, `XFR` transfer, `PRO` promotion, `DEM`, `PAY`, `DTA` data change,
  `LOA` / `PLA` leave, `RFL` return from leave, `SUS`, `TER` termination, `RET` retirement,
  each with PeopleSoft action reasons (`RES`, `INV`, `PAR`, `MED`, ...).
* **Employee status** (`EMPL_STATUS`): A Active, L Leave, P Paid leave, S Suspended, T Terminated, R Retired,
  plus `HR_STATUS` A/I.
* **Person, employment and setup tables**: `PS_PERSONAL_DATA`, `PS_EMAIL_ADDRESSES`, `PS_PERSON_PHONE`,
  `PS_EMPLOYMENT`, `PS_DEPT_TBL`, `PS_JOBCODE_TBL`, `PS_LOCATION_TBL`, `PS_COMPANY_TBL`.
* **User profiles** (`PSOPRDEFN` / `PSROLEUSER`) as the target when Okta provisions *into* PeopleSoft.
* **Future-dated rows**: a hire dated next week is a *pre-hire*; a termination dated Friday stays
  Active until Friday. Okta events for those wait for their effective date.
* The demo company is **GBI** (Global Business Institute, the classic PeopleSoft demo org) with
  32 people across 10 departments, including someone on leave, someone terminated, a contractor
  and a future-dated pre-hire.

## The UI

Modelled on PeopleSoft 9.2 "classic plus": a Fluid dark header with the NavBar and a tile homepage,
then classic transaction pages underneath.

* **Job Data**: a *Find an Existing Value* search page, then the Work Location / Job Information /
  Compensation tabs with the effective-dated row navigator (*First 1 of N Last*). Click **+** to insert a
  new row: pick the Action and Reason, change only the fields that differ, **Save**. That is how
  transfers, promotions, pay changes, leaves, terminations and rehires are entered, exactly like the real thing.
* **Modify a Person**: names, preferred name, email and phone (DTA data change).
* **Add Employment Instance**: the hire page. A future effective date makes a pre-hire.
* Every page has the classic toolbar: Save, Return to Search, Notify, Refresh, Add, Update/Display, Include History.
* The **Okta Provisioning** tab on Job Data is the one addition PeopleSoft does not have: it shows the Okta profile
  mapping, desired Okta status, and the outbox events for that person.

## The lifecycle journey

Every HR action writes a new `PS_JOB` row and drops an event in the `PS_OKTA_EVENTS` outbox.
A background sync flushes the outbox to Okta (every `OKTA_SYNC_INTERVAL` seconds, default 10).

| Stage | PeopleSoft action | Okta result |
|---|---|---|
| Joiner | HIR hire | user created (STAGED if pre-hire, activated on start date) |
| Mover | PRO / XFR / DTA / PAY | profile updated (title, department, manager, location, name...) |
| Leaver (temporary) | LOA / PLA | user suspended (`OKTA_LOA_ACTION=suspend`) |
| Return | RFL | user unsuspended |
| Leaver | TER / RET | user deactivated on the termination date |
| Rehire | REH | user reactivated |

Run the whole journey for a new person in one go:

```
make demo                                  # CLI, prints every stage
open http://localhost:8080/journey         # UI, one button
curl -u PS:PS -X POST localhost:8080/api/v1/admin/journey
scripts/demo_journey.sh                    # curl walk-through, step by step
```

## Connecting to Okta

Set `OKTA_MODE` in `.env` (copied from `.env.example` on first start) and restart.

### `dryrun` (default, no tenant needed)
Nothing leaves the box. Every event records the exact Okta requests it *would* have sent, for all
three real modes. Open **Okta Integration > event** to see them.

### `users` - drive the Okta Users API directly
```
OKTA_MODE=users
OKTA_ORG_URL=https://dev-123456.okta.com
OKTA_API_TOKEN=00abc...            # SSWS API token (Security > API > Tokens)
OKTA_CUSTOM_ATTRS=off              # on = also send hireDate/terminationDate/jobCode/... (add them to the Okta user schema first)
```
Per event the emulator looks the user up by `profile.employeeNumber` (fallback `profile.login`), then
creates / partially updates the profile and applies the lifecycle call: `activate`, `suspend`,
`unsuspend`, `deactivate`, `reactivate`. Base profile attributes used: login, email, firstName,
lastName, middleName, nickName, displayName, title, department, employeeNumber, managerId, manager,
costCenter, organization, division, mobilePhone, primaryPhone, city, state, countryCode, userType,
secondEmail.

### `identity-source` - Okta "Anything-as-a-Source"
```
OKTA_MODE=identity-source
OKTA_ORG_URL=https://dev-123456.okta.com
OKTA_API_TOKEN=00abc...
OKTA_IDENTITY_SOURCE_ID=0oa...     # id of the Custom Identity Source app in Okta
```
Each sync opens an import session, `bulk-upsert`s joiners/movers, `bulk-delete`s leavers, then
`start-import`. Map the pushed attributes in the Custom Identity Source app's profile editor.
Requires the *Anything-as-a-Source* feature on your org.

### `webhook` - Okta Workflows (or anything that takes a POST)
```
OKTA_MODE=webhook
OKTA_WEBHOOK_URL=https://<org>.workflows.okta.com/api/flo/<id>/invoke
OKTA_WEBHOOK_TOKEN=<client token>  # sent as x-api-client-token
```
Posts the full event (`eventType`, `action`, `effectiveDate`, `changes`, the worker composite,
`oktaProfile`, `oktaDesiredStatus`) to the URL. In Workflows use an **API Endpoint** event card,
branch on `eventType`, and call the Okta connector cards.

### Pull instead of push
Okta Workflows (or any poller) can read the HR source directly:
```
GET /api/v1/workers?changedSince=2026-09-01T00:00:00Z     # delta since last run
GET /api/v1/workers?status=T                               # leavers
GET /api/v1/workers/{emplid}?asOf=2026-10-01               # effective-dated view
```

### Okta -> PeopleSoft (SCIM 2.0)
To show Okta provisioning *into* PeopleSoft user profiles, add an app in Okta:
**Applications > Browse App Catalog > SCIM 2.0 Test App (Header Auth)**, Provisioning tab:

* SCIM connector base URL: `<public URL>/scim/v2` (expose the emulator with ngrok, cloudflared or similar and put that in `PS_PUBLIC_URL`)
* Unique identifier field: `userName`
* Authentication: HTTP Header, token `peopleschoft-scim-token` (`PS_SCIM_TOKEN`)
* Supported actions: Push New Users, Push Profile Updates, Push Deactivation (import is fine too)

Users Okta assigns to the app appear under **User Profiles (SCIM)** as `PSOPRDEFN` rows, linked to
the EMPLID by `employeeNumber` or work email. Deactivation locks the account (`ACCTLOCK=1`).

### No Okta tenant? Use the mock
```
make mock-okta                           # fake Okta org on http://localhost:9090
OKTA_MODE=users OKTA_ORG_URL=http://localhost:9090 OKTA_API_TOKEN=mock ./start.sh
```
The mock supports all three modes (`users`, `identity-source`, and `webhook` at
`http://localhost:9090/webhook`) and shows users, statuses and received events at
http://localhost:9090/.

## Running in a container

The container files are generated rather than checked in:

```
python3 scripts/generate_docker.py        # writes Dockerfile, docker-compose.yml, .dockerignore  (make docker-files)
docker compose up -d --build              # PeopleSchoft on :8080, mock Okta on :9090, data in a named volume
docker compose exec peopleschoft python3 -m peopleschoft demo
```

Options: `--port`, `--python` (base image tag), `--no-mock` (drop the mock Okta service), `--no-live`, `--print`, `--force`.
Inside compose, point the emulator at the mock with `OKTA_ORG_URL=http://mock-okta:9090`.

**No rebuilds while iterating.** The compose file mounts `./peopleschoft` and `./scripts` into the container and sets
`PS_RELOAD=1`, so the container always runs the code in your checkout and restarts itself within a second of a file
change (watch `docker compose logs -f peopleschoft` for `[reload]`). You only rebuild when the Dockerfile changes.
`--no-live` gives you a self-contained image instead. The same `PS_RELOAD=1` works with `./start.sh` outside a container.

## API cheat sheet

Auth: Basic `PS_API_USER:PS_API_PASSWORD` (default `PS:PS`) or `Authorization: Bearer PS_API_TOKEN`.
`PS_API_AUTH=off` disables it. Full reference with examples at `/api-docs`.

```
GET   /api/v1/workers?status=&changedSince=&asOf=&q=&deptid=&limit=&offset=
GET   /api/v1/workers/{emplid}                     (?asOf=YYYY-MM-DD)
POST  /api/v1/workers                              hire: firstName,lastName,deptid,jobcode,hireDate,location,supervisorId,workEmail,compRate,emplClass,reason
PATCH /api/v1/workers/{emplid}                     firstName,lastName,preferredFirstName,workEmail,mobilePhone
POST  /api/v1/workers/{emplid}/actions             {"action":"XFR|PRO|DEM|PAY|DTA|LOA|PLA|RFL|SUS|TER|RET|REH","effdt":..,"reason":..,...}
POST  /api/v1/workers/{emplid}/transfer|promote|demote|pay|manager|leave|return|terminate|retire|rehire|suspend
GET   /api/v1/workers/{emplid}/job-history | /events
GET   /api/v1/departments | /jobcodes | /locations | /companies | /meta | /audit
GET   /api/v1/events?status=PENDING|SCHEDULED|SENT|DRYRUN|FAILED     POST /api/v1/events/{id}/retry
POST  /api/v1/okta/sync      GET /api/v1/okta/status      GET /api/v1/okta/preview/{emplid}     POST /api/v1/okta/export
GET   /api/v1/users                                (PSOPRDEFN, what Okta pushed over SCIM)
POST  /api/v1/admin/journey      POST /api/v1/admin/reset      GET /api/v1/health (no auth)

GET   /PSIGW/RESTListeningConnector/PSFT_HR/WORKER.v1[/{emplid}]      (PeopleSoft IB style aliases)
GET|POST /PSIGW/RESTListeningConnector/PSFT_HR/JOB.v1/{emplid}
```

## CLI

```
python3 -m peopleschoft serve [--port 8080]   # same as ./start.sh
python3 -m peopleschoft seed                  # create + seed if empty
python3 -m peopleschoft reset --yes           # wipe and re-seed
python3 -m peopleschoft demo                  # run the journey and sync
python3 -m peopleschoft okta-sync             # flush the outbox once
python3 -m peopleschoft export                # queue a snapshot of every worker (initial load)
python3 -m peopleschoft status
python3 -m unittest -v                        # tests
```

## Layout

```
peopleschoft/
  config.py     env / .env settings            hr.py        lifecycle engine (actions, effective dating, events)
  db.py         SQLite schema (PS_* tables)    okta.py      outbound connector (dryrun / webhook / users / identity-source)
  seed_data.py  the GBI demo organisation      scim.py      SCIM 2.0 server (inbound)
  api.py        REST + IB aliases + SCIM routes web.py      PeopleSoft-style UI
  server.py     HTTP server, auth, sync thread journey.py   guided joiner/mover/leaver/rehire
scripts/mock_okta.py      fake Okta org        scripts/demo_journey.sh   curl walk-through
tests/test_lifecycle.py   unit + HTTP tests    data/peopleschoft.db      the database (auto-created)
```

## Notes and limits

* One employment record (`EMPL_RCD 0`) per person; job rows are append-only by effective date
  (no correction mode). Same-day rows get incrementing `EFFSEQ`.
* Pre-hires are pushed to Okta `OKTA_PREHIRE_DAYS` before the start date as STAGED and activated on
  the start date. Future-dated terminations send a `worker.termination_scheduled` notice immediately
  and the deactivation on the date. All of that happens in the background sync, so leave the server running
  or run `okta-sync` on a schedule.
* SCIM Groups are not implemented (Okta only needs Users for push provisioning).
* The UI has no login; the API and SCIM endpoints do. Change the defaults in `.env` before exposing it.
