"""HR lifecycle engine: effective-dated PS_JOB rows driven by PeopleSoft ACTION codes.

Joiner  -> HIR (hire), REH (rehire)
Mover   -> XFR (transfer), PRO (promotion), DEM (demotion), PAY (pay change), DTA (data change), POS (position change)
Leaver  -> TER (termination), RET (retirement), LOA/PLA (leave), RFL (return from leave), SUS (suspension)
"""
import json
from datetime import date, datetime, timedelta

from . import db
from .config import config

ACTIONS = {
    "HIR": "Hire", "REH": "Rehire", "XFR": "Transfer", "PRO": "Promotion", "DEM": "Demotion",
    "PAY": "Pay Rate Change", "DTA": "Data Change", "POS": "Position Change",
    "LOA": "Leave of Absence", "PLA": "Paid Leave of Absence", "RFL": "Return from Leave",
    "SUS": "Suspension", "TER": "Termination", "RET": "Retirement",
}
# Actions that set a new EMPL_STATUS; all others inherit the previous status.
ACTION_STATUS = {"HIR": "A", "REH": "A", "RFL": "A", "LOA": "L", "PLA": "P", "SUS": "S", "TER": "T", "RET": "R"}
STATUS_LABELS = {"A": "Active", "L": "Leave of Absence", "P": "Leave With Pay", "S": "Suspended",
                 "T": "Terminated", "R": "Retired", "D": "Deceased", "Q": "Retired With Pay", "V": "Terminated With Pay"}
ACTIVE_STATUSES = ("A", "L", "P", "S")
REASONS = {
    "HIR": {"NEW": "New Position", "REP": "Replacement", "CNV": "Conversion", "ACQ": "Acquisition"},
    "REH": {"REH": "Rehire", "RET": "Return from Retirement"},
    "XFR": {"DEP": "Department Transfer", "LOC": "Location Change", "MGR": "Manager Change", "REO": "Reorganization"},
    "PRO": {"MER": "Merit", "REC": "Reclassification", "CAR": "Career Progression"},
    "DEM": {"PER": "Performance", "VOL": "Voluntary"},
    "PAY": {"MER": "Merit Increase", "ADJ": "Market Adjustment", "COL": "Cost of Living"},
    "DTA": {"NAM": "Name Change", "EML": "Email Change", "MGR": "Supervisor Change", "COR": "Correction"},
    "POS": {"POS": "Position Data Change"},
    "LOA": {"MED": "Medical", "PAR": "Parental", "MIL": "Military", "PER": "Personal", "SAB": "Sabbatical"},
    "PLA": {"MED": "Medical", "PAR": "Parental", "JUR": "Jury Duty"},
    "RFL": {"RFL": "Return from Leave"},
    "SUS": {"DIS": "Disciplinary", "INV": "Investigation"},
    "TER": {"RES": "Resignation", "INV": "Involuntary", "EOC": "End of Contract", "RIF": "Reduction in Force",
            "MUT": "Mutual Agreement", "DEA": "Death"},
    "RET": {"RET": "Retirement", "ERT": "Early Retirement"},
}
EMPL_CLASS = {"E": "Employee", "C": "Contractor", "I": "Intern", "T": "Temporary", "X": "Consultant"}

JOB_FIELDS = ("DEPTID", "JOBCODE", "POSITION_NBR", "LOCATION", "COMPANY", "BUSINESS_UNIT", "REG_TEMP",
              "FULL_PART_TIME", "EMPL_CLASS", "SUPERVISOR_ID", "REPORTS_TO", "COMPRATE", "CURRENCY_CD",
              "COMP_FREQUENCY", "STD_HOURS", "PAYGROUP")


class HRError(Exception):
    """Business-rule violation, surfaced as HTTP 400."""


def today():
    return date.today().isoformat()


def _valid_date(value, field="effdt"):
    if not value:
        return today()
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise HRError(f"{field} must be YYYY-MM-DD, got {value!r}")


# --------------------------------------------------------------------------- lookups
def dept(conn, deptid):
    return db.row(conn, "SELECT * FROM PS_DEPT_TBL WHERE DEPTID=?", (deptid,))


def jobcode(conn, code):
    return db.row(conn, "SELECT * FROM PS_JOBCODE_TBL WHERE JOBCODE=?", (code,))


def location(conn, loc):
    return db.row(conn, "SELECT * FROM PS_LOCATION_TBL WHERE LOCATION=?", (loc,))


def _require(conn, table, key, value, label):
    if not value:
        return
    if not db.row(conn, f"SELECT 1 FROM {table} WHERE {key}=?", (value,)):
        raise HRError(f"Unknown {label}: {value!r}")


def _validate_refs(conn, fields):
    _require(conn, "PS_DEPT_TBL", "DEPTID", fields.get("DEPTID"), "DEPTID")
    _require(conn, "PS_JOBCODE_TBL", "JOBCODE", fields.get("JOBCODE"), "JOBCODE")
    _require(conn, "PS_LOCATION_TBL", "LOCATION", fields.get("LOCATION"), "LOCATION")
    sup = fields.get("SUPERVISOR_ID")
    if sup:
        _require(conn, "PS_PERSONAL_DATA", "EMPLID", sup, "SUPERVISOR_ID")


