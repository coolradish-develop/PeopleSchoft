"""HR-master SQL export for the Okta On-prem Connector for Generic Databases (Identity Governance).

The connector runs SQL you configure against Oracle / MySQL / PostgreSQL / Db2 / SQL Server and needs:
soft deletes (no hard-deleted rows), an auto-updating timestamp column on every table, a status column
for "Account Status Attribute", and user + entitlement tables. This module renders that schema and the
current PeopleSoft state as idempotent upsert SQL, so a mirror database can be kept in sync:

  python3 -m peopleschoft export-sql --dialect postgres > hr_master.sql
  GET /api/v1/export/sql?dialect=postgres[&since=ISO][&ddl=0]

Tables (lower case):  hr_worker, hr_entitlement, hr_worker_entitlement, view hr_worker_v
"""
from datetime import datetime, timezone

from . import db, hr, hrscim

DIALECTS = ("postgres", "mysql", "mssql", "oracle", "db2", "sqlite")   # the five databases Okta supports, plus sqlite for tests
MERGE_DUMMY = {"mssql": "", "oracle": " FROM dual", "db2": " FROM SYSIBM.SYSDUMMY1"}

WORKER_COLS = ["emplid", "user_name", "email", "first_name", "last_name", "middle_name", "preferred_name", "display_name", "title", "jobcode",
               "job_family", "grade", "deptid", "department", "location", "city", "state", "country", "company", "business_unit",
               "manager_id", "manager_name", "manager_email", "mobile_phone", "work_phone", "empl_status", "empl_status_descr", "hr_status",
               "account_status", "empl_class", "reg_temp", "full_part_time", "action", "action_reason", "effective_date",
               "hire_dt", "orig_hire_dt", "rehire_dt", "termination_dt", "last_date_worked", "pre_hire", "is_deleted", "last_update_dttm"]
ENT_COLS = ["entitlement_id", "entitlement_name", "entitlement_type", "is_deleted", "last_update_dttm"]
WE_COLS = ["emplid", "entitlement_id", "is_deleted", "last_update_dttm"]


def _types(dialect):
    ts = {"postgres": "TIMESTAMP", "mysql": "DATETIME", "mssql": "DATETIME2", "oracle": "TIMESTAMP", "db2": "TIMESTAMP", "sqlite": "TEXT"}[dialect]
    vc = "VARCHAR2" if dialect == "oracle" else "VARCHAR"
    return {"str": f"{vc}(255)", "code": f"{vc}(50)", "int": {"mssql": "INT", "oracle": "NUMBER(1)"}.get(dialect, "INTEGER"), "date": f"{vc}(10)", "ts": ts}


