# PeopleSchoft + Okta: customer demo runbook

Story: PeopleSoft is the HR master. Okta imports workers through the **On-prem Connector for Generic
Databases**, treats PeopleSoft as the profile source, discovers entitlements (departments, job codes, roles),
and reacts to joiners, movers and leavers. ~25 minutes.

Two browser tabs: PeopleSchoft (http://localhost:8080) and the Okta Admin Console (sandbox). One terminal.

---

## 0. Before the customer arrives (10 min)

```
docker compose ps                                   # peopleschoft, hr-db, hr-mirror, opc-agent all Up
docker compose exec peopleschoft python3 -m peopleschoft reset --yes   # clean 32-person org, atko.email addresses
docker compose logs --tail 3 hr-mirror              # "mirrored hr_master.postgres.sql" within 30 s
docker compose logs --tail 5 opc-agent              # agent running, no errors
```

In Okta:
* Applications > *On-prem Connector for Generic Databases* > Provisioning tab: agent connected, Get Users /
  Get All Entitlements / Incremental Import configured (values on http://localhost:8080/hr-master).
* Profile & Lifecycle Sourcing enabled ("Allow ... to source Okta users").
* Import tab > **Import Now** > confirm all users (or have Auto-confirm on). After this, Directory > People shows
  the GBI staff with `@atko.email` logins and their titles, departments and managers.
* Delete any leftover demo people from earlier runs (Directory > People, search "atko.email").

Have these open: PeopleSchoft Homepage, PeopleSchoft > HR as a Source, Okta app Import tab, Okta Directory > People,
Okta app Governance tab (entitlements).

Timing rule for every step: PeopleSchoft change -> mirror refresh (<= 30 s) -> Okta **Import Now** (incremental)
-> confirm -> look at the user. Say it out loud once, then it feels natural.

---

## 1. Set the scene (3 min)

* PeopleSchoft Homepage: "This is PeopleSoft HCM. Effective-dated job data, action codes, departments,
  job codes. It is the system of record for people."
* Open **Job Data** > search > pick Hannah Schmidt. Show the Work Location / Job Information tabs and the
  effective-dated history at the bottom: "every change is a new dated row; that is what Okta consumes."
* Open **HR as a Source**: "Okta reads this through its on-prem connector: a small agent that runs the SQL you
  see here against the HR database. No custom code, no inbound firewall rules."
* Okta > Directory > People > Hannah Schmidt: profile fields are read-only and sourced from the app.
  "Okta doesn't own these attributes any more; PeopleSoft does."

## 2. Joiner (5 min)

PeopleSchoft > **Add Employment Instance**:
* First name / last name: the customer's choice. Department Engineering (13000), job code Software Engineer I
  (SWE1), supervisor Marcus Johnson, hire date today. Save.
* Point out the generated login `first.last@atko.email` and the HIR row on Job Data.

Wait for the mirror (30 s), then Okta > app > Import tab > **Import Now** > confirm the one new user.

Show:
* Directory > People: the new person, ACTIVE, with title, department, manager, employee number.
* Their profile: fields locked, source = the app.
* App > Governance tab: entitlements `Department - Engineering`, `Job Code - Software Engineer I`, roles.

Talking point: pre-hires. Hire someone with a start date 3 weeks out: PeopleSchoft holds them as a pre-hire and
they do **not** appear in the export until 14 days before start (`OKTA_PREHIRE_DAYS`). "Accounts exist exactly
when HR says they should, not a month early."

## 3. Mover (5 min)

PeopleSchoft > Job Data > the new person > **+** (insert a row):
* Action **PRO** Promotion, reason Merit, job code Software Engineer II, comp rate 140000. Save.
* **+** again: Action **XFR** Transfer, department Platform Engineering (13100), location Austin, supervisor
  Wei Zhang. Save.
* Show the two new effective-dated rows.

Import Now > confirm. Show in Okta:
* Title and department changed on the profile; manager changed.
* Governance: `Department - Engineering` gone, `Department - Platform Engineering` and the new job code present.
  "Entitlements follow the HR record. Access reviews and policies key off these."

Optional: Modify a Person > change last name (marriage). Import. Name updates in Okta; login stays stable.

## 4. Leaver (4 min)

PeopleSchoft > Job Data > the person > **+**: Action **TER** Termination, reason Resignation, effective date
today. Save. Show `account_status = INACTIVE` on HR as a Source (or in the database).

Import Now > confirm. Show in Okta: the user is **Deprovisioned**. "No ticket, no manual step. HR terminated
them, Okta cut access on the next sync."

Talking point: future-dated terminations. Set the effective date to next Friday instead: the row is in
PeopleSoft now, but `account_status` stays ACTIVE until that date. "Notice period handled by data, not by
someone remembering."

## 5. Leave of absence and rehire (optional, 3 min)

* Rehire: Job Data > **+** > Action **REH**, department IT & Security, job code Identity & Access Engineer.
  Import. The user is reactivated with the new title.
* Leave: **+** > Action **LOA** (parental). The HR feed keeps them active (a leave is not a termination); show
  how the outbound Users API mode would instead suspend them, if the customer asks about leave handling.

## 6. Close (2 min)

* HR as a Source page: the exact connector settings. "This is the whole configuration."
* Okta app > Import tab > schedule: "Hourly incremental imports in production; we ran them by hand today."
* Alternatives in the same demo box: Okta Provisioning Agent SCIM feed (`/hr/scim/v1`), Anything-as-a-Source,
  Okta Workflows webhooks, and Okta -> PeopleSoft SCIM provisioning of user profiles. Show the Okta Integration
  page if they ask about push instead of import.

---

## If something goes wrong

| Symptom | Fix |
|---|---|
| Import says "No getUsers operation defined" | Provisioning > To Okta > Schema discovery & Import: Get Users must be Enabled with the SQL and user ID column `emplid`; click Save |
| Import error on the incremental statement | It must be `... AND last_update_dttm > CAST(? AS TIMESTAMP)` (the agent binds the value as text) |
| Names blank after import | Mappings must point at the discovered `ext_` attributes (Profile Editor > app > Mappings), not at plain column names |
| New person not in the import | Wait 30 s for hr-mirror (`docker compose logs --tail 3 hr-mirror`), then Import Now again |
| Old `gbi.example.com` addresses | `docker compose exec peopleschoft python3 -m peopleschoft reset --yes` |
| Agent shows disconnected in Okta | `docker compose restart opc-agent`; approval state is kept in the volume |
| Import created a user with the wrong login | Delete that Okta user; the next import recreates it from the current data |

## Reset between demos

```
docker compose exec peopleschoft python3 -m peopleschoft reset --yes
```
Then in Okta delete the demo people you created (they will not be recreated: the reset removes them from HR
too), and run one full import to realign. Seeded staff remain and match.