# --------------------------------------------------------------------------- job rows
def current_job(conn, emplid, asof=None, empl_rcd=0):
    """Effective-dated lookup: the row with the greatest EFFDT <= asof, then greatest EFFSEQ."""
    asof = asof or today()
    return db.row(conn, """SELECT * FROM PS_JOB WHERE EMPLID=? AND EMPL_RCD=? AND EFFDT<=?
                           ORDER BY EFFDT DESC, EFFSEQ DESC LIMIT 1""", (emplid, empl_rcd, asof))


def latest_job(conn, emplid, empl_rcd=0):
    """Most recent row regardless of date (includes future-dated rows)."""
    return db.row(conn, "SELECT * FROM PS_JOB WHERE EMPLID=? AND EMPL_RCD=? ORDER BY EFFDT DESC, EFFSEQ DESC LIMIT 1",
                  (emplid, empl_rcd))


def job_history(conn, emplid, empl_rcd=0):
    return db.rows(conn, """SELECT j.*, d.DESCR AS DEPT_DESCR, c.DESCR AS JOB_DESCR, l.DESCR AS LOC_DESCR
                            FROM PS_JOB j LEFT JOIN PS_DEPT_TBL d ON d.DEPTID=j.DEPTID
                            LEFT JOIN PS_JOBCODE_TBL c ON c.JOBCODE=j.JOBCODE
                            LEFT JOIN PS_LOCATION_TBL l ON l.LOCATION=j.LOCATION
                            WHERE j.EMPLID=? AND j.EMPL_RCD=? ORDER BY j.EFFDT DESC, j.EFFSEQ DESC""",
                   (emplid, empl_rcd))


def insert_job_row(conn, emplid, effdt, action, reason="", overrides=None, oprid="PS", empl_rcd=0):
    overrides = {k: v for k, v in (overrides or {}).items() if k in JOB_FIELDS and v is not None and v != ""}
    if action not in ACTIONS:
        raise HRError(f"Unknown ACTION {action!r}. Valid: {', '.join(sorted(ACTIONS))}")
    effdt = _valid_date(effdt)
    prev = latest_job(conn, emplid, empl_rcd)
    if prev is None and action not in ("HIR",):
        raise HRError(f"{emplid} has no job data; only HIR is valid")
    if prev is not None and effdt < prev["EFFDT"]:
        raise HRError(f"Effective date {effdt} is before the latest job row ({prev['EFFDT']} {prev['ACTION']} "
                      f"{ACTIONS.get(prev['ACTION'], '')}). Job rows are append-only; use {prev['EFFDT']} or later")
    _validate_refs(conn, overrides)
    if overrides.get("SUPERVISOR_ID") == emplid:
        raise HRError("An employee cannot be their own supervisor")
    if "COMPRATE" in overrides:
        try:
            overrides["COMPRATE"] = float(overrides["COMPRATE"])
        except (TypeError, ValueError):
            raise HRError("COMPRATE must be numeric")

    new = {k: (prev[k] if prev else None) for k in JOB_FIELDS}
    if prev is None:
        new.update({"COMPANY": config.company, "BUSINESS_UNIT": "US001", "REG_TEMP": "R", "FULL_PART_TIME": "F",
                    "EMPL_CLASS": "E", "CURRENCY_CD": "USD", "COMP_FREQUENCY": "A", "STD_HOURS": 40,
                    "PAYGROUP": "KU1", "SUPERVISOR_ID": "", "REPORTS_TO": "", "POSITION_NBR": "", "COMPRATE": 0})
    new.update(overrides)
    status = ACTION_STATUS.get(action) or (prev["EMPL_STATUS"] if prev else "A")
    seq_row = conn.execute("SELECT MAX(EFFSEQ) FROM PS_JOB WHERE EMPLID=? AND EMPL_RCD=? AND EFFDT=?",
                           (emplid, empl_rcd, effdt)).fetchone()
    effseq = 0 if seq_row[0] is None else seq_row[0] + 1
    ts = db.now_iso()
    conn.execute(f"""INSERT INTO PS_JOB (EMPLID, EMPL_RCD, EFFDT, EFFSEQ, ACTION, ACTION_REASON, ACTION_DT,
                     EMPL_STATUS, HR_STATUS, LASTUPDDTTM, LASTUPDOPRID, {', '.join(JOB_FIELDS)})
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,{','.join('?' * len(JOB_FIELDS))})""",
                 (emplid, empl_rcd, effdt, effseq, action, reason or "", today(), status,
                  "A" if status in ACTIVE_STATUSES else "I", ts, oprid, *[new[k] for k in JOB_FIELDS]))
    return db.row(conn, "SELECT * FROM PS_JOB WHERE EMPLID=? AND EMPL_RCD=? AND EFFDT=? AND EFFSEQ=?",
                  (emplid, empl_rcd, effdt, effseq))


# --------------------------------------------------------------------------- worker composite
def _email(conn, emplid, typ):
    r = db.row(conn, "SELECT EMAIL_ADDR FROM PS_EMAIL_ADDRESSES WHERE EMPLID=? AND E_ADDR_TYPE=?", (emplid, typ))
    return r["EMAIL_ADDR"] if r else ""