def ddl(dialect):
    t = _types(dialect)
    w_cols = ", ".join(f"{c} {t['code'] if c in ('emplid','jobcode','deptid','location','company','business_unit','manager_id','empl_status','hr_status','account_status','empl_class','reg_temp','full_part_time','action','action_reason','job_family','grade','country','state') else t['date'] if c.endswith('_dt') or c in ('effective_date','last_date_worked') else t['int'] if c in ('pre_hire','is_deleted') else t['ts'] if c == 'last_update_dttm' else t['str']}"
                       + (" PRIMARY KEY" if c == "emplid" else " NOT NULL DEFAULT 0" if c in ("is_deleted", "pre_hire") else "") for c in WORKER_COLS)
    out = [
        f"CREATE TABLE {_ine(dialect, 'hr_worker')} ({w_cols});",
        f"CREATE TABLE {_ine(dialect, 'hr_entitlement')} (entitlement_id {t['str']} PRIMARY KEY, entitlement_name {t['str']}, entitlement_type {t['code']}, is_deleted {t['int']} NOT NULL DEFAULT 0, last_update_dttm {t['ts']});",
        f"CREATE TABLE {_ine(dialect, 'hr_worker_entitlement')} (emplid {t['code']}, entitlement_id {t['str']}, is_deleted {t['int']} NOT NULL DEFAULT 0, last_update_dttm {t['ts']}, PRIMARY KEY (emplid, entitlement_id));",
    ]
    if dialect == "postgres":
        out += [
            "CREATE OR REPLACE FUNCTION hr_touch() RETURNS trigger AS $$ BEGIN NEW.last_update_dttm = now() at time zone 'utc'; RETURN NEW; END; $$ LANGUAGE plpgsql;",
            "DROP TRIGGER IF EXISTS hr_worker_touch ON hr_worker; CREATE TRIGGER hr_worker_touch BEFORE UPDATE ON hr_worker FOR EACH ROW WHEN (NEW.last_update_dttm IS NOT DISTINCT FROM OLD.last_update_dttm) EXECUTE FUNCTION hr_touch();",
            "DROP TRIGGER IF EXISTS hr_entitlement_touch ON hr_entitlement; CREATE TRIGGER hr_entitlement_touch BEFORE UPDATE ON hr_entitlement FOR EACH ROW WHEN (NEW.last_update_dttm IS NOT DISTINCT FROM OLD.last_update_dttm) EXECUTE FUNCTION hr_touch();",
            "DROP TRIGGER IF EXISTS hr_worker_entitlement_touch ON hr_worker_entitlement; CREATE TRIGGER hr_worker_entitlement_touch BEFORE UPDATE ON hr_worker_entitlement FOR EACH ROW WHEN (NEW.last_update_dttm IS NOT DISTINCT FROM OLD.last_update_dttm) EXECUTE FUNCTION hr_touch();",
            "CREATE OR REPLACE VIEW hr_worker_v AS SELECT w.*, (SELECT string_agg(we.entitlement_id, ',' ORDER BY we.entitlement_id) FROM hr_worker_entitlement we WHERE we.emplid = w.emplid AND we.is_deleted = 0) AS entitlements FROM hr_worker w;",
        ]
    elif dialect == "mysql":
        out += ["CREATE OR REPLACE VIEW hr_worker_v AS SELECT w.*, (SELECT GROUP_CONCAT(we.entitlement_id ORDER BY we.entitlement_id) FROM hr_worker_entitlement we WHERE we.emplid = w.emplid AND we.is_deleted = 0) AS entitlements FROM hr_worker w;"]
    elif dialect == "mssql":
        out += ["IF OBJECT_ID('hr_worker_v', 'V') IS NOT NULL DROP VIEW hr_worker_v;",
                "CREATE VIEW hr_worker_v AS SELECT w.*, (SELECT STRING_AGG(we.entitlement_id, ',') FROM hr_worker_entitlement we WHERE we.emplid = w.emplid AND we.is_deleted = 0) AS entitlements FROM hr_worker w;"]
    elif dialect == "oracle":
        out = ["-- Oracle: CREATE TABLE has no IF NOT EXISTS; ignore ORA-00955 (name already used) on re-runs"] + out + [
            "CREATE OR REPLACE VIEW hr_worker_v AS SELECT w.*, (SELECT LISTAGG(we.entitlement_id, ',') WITHIN GROUP (ORDER BY we.entitlement_id) FROM hr_worker_entitlement we WHERE we.emplid = w.emplid AND we.is_deleted = 0) AS entitlements FROM hr_worker w;"]
    elif dialect == "db2":
        out = ["-- Db2 LUW: CREATE TABLE has no IF NOT EXISTS; ignore SQL0601N (already exists) on re-runs. Requires OPS agent 1.7.0 or later"] + out + [
            "CREATE OR REPLACE VIEW hr_worker_v AS SELECT w.*, (SELECT LISTAGG(we.entitlement_id, ',') WITHIN GROUP (ORDER BY we.entitlement_id) FROM hr_worker_entitlement we WHERE we.emplid = w.emplid AND we.is_deleted = 0) AS entitlements FROM hr_worker w;"]
    elif dialect == "sqlite":
        out += ["CREATE VIEW IF NOT EXISTS hr_worker_v AS SELECT w.*, (SELECT group_concat(we.entitlement_id, ',') FROM hr_worker_entitlement we WHERE we.emplid = w.emplid AND we.is_deleted = 0) AS entitlements FROM hr_worker w;"]
    return out


def _ine(dialect, table):
    return f"IF NOT EXISTS {table}" if dialect in ("postgres", "mysql", "sqlite") else table


def _q(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _ts(v):
    """ISO 'YYYY-MM-DDTHH:MM:SSZ' -> 'YYYY-MM-DD HH:MM:SS' for SQL timestamp columns."""
    return v.replace("T", " ").replace("Z", "") if v else None


def upsert(dialect, table, cols, row, key):
    vals = ", ".join(_q(row[c]) for c in cols)
    sets = ", ".join(f"{c} = {_q(row[c])}" for c in cols if c not in key)
    if dialect in ("postgres", "sqlite"):
        return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({vals}) ON CONFLICT ({', '.join(key)}) DO UPDATE SET {sets};"
    if dialect == "mysql":
        return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({vals}) ON DUPLICATE KEY UPDATE {sets};"
    # MERGE for SQL Server, Oracle and Db2 (Oracle/Db2 need a dummy source table and no AS before the alias)
    on = " AND ".join(f"t.{k} = s.{k}" for k in key)
    src = ", ".join(f"{_q(row[c])} AS {c}" for c in cols)
    into, as_ = ("INTO ", "") if dialect in ("oracle", "db2") else ("", "AS ")
    return (f"MERGE {into}{table} {as_}t USING (SELECT {src}{MERGE_DUMMY[dialect]}) {as_}s ON ({on}) WHEN MATCHED THEN UPDATE SET {sets} "
            f"WHEN NOT MATCHED THEN INSERT ({', '.join(cols)}) VALUES ({', '.join('s.' + c for c in cols)});")


def worker_ts(conn, w):
    """User-row timestamp. Okta's guide: the User table's timestamp must reflect entitlement-only changes, otherwise
    Incremental Import cannot detect them. Roles (PSROLEUSER) change through the user profile, so include its update time."""
    ts = hrscim.last_modified(w)
    prof = db.row(conn, "SELECT MAX(LASTUPDDTTM) AS T FROM PSOPRDEFN WHERE EMPLID=?", (w["emplid"],))
    if prof and prof["T"] and prof["T"] > ts:
        ts = prof["T"]
    return ts


def worker_row(w, ts=None):
    j = w.get("job") or {}
    # Same rule as the SCIM feed: pre-hires are exported only inside the pre-hire window, and count as active
    # so Okta creates them ahead of their start date instead of deactivating them.
    active = w["emplStatus"] in hr.ACTIVE_STATUSES
    return {"emplid": w["emplid"], "user_name": w["workEmail"], "email": w["workEmail"], "first_name": w["firstName"], "last_name": w["lastName"],
            "middle_name": w.get("middleName") or None, "preferred_name": w.get("preferredFirstName") or None, "display_name": w["displayName"],
            "title": j.get("jobTitle"), "jobcode": j.get("jobcode"), "job_family": j.get("jobFamily"), "grade": j.get("grade"), "deptid": j.get("deptid"),
            "department": j.get("deptDescr"), "location": j.get("location"), "city": j.get("city") or None, "state": j.get("state") or None,
            "country": j.get("locationCountry") or w.get("country"), "company": j.get("company"), "business_unit": j.get("businessUnit"),
            "manager_id": j.get("supervisorId") or None, "manager_name": j.get("supervisorName") or None, "manager_email": j.get("supervisorEmail") or None,
            "mobile_phone": w.get("mobilePhone") or None, "work_phone": w.get("workPhone") or None, "empl_status": w["emplStatus"],
            "empl_status_descr": w["emplStatusDescr"], "hr_status": w["hrStatus"], "account_status": "ACTIVE" if active else "INACTIVE",
            "empl_class": j.get("emplClass"), "reg_temp": j.get("regTemp"), "full_part_time": j.get("fullPartTime"), "action": j.get("action"),
            "action_reason": j.get("actionReason"), "effective_date": j.get("effdt"), "hire_dt": w.get("hireDate"), "orig_hire_dt": w.get("originalHireDate"),
            "rehire_dt": w.get("rehireDate"), "termination_dt": w.get("terminationDate"), "last_date_worked": w.get("lastDateWorked"),
            "pre_hire": 1 if w.get("preHire") else 0, "is_deleted": 0, "last_update_dttm": _ts(ts or hrscim.last_modified(w))}


def entitlements(conn):
    """Entitlement catalogue: departments, job codes and PeopleSoft roles."""
    ents = []
    for d in db.rows(conn, "SELECT DEPTID, DESCR FROM PS_DEPT_TBL ORDER BY DEPTID"):
        ents.append({"entitlement_id": f"DEPT:{d['DEPTID']}", "entitlement_name": f"Department - {d['DESCR']}", "entitlement_type": "DEPARTMENT"})
    for j in db.rows(conn, "SELECT JOBCODE, DESCR FROM PS_JOBCODE_TBL ORDER BY JOBCODE"):
        ents.append({"entitlement_id": f"JOBCODE:{j['JOBCODE']}", "entitlement_name": f"Job Code - {j['DESCR']}", "entitlement_type": "JOBCODE"})
    roles = sorted({r["ROLENAME"] for r in db.rows(conn, "SELECT DISTINCT ROLENAME FROM PSROLEUSER")} | {"PeopleSoft User", "Employee", "HR Administrator", "PeopleSoft Administrator"})
    for r in roles:
        ents.append({"entitlement_id": f"ROLE:{r}", "entitlement_name": f"Role - {r}", "entitlement_type": "ROLE"})
    return ents


def worker_entitlements(conn, w):
    j = w.get("job") or {}
    out = []
    if j.get("deptid"):
        out.append(f"DEPT:{j['deptid']}")
    if j.get("jobcode"):
        out.append(f"JOBCODE:{j['jobcode']}")
    for r in db.rows(conn, "SELECT r.ROLENAME FROM PSROLEUSER r JOIN PSOPRDEFN o ON o.OPRID=r.ROLEUSER WHERE o.EMPLID=?", (w["emplid"],)):
        out.append(f"ROLE:{r['ROLENAME']}")
    return out


def render(conn, dialect="postgres", since=None, include_ddl=True):
    if dialect not in DIALECTS:
        raise ValueError(f"dialect must be one of {DIALECTS}")
    now = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"-- PeopleSchoft HR master export ({dialect}) generated {now} UTC" + (f", changes since {since}" if since else ", full state"),
             "-- Tables: hr_worker (users), hr_entitlement (catalogue), hr_worker_entitlement (assignments), view hr_worker_v (users + entitlements csv)"]
    if include_ddl:
        lines += ddl(dialect)
    ent_ts = now
    for ent in entitlements(conn):
        lines.append(upsert(dialect, "hr_entitlement", ENT_COLS, {**ent, "is_deleted": 0, "last_update_dttm": ent_ts}, ["entitlement_id"]))
    workers, _ = hr.list_workers(conn, limit=100000)
    workers = [w for w in workers if hrscim.visible(w) and (not since or worker_ts(conn, w) > since)]
    for w in workers:
        row = worker_row(w, worker_ts(conn, w))
        lines.append(upsert(dialect, "hr_worker", WORKER_COLS, row, ["emplid"]))
        ids = worker_entitlements(conn, w)
        for eid in ids:
            lines.append(upsert(dialect, "hr_worker_entitlement", WE_COLS, {"emplid": w["emplid"], "entitlement_id": eid, "is_deleted": 0, "last_update_dttm": row["last_update_dttm"]}, ["emplid", "entitlement_id"]))
        not_in = ", ".join(_q(i) for i in ids) or "''"
        lines.append(f"UPDATE hr_worker_entitlement SET is_deleted = 1, last_update_dttm = {_q(row['last_update_dttm'])} WHERE emplid = {_q(w['emplid'])} AND is_deleted = 0 AND entitlement_id NOT IN ({not_in});")
    lines.append(f"-- {len(workers)} worker(s) exported")
    return "\n".join(lines) + "\n"