def _phone(conn, emplid, typ):
    r = db.row(conn, "SELECT PHONE FROM PS_PERSON_PHONE WHERE EMPLID=? AND PHONE_TYPE=?", (emplid, typ))
    return r["PHONE"] if r else ""


def get_worker(conn, emplid, asof=None):
    person = db.row(conn, "SELECT * FROM PS_PERSONAL_DATA WHERE EMPLID=?", (emplid,))
    if not person:
        return None
    job = current_job(conn, emplid, asof=asof)
    latest = latest_job(conn, emplid)
    employment = db.row(conn, "SELECT * FROM PS_EMPLOYMENT WHERE EMPLID=? AND EMPL_RCD=0", (emplid,)) or {}
    pre_hire = False
    if job is None and latest is not None:
        # Only future-dated rows exist: a pre-hire. Show the future job with a pre-hire marker.
        job = latest
        pre_hire = latest["ACTION"] in ("HIR", "REH")
    d = dept(conn, job["DEPTID"]) if job else None
    jc = jobcode(conn, job["JOBCODE"]) if job else None
    loc = location(conn, job["LOCATION"]) if job else None
    sup = db.row(conn, "SELECT NAME_DISPLAY FROM PS_PERSONAL_DATA WHERE EMPLID=?", (job["SUPERVISOR_ID"],)) \
        if job and job["SUPERVISOR_ID"] else None
    sup_email = _email(conn, job["SUPERVISOR_ID"], "BUSN") if job and job["SUPERVISOR_ID"] else ""
    status = job["EMPL_STATUS"] if job else "T"
    last_mod = max(filter(None, [person["LAST_UPDATE_DTTM"], job["LASTUPDDTTM"] if job else None,
                                 latest["LASTUPDDTTM"] if latest else None]))
    worker = {
        "emplid": emplid,
        "emplRcd": 0,
        "firstName": person["FIRST_NAME"], "lastName": person["LAST_NAME"], "middleName": person["MIDDLE_NAME"],
        "preferredFirstName": person["PREF_FIRST_NAME"], "displayName": person["NAME_DISPLAY"],
        "birthDate": person["BIRTHDATE"], "sex": person["SEX"], "country": person["COUNTRY"],
        "workEmail": _email(conn, emplid, "BUSN"), "homeEmail": _email(conn, emplid, "HOME"),
        "workPhone": _phone(conn, emplid, "BUSN"), "mobilePhone": _phone(conn, emplid, "MOBL"),
        "emplStatus": status, "emplStatusDescr": STATUS_LABELS.get(status, status),
        "hrStatus": job["HR_STATUS"] if job else "I",
        "preHire": pre_hire,
        "hireDate": employment.get("HIRE_DT"), "originalHireDate": employment.get("ORIG_HIRE_DT"),
        "rehireDate": employment.get("REHIRE_DT"), "terminationDate": employment.get("TERMINATION_DT"),
        "lastDateWorked": employment.get("LAST_DATE_WORKED"),
        "job": None,
        "lastModified": last_mod,
    }
    if job:
        worker["job"] = {
            "effdt": job["EFFDT"], "effseq": job["EFFSEQ"], "action": job["ACTION"],
            "actionDescr": ACTIONS.get(job["ACTION"], job["ACTION"]), "actionReason": job["ACTION_REASON"],
            "actionReasonDescr": REASONS.get(job["ACTION"], {}).get(job["ACTION_REASON"], job["ACTION_REASON"]),
            "deptid": job["DEPTID"], "deptDescr": d["DESCR"] if d else "",
            "jobcode": job["JOBCODE"], "jobTitle": jc["DESCR"] if jc else "", "jobFamily": jc["JOB_FAMILY"] if jc else "",
            "grade": jc["GRADE"] if jc else "", "positionNbr": job["POSITION_NBR"],
            "location": job["LOCATION"], "locationDescr": loc["DESCR"] if loc else "",
            "city": loc["CITY"] if loc else "", "state": loc["STATE"] if loc else "", "locationCountry": loc["COUNTRY"] if loc else "",
            "company": job["COMPANY"], "businessUnit": job["BUSINESS_UNIT"],
            "regTemp": job["REG_TEMP"], "fullPartTime": job["FULL_PART_TIME"],
            "emplClass": job["EMPL_CLASS"], "emplClassDescr": EMPL_CLASS.get(job["EMPL_CLASS"], job["EMPL_CLASS"]),
            "supervisorId": job["SUPERVISOR_ID"], "supervisorName": sup["NAME_DISPLAY"] if sup else "",
            "supervisorEmail": sup_email, "reportsTo": job["REPORTS_TO"],
            "compRate": job["COMPRATE"], "currency": job["CURRENCY_CD"], "compFrequency": job["COMP_FREQUENCY"],
            "stdHours": job["STD_HOURS"], "paygroup": job["PAYGROUP"],
            "lastUpdated": job["LASTUPDDTTM"], "lastUpdatedBy": job["LASTUPDOPRID"],
        }
    return worker


def list_workers(conn, status=None, changed_since=None, q=None, asof=None, deptid=None, limit=500, offset=0,
                 include_inactive=True):
    params = []
    sql = "SELECT EMPLID FROM PS_PERSONAL_DATA WHERE 1=1"
    if q:
        sql += " AND (EMPLID LIKE ? OR NAME_DISPLAY LIKE ? OR FIRST_NAME LIKE ? OR LAST_NAME LIKE ?)"
        params += [f"%{q}%"] * 4
    sql += " ORDER BY EMPLID"
    out = []
    for r in conn.execute(sql, params).fetchall():
        w = get_worker(conn, r["EMPLID"], asof=asof)
        if status and w["emplStatus"] != status:
            continue
        if not include_inactive and w["hrStatus"] != "A":
            continue
        if deptid and (not w["job"] or w["job"]["deptid"] != deptid):
            continue
        if changed_since and w["lastModified"] <= changed_since:
            continue
        out.append(w)
    total = len(out)
    return out[offset:offset + limit], total


# --------------------------------------------------------------------------- events (outbox to Okta)
EVENT_FOR_ACTION = {
    "HIR": "worker.hired", "REH": "worker.rehired", "XFR": "worker.transferred", "PRO": "worker.promoted",
    "DEM": "worker.demoted", "PAY": "worker.pay_changed", "DTA": "worker.updated", "POS": "worker.updated",
    "LOA": "worker.leave_started", "PLA": "worker.leave_started", "RFL": "worker.leave_ended",
    "SUS": "worker.suspended", "TER": "worker.terminated", "RET": "worker.terminated",
}


def enqueue_event(conn, emplid, action, reason, effdt, summary, event_type=None, changes=None):
    worker = get_worker(conn, emplid)
    payload = {
        "eventType": event_type or EVENT_FOR_ACTION.get(action, "worker.updated"),
        "source": "peopleschoft", "emplid": emplid,
        "action": action, "actionDescr": ACTIONS.get(action, action), "actionReason": reason,
        "actionReasonDescr": REASONS.get(action, {}).get(reason, reason),
        "effectiveDate": effdt, "summary": summary, "changes": changes or {},
        "occurredAt": db.now_iso(), "worker": worker,
    }
    conn.execute("""INSERT INTO PS_OKTA_EVENTS (EMPLID, EVENT_TYPE, ACTION, ACTION_REASON, EFFDT, SUMMARY, PAYLOAD, CREATED_DTTM)
                    VALUES (?,?,?,?,?,?,?,?)""",
                 (emplid, payload["eventType"], action, reason, effdt, summary, json.dumps(payload), db.now_iso()))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# --------------------------------------------------------------------------- personal data
def _display_name(first, last, middle=""):
    return f"{first} {last}".strip()


def _touch_person(conn, emplid):
    conn.execute("UPDATE PS_PERSONAL_DATA SET LAST_UPDATE_DTTM=? WHERE EMPLID=?", (db.now_iso(), emplid))


def set_email(conn, emplid, email, typ="BUSN"):
    conn.execute("INSERT INTO PS_EMAIL_ADDRESSES (EMPLID, E_ADDR_TYPE, EMAIL_ADDR, PREF_EMAIL_FLAG) VALUES (?,?,?,?) "
                 "ON CONFLICT(EMPLID, E_ADDR_TYPE) DO UPDATE SET EMAIL_ADDR=excluded.EMAIL_ADDR",
                 (emplid, typ, email, "Y" if typ == "BUSN" else "N"))
    _touch_person(conn, emplid)


def set_phone(conn, emplid, phone, typ="BUSN"):
    if not phone:
        conn.execute("DELETE FROM PS_PERSON_PHONE WHERE EMPLID=? AND PHONE_TYPE=?", (emplid, typ))
    else:
        conn.execute("INSERT INTO PS_PERSON_PHONE (EMPLID, PHONE_TYPE, PHONE, PREF_PHONE_FLAG) VALUES (?,?,?,?) "
                     "ON CONFLICT(EMPLID, PHONE_TYPE) DO UPDATE SET PHONE=excluded.PHONE",
                     (emplid, typ, phone, "Y" if typ == "BUSN" else "N"))
    _touch_person(conn, emplid)


def default_email(conn, first, last):
    base = f"{first}.{last}".lower()
    base = "".join(ch for ch in base if ch.isalnum() or ch in "._-")
    candidate, n = f"{base}@{config.email_domain}", 1
    while db.row(conn, "SELECT 1 FROM PS_EMAIL_ADDRESSES WHERE EMAIL_ADDR=?", (candidate,)):
        n += 1
        candidate = f"{base}{n}@{config.email_domain}"
    return candidate