def connector_settings():
    """Values to paste into the Okta On-prem Connector for Generic Databases (Provisioning tab)."""
    # Field order follows Okta's guide: Provisioning tab > Integration > Schema discovery & Import, then Database Operations.
    return {
        "Get Users": "Enabled - SQL Statement",
        "Get Users query": "SELECT * FROM hr_worker_v WHERE is_deleted = 0",
        "Get Users - user ID column": "emplid",
        "Get All Entitlements": "Enabled - SQL Statement",
        "Get All Entitlements query": "SELECT entitlement_id, entitlement_name, entitlement_type FROM hr_entitlement WHERE is_deleted = 0",
        "Get All Entitlements - entitlement ID column / display column": "entitlement_id / entitlement_name",
        "Get User by ID (User Specific Import)": "Enabled - SQL Statement: SELECT * FROM hr_worker_v WHERE emplid = ?   (user ID column emplid)",
        "Get User Entitlements (User Specific Import)": "Enabled - SQL Statement: SELECT entitlement_id FROM hr_worker_entitlement WHERE emplid = ? AND is_deleted = 0   (entitlement column entitlement_id)",
        "Where to enter these": "Provisioning tab > To Okta > Schema discovery & Import (the Database operations page only shows status)",
        "Enable Single Entitlements per User": "leave OFF (workers hold a department, a job code and roles at once; this setting is permanent once entitlements are discovered)",
        "Account Status Attribute (optional but recommended)": "column account_status, active value ACTIVE   (without it Okta never deactivates imported users)",
        "Incremental Import": "Enabled - SQL Statement",
        "Incremental Import query": "SELECT * FROM hr_worker_v WHERE is_deleted = 0 AND last_update_dttm > CAST(? AS TIMESTAMP)   (? = last import time, bound as text by the agent; MySQL: CAST(? AS DATETIME), SQL Server: CAST(? AS DATETIME2))",
        "Incremental Import - Database Field / Timestamp Column": "last_update_dttm / last_update_dttm",
        "User entitlements": "hr_worker_v.entitlements (comma-separated entitlement_id values per user); detail rows in hr_worker_entitlement",
        "Database requirements met by the mirror": "soft deletes (is_deleted), auto-updating last_update_dttm on every table, user row timestamp moves on entitlement-only changes",
        "Attribute mapping suggestions": "user_name->userName/login, email->email, first_name->firstName, last_name->lastName, display_name->displayName, title->title, department->department, emplid->employeeNumber, manager_id->managerId, manager_email->manager, deptid->costCenter, company->organization, business_unit->division, mobile_phone->mobilePhone, city/state/country",
        "To App (Create User / Update User / Deactivate User)": "leave disabled: PeopleSoft is the HR master and Okta only imports. If you enable them, map the parameters of your INSERT/UPDATE statements to Okta user attributes",
    }