# --------------------------------------------------------------------------- lifecycle actions
def hire(conn, data, oprid="PS", source="API", emplid=None, sync=True):
    """Joiner. data keys (camelCase or PS names accepted): firstName, lastName, middleName, preferredFirstName,
    deptid, jobcode, location, supervisorId, hireDate/effdt, workEmail, mobilePhone, compRate, emplClass, regTemp,
    fullPartTime, reason, birthDate, nationalId."""
    g = _Getter(data)
    first, last = g("firstName", "FIRST_NAME"), g("lastName", "LAST_NAME")
    if not first or not last:
        raise HRError("firstName and lastName are required")
    effdt = _valid_date(g("hireDate", "effdt", "HIRE_DT", "EFFDT"), "hireDate")
    emplid = emplid or f"{db.next_val(conn, 'EMPLID'):06d}"
    if db.row(conn, "SELECT 1 FROM PS_PERSONAL_DATA WHERE EMPLID=?", (emplid,)):
        raise HRError(f"EMPLID {emplid} already exists")
    ts = db.now_iso()
    conn.execute("""INSERT INTO PS_PERSONAL_DATA (EMPLID, FIRST_NAME, LAST_NAME, MIDDLE_NAME, PREF_FIRST_NAME, NAME_DISPLAY,
                    BIRTHDATE, SEX, COUNTRY, LAST_UPDATE_DTTM) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                 (emplid, first, last, g("middleName", "MIDDLE_NAME") or "", g("preferredFirstName", "PREF_FIRST_NAME") or "",
                  _display_name(first, last), g("birthDate", "BIRTHDATE"), g("sex", "SEX") or "U",
                  g("country", "COUNTRY") or "USA", ts))
    set_email(conn, emplid, g("workEmail", "email", "EMAIL_ADDR") or default_email(conn, first, last), "BUSN")
    if g("homeEmail"):
        set_email(conn, emplid, g("homeEmail"), "HOME")
    if g("mobilePhone"):
        set_phone(conn, emplid, g("mobilePhone"), "MOBL")
    if g("workPhone"):
        set_phone(conn, emplid, g("workPhone"), "BUSN")
    if g("nationalId"):
        conn.execute("INSERT INTO PS_PERS_NID (EMPLID, COUNTRY, NATIONAL_ID_TYPE, NATIONAL_ID) VALUES (?,?,?,?)",
                     (emplid, g("country") or "USA", "PR", g("nationalId")))
    conn.execute("INSERT INTO PS_EMPLOYMENT (EMPLID, EMPL_RCD, HIRE_DT, ORIG_HIRE_DT) VALUES (?,0,?,?)", (emplid, effdt, effdt))
    overrides = {
        "DEPTID": g("deptid", "DEPTID"), "JOBCODE": g("jobcode", "JOBCODE"), "LOCATION": g("location", "LOCATION"),
        "SUPERVISOR_ID": g("supervisorId", "SUPERVISOR_ID"), "COMPRATE": g("compRate", "COMPRATE"),
        "EMPL_CLASS": g("emplClass", "EMPL_CLASS"), "REG_TEMP": g("regTemp", "REG_TEMP"),
        "FULL_PART_TIME": g("fullPartTime", "FULL_PART_TIME"), "POSITION_NBR": g("positionNbr", "POSITION_NBR"),
        "BUSINESS_UNIT": g("businessUnit", "BUSINESS_UNIT"), "COMPANY": g("company", "COMPANY"),
    }
    if not overrides["DEPTID"] or not overrides["JOBCODE"]:
        raise HRError("deptid and jobcode are required")
    if not overrides["LOCATION"]:
        overrides["LOCATION"] = (dept(conn, overrides["DEPTID"]) or {}).get("LOCATION")
    insert_job_row(conn, emplid, effdt, "HIR", g("reason", "ACTION_REASON") or "NEW", overrides, oprid)
    db.audit(conn, emplid, "HIR", f"Hired {first} {last} into {overrides['DEPTID']}/{overrides['JOBCODE']} eff {effdt}", oprid, source)
    if sync:
        enqueue_event(conn, emplid, "HIR", g("reason") or "NEW", effdt, f"Hired {first} {last}")
        if effdt > today():
            enqueue_event(conn, emplid, "HIR", g("reason") or "NEW", effdt, f"Start date reached for {first} {last}",
                          event_type="worker.started")
    conn.commit()
    return get_worker(conn, emplid)


def _worker_or_404(conn, emplid):
    w = get_worker(conn, emplid)
    if not w:
        raise HRError(f"EMPLID {emplid} not found")
    latest = latest_job(conn, emplid)
    if latest:
        # Validate against the latest row so a future-dated termination/hire is respected.
        w["emplStatus"] = latest["EMPL_STATUS"]
        w["emplStatusDescr"] = STATUS_LABELS.get(latest["EMPL_STATUS"], latest["EMPL_STATUS"])
        if latest["EFFDT"] > today():
            w["emplStatusDescr"] += f" (effective {latest['EFFDT']})"
    return w


def _job_action(conn, emplid, action, reason, effdt, overrides, summary, oprid, source, changes=None, sync=True):
    row = insert_job_row(conn, emplid, effdt, action, reason, overrides, oprid)
    db.audit(conn, emplid, action, summary, oprid, source)
    if sync:
        enqueue_event(conn, emplid, action, reason, row["EFFDT"], summary, changes=changes or overrides)
    conn.commit()
    return get_worker(conn, emplid)


def transfer(conn, emplid, effdt=None, deptid=None, location=None, supervisor_id=None, reason="DEP",
             jobcode=None, oprid="PS", source="API", sync=True):
    """Mover: department / location / manager change (XFR)."""
    w = _worker_or_404(conn, emplid)
    if w["emplStatus"] not in ACTIVE_STATUSES:
        raise HRError(f"{emplid} is {w['emplStatusDescr']}; transfer requires an active employee")
    overrides = {"DEPTID": deptid, "LOCATION": location, "SUPERVISOR_ID": supervisor_id, "JOBCODE": jobcode}
    if not any(overrides.values()):
        raise HRError("transfer requires at least one of deptid, location, supervisorId, jobcode")
    if deptid and not location and not supervisor_id:
        overrides["SUPERVISOR_ID"] = (dept(conn, deptid) or {}).get("MANAGER_ID") or None
    parts = [f"{k}={v}" for k, v in overrides.items() if v]
    return _job_action(conn, emplid, "XFR", reason, effdt, overrides, f"Transfer: {', '.join(parts)}", oprid, source, sync=sync)


def promote(conn, emplid, jobcode, effdt=None, comp_rate=None, reason="MER", deptid=None, supervisor_id=None,
            action="PRO", oprid="PS", source="API", sync=True):
    w = _worker_or_404(conn, emplid)
    if w["emplStatus"] not in ACTIVE_STATUSES:
        raise HRError(f"{emplid} is {w['emplStatusDescr']}; promotion requires an active employee")
    if not jobcode:
        raise HRError("jobcode is required")
    overrides = {"JOBCODE": jobcode, "COMPRATE": comp_rate, "DEPTID": deptid, "SUPERVISOR_ID": supervisor_id}
    jc = jobcode_or_err(conn, jobcode)
    return _job_action(conn, emplid, action, reason, effdt, overrides,
                       f"{ACTIONS[action]} to {jc['DESCR']} ({jobcode})", oprid, source, sync=sync)


def jobcode_or_err(conn, code):
    jc = jobcode(conn, code)
    if not jc:
        raise HRError(f"Unknown JOBCODE: {code!r}")
    return jc


def pay_change(conn, emplid, comp_rate, effdt=None, reason="MER", oprid="PS", source="API", sync=True):
    _worker_or_404(conn, emplid)
    return _job_action(conn, emplid, "PAY", reason, effdt, {"COMPRATE": comp_rate},
                       f"Pay rate change to {comp_rate}", oprid, source, sync=sync)


def change_manager(conn, emplid, supervisor_id, effdt=None, oprid="PS", source="API", sync=True):
    _worker_or_404(conn, emplid)
    _worker_or_404(conn, supervisor_id)
    return _job_action(conn, emplid, "DTA", "MGR", effdt, {"SUPERVISOR_ID": supervisor_id},
                       f"Supervisor changed to {supervisor_id}", oprid, source, sync=sync)


def leave_of_absence(conn, emplid, effdt=None, reason="MED", paid=False, oprid="PS", source="API", sync=True):
    w = _worker_or_404(conn, emplid)
    if w["emplStatus"] != "A":
        raise HRError(f"{emplid} is {w['emplStatusDescr']}; leave requires an Active employee")
    action = "PLA" if paid else "LOA"
    return _job_action(conn, emplid, action, reason, effdt, {}, f"{ACTIONS[action]} ({REASONS[action].get(reason, reason)})",
                       oprid, source, sync=sync)


def return_from_leave(conn, emplid, effdt=None, oprid="PS", source="API", sync=True):
    w = _worker_or_404(conn, emplid)
    if w["emplStatus"] not in ("L", "P", "S"):
        raise HRError(f"{emplid} is {w['emplStatusDescr']}; not on leave")
    return _job_action(conn, emplid, "RFL", "RFL", effdt, {}, "Returned from leave", oprid, source, sync=sync)


def terminate(conn, emplid, effdt=None, reason="RES", last_date_worked=None, retire=False, oprid="PS", source="API", sync=True):
    """Leaver. In PeopleSoft the termination EFFDT is the first day the person is no longer employed."""
    w = _worker_or_404(conn, emplid)
    if w["emplStatus"] in ("T", "R", "D"):
        raise HRError(f"{emplid} is already {w['emplStatusDescr']}")
    effdt = _valid_date(effdt)
    action = "RET" if retire else "TER"
    ldw = _valid_date(last_date_worked) if last_date_worked else (date.fromisoformat(effdt) - timedelta(days=1)).isoformat()
    conn.execute("UPDATE PS_EMPLOYMENT SET TERMINATION_DT=?, LAST_DATE_WORKED=? WHERE EMPLID=? AND EMPL_RCD=0", (effdt, ldw, emplid))
    if sync and effdt > today():
        enqueue_event(conn, emplid, action, reason, today(), f"Termination scheduled for {effdt}",
                      event_type="worker.termination_scheduled", changes={"terminationDate": effdt, "lastDateWorked": ldw})
    return _job_action(conn, emplid, action, reason, effdt, {}, f"{ACTIONS[action]} ({REASONS[action].get(reason, reason)}) eff {effdt}",
                       oprid, source, changes={"terminationDate": effdt, "lastDateWorked": ldw}, sync=sync)


def rehire(conn, emplid, effdt=None, deptid=None, jobcode=None, location=None, supervisor_id=None, comp_rate=None,
           reason="REH", oprid="PS", source="API", sync=True):
    w = _worker_or_404(conn, emplid)
    if w["emplStatus"] not in ("T", "R"):
        raise HRError(f"{emplid} is {w['emplStatusDescr']}; rehire requires a Terminated or Retired employee")
    effdt = _valid_date(effdt)
    conn.execute("UPDATE PS_EMPLOYMENT SET REHIRE_DT=?, HIRE_DT=?, TERMINATION_DT=NULL, LAST_DATE_WORKED=NULL WHERE EMPLID=? AND EMPL_RCD=0",
                 (effdt, effdt, emplid))
    overrides = {"DEPTID": deptid, "JOBCODE": jobcode, "LOCATION": location, "SUPERVISOR_ID": supervisor_id, "COMPRATE": comp_rate}
    w = _job_action(conn, emplid, "REH", reason, effdt, overrides, f"Rehired eff {effdt}", oprid, source, sync=sync)
    if sync and effdt > today():
        enqueue_event(conn, emplid, "REH", reason, effdt, "Rehire start date reached", event_type="worker.started")
        conn.commit()
    return w


def update_personal(conn, emplid, data, oprid="PS", source="API", sync=True):
    """Name / email / phone changes (DTA)."""
    g = _Getter(data)
    p = db.row(conn, "SELECT * FROM PS_PERSONAL_DATA WHERE EMPLID=?", (emplid,))
    if not p:
        raise HRError(f"EMPLID {emplid} not found")
    changes = {}
    first = g("firstName") or p["FIRST_NAME"]
    last = g("lastName") or p["LAST_NAME"]
    middle = g("middleName") if g("middleName") is not None else p["MIDDLE_NAME"]
    pref = g("preferredFirstName") if g("preferredFirstName") is not None else p["PREF_FIRST_NAME"]
    for k, old, new in (("firstName", p["FIRST_NAME"], first), ("lastName", p["LAST_NAME"], last),
                        ("middleName", p["MIDDLE_NAME"], middle), ("preferredFirstName", p["PREF_FIRST_NAME"], pref)):
        if old != new:
            changes[k] = {"old": old, "new": new}
    conn.execute("UPDATE PS_PERSONAL_DATA SET FIRST_NAME=?, LAST_NAME=?, MIDDLE_NAME=?, PREF_FIRST_NAME=?, NAME_DISPLAY=?, LAST_UPDATE_DTTM=? WHERE EMPLID=?",
                 (first, last, middle, pref, _display_name(first, last), db.now_iso(), emplid))
    for key, typ, fn in (("workEmail", "BUSN", set_email), ("homeEmail", "HOME", set_email),
                         ("mobilePhone", "MOBL", set_phone), ("workPhone", "BUSN", set_phone)):
        val = g(key)
        if val is not None:
            old = _email(conn, emplid, typ) if fn is set_email else _phone(conn, emplid, typ)
            if old != val:
                changes[key] = {"old": old, "new": val}
                fn(conn, emplid, val, typ)
    if not changes:
        conn.commit()
        return get_worker(conn, emplid)
    reason = "NAM" if any(k in changes for k in ("firstName", "lastName")) else ("EML" if "workEmail" in changes else "COR")
    summary = "Personal data change: " + ", ".join(changes)
    db.audit(conn, emplid, "DTA", summary, oprid, source)
    if sync:
        enqueue_event(conn, emplid, "DTA", reason, today(), summary, changes=changes)
    conn.commit()
    return get_worker(conn, emplid)


def generic_action(conn, emplid, data, oprid="PS", source="API"):
    """POST /workers/{id}/actions with {"action": "XFR", ...} routes to the matching lifecycle function."""
    g = _Getter(data)
    action = (g("action", "ACTION") or "").upper()
    effdt = g("effdt", "effectiveDate", "EFFDT")
    reason = g("reason", "actionReason", "ACTION_REASON")
    if action == "XFR":
        return transfer(conn, emplid, effdt, g("deptid"), g("location"), g("supervisorId"), reason or "DEP", g("jobcode"), oprid, source)
    if action in ("PRO", "DEM"):
        return promote(conn, emplid, g("jobcode"), effdt, g("compRate"), reason or "MER", g("deptid"), g("supervisorId"), action, oprid, source)
    if action == "PAY":
        return pay_change(conn, emplid, g("compRate"), effdt, reason or "MER", oprid, source)
    if action == "DTA":
        if g("supervisorId"):
            return change_manager(conn, emplid, g("supervisorId"), effdt, oprid, source)
        return update_personal(conn, emplid, data, oprid, source)
    if action in ("LOA", "PLA"):
        return leave_of_absence(conn, emplid, effdt, reason or "MED", action == "PLA", oprid, source)
    if action == "RFL":
        return return_from_leave(conn, emplid, effdt, oprid, source)
    if action in ("TER", "RET"):
        return terminate(conn, emplid, effdt, reason or ("RET" if action == "RET" else "RES"), g("lastDateWorked"), action == "RET", oprid, source)
    if action == "REH":
        return rehire(conn, emplid, effdt, g("deptid"), g("jobcode"), g("location"), g("supervisorId"), g("compRate"), reason or "REH", oprid, source)
    if action == "SUS":
        w = _worker_or_404(conn, emplid)
        if w["emplStatus"] != "A":
            raise HRError("suspension requires an Active employee")
        return _job_action(conn, emplid, "SUS", reason or "DIS", effdt, {}, "Suspended", oprid, source)
    raise HRError(f"Unsupported action {action!r}. Supported: XFR, PRO, DEM, PAY, DTA, LOA, PLA, RFL, SUS, TER, RET, REH")


class _Getter:
    """Case-tolerant accessor over a dict with several alias keys."""

    def __init__(self, data):
        self.data = data or {}
        self.lower = {str(k).lower(): v for k, v in self.data.items()}

    def __call__(self, *keys):
        for k in keys:
            if k in self.data and self.data[k] not in (None, ""):
                return self.data[k]
            v = self.lower.get(k.lower())
            if v not in (None, ""):
                return v
        return None


# --------------------------------------------------------------------------- seeding
def seed(conn):
    from . import seed_data as sd
    conn.executemany("INSERT OR REPLACE INTO PS_COMPANY_TBL (COMPANY, DESCR) VALUES (?,?)", sd.COMPANIES)
    conn.executemany("INSERT OR REPLACE INTO PS_LOCATION_TBL (LOCATION, DESCR, CITY, STATE, COUNTRY) VALUES (?,?,?,?,?)", sd.LOCATIONS)
    conn.executemany("INSERT OR REPLACE INTO PS_DEPT_TBL (DEPTID, DESCR, LOCATION, COMPANY) VALUES (?,?,?,'GBI')", sd.DEPARTMENTS)
    conn.executemany("INSERT OR REPLACE INTO PS_JOBCODE_TBL (JOBCODE, DESCR, DESCRSHORT, GRADE, JOB_FAMILY, MANAGER_LEVEL) VALUES (?,?,?,?,?,?)", sd.JOBCODES)
    conn.execute("INSERT OR REPLACE INTO PS_SEQUENCES (NAME, NEXT_VAL) VALUES ('EMPLID', 100032)")
    for (emplid, first, last, middle, pref, sex, deptid, jc, loc, sup, hire_dt, status, cls, reg, comp) in sd.EMPLOYEES:
        hire(conn, {"firstName": first, "lastName": last, "middleName": middle, "preferredFirstName": pref, "sex": sex,
                    "deptid": deptid, "jobcode": jc, "location": loc, "supervisorId": sup, "hireDate": hire_dt,
                    "compRate": comp, "emplClass": cls, "regTemp": reg,
                    "mobilePhone": f"+1 415 555 {int(emplid[-4:]) % 10000:04d}"},
             oprid="SEED", source="SEED", emplid=emplid, sync=False)
    for (emplid, effdt, action, reason, ov) in sd.SCENARIOS:
        if action == "TER":
            terminate(conn, emplid, effdt, reason, oprid="SEED", source="SEED", sync=False)
        elif action == "LOA":
            leave_of_absence(conn, emplid, effdt, reason, oprid="SEED", source="SEED", sync=False)
        else:
            insert_job_row(conn, emplid, effdt, action, reason, ov, oprid="SEED")
    # Department managers
    mgrs = {"10000": "100001", "11000": "100003", "12000": "100002", "13000": "100009", "13100": "100014",
            "14000": "100018", "15000": "100021", "16000": "100023", "17000": "100027", "18000": "100030"}
    for d, m in mgrs.items():
        conn.execute("UPDATE PS_DEPT_TBL SET MANAGER_ID=? WHERE DEPTID=?", (m, d))
    # A future-dated hire so the pre-hire flow is visible on day one.
    start = (date.today() + timedelta(days=10)).isoformat()
    hire(conn, {"firstName": "Nadia", "lastName": "Okonkwo", "deptid": "16000", "jobcode": "IAMENG", "location": "AUS01",
                "supervisorId": "100023", "hireDate": start, "compRate": 155000, "reason": "NEW"},
         oprid="SEED", source="SEED", emplid="100032", sync=False)
    conn.execute("INSERT OR REPLACE INTO PS_SEQUENCES (NAME, NEXT_VAL) VALUES ('EMPLID', 100033)")
    # Seeded user profiles (PSOPRDEFN) for a few people, as if Okta had already pushed them via SCIM.
    for emplid in ("100001", "100024", "100025"):
        w = get_worker(conn, emplid)
        conn.execute("""INSERT OR REPLACE INTO PSOPRDEFN (OPRID, SCIM_ID, EMPLID, OPRDEFNDESC, EMAILID, FIRST_NAME, LAST_NAME,
                        ACCTLOCK, EXTERNAL_ID, RAW_JSON, CREATED_DTTM, LASTUPDDTTM) VALUES (?,?,?,?,?,?,?,0,?,?,?,?)""",
                     (w["workEmail"], f"seed-{emplid}", emplid, w["displayName"], w["workEmail"], w["firstName"], w["lastName"],
                      f"okta-seed-{emplid}", "{}", db.now_iso(), db.now_iso()))
        conn.executemany("INSERT OR REPLACE INTO PSROLEUSER VALUES (?,?)", [(w["workEmail"], "PeopleSoft User"), (w["workEmail"], "Employee")])
    conn.commit()
