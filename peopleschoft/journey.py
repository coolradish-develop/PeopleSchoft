"""Guided lifecycle journey: joiner -> mover -> leaver -> rehire for one new demo employee."""
import random
from datetime import date, timedelta

from . import db, hr

FIRST = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Avery", "Quinn", "Sam", "Jamie"]
LAST = ["Rivera", "Kowalski", "Haddad", "Ivanova", "Mbeki", "Sato", "Larsen", "Costa", "Byrne", "Novak"]


def run_journey(conn, oprid="DEMO", source="JOURNEY", start_date=None):
    """Runs every lifecycle stage and returns the list of steps with the resulting worker state."""
    rnd = random.Random()
    first, last = rnd.choice(FIRST), rnd.choice(LAST)
    d0 = date.fromisoformat(start_date) if start_date else date.today() - timedelta(days=400)
    steps = []

    def step(stage, action, descr, worker):
        steps.append({"stage": stage, "action": action, "description": descr, "emplid": worker["emplid"],
                      "emplStatus": worker["emplStatus"], "emplStatusDescr": worker["emplStatusDescr"],
                      "deptid": worker["job"]["deptid"], "deptDescr": worker["job"]["deptDescr"],
                      "jobTitle": worker["job"]["jobTitle"], "location": worker["job"]["location"],
                      "supervisorId": worker["job"]["supervisorId"], "effdt": worker["job"]["effdt"]})

    w = hr.hire(conn, {"firstName": first, "lastName": last, "deptid": "13000", "jobcode": "SWE1", "location": "SFHQ",
                       "supervisorId": "100010", "hireDate": d0.isoformat(), "compRate": 115000, "reason": "NEW",
                       "mobilePhone": f"+1 415 555 {rnd.randint(1000, 9999)}"}, oprid, source)
    step("Joiner", "HIR", f"Hired {first} {last} as Software Engineer I in Engineering (SFHQ), reports to Marcus Johnson", w)
    emplid = w["emplid"]
    w = hr.promote(conn, emplid, "SWE2", (d0 + timedelta(days=200)).isoformat(), 140000, "MER", oprid=oprid, source=source)
    step("Mover", "PRO", "Promoted to Software Engineer II with merit increase", w)
    w = hr.transfer(conn, emplid, (d0 + timedelta(days=260)).isoformat(), deptid="13100", location="AUS01",
                    supervisor_id="100014", reason="DEP", oprid=oprid, source=source)
    step("Mover", "XFR", "Transferred to Platform Engineering (Austin), new manager Wei Zhang", w)
    w = hr.update_personal(conn, emplid, {"lastName": f"{last}-Lee", "preferredFirstName": first[:3]}, oprid, source)
    step("Mover", "DTA", f"Name change: last name now {last}-Lee, preferred name {first[:3]}", w)
    w = hr.leave_of_absence(conn, emplid, (d0 + timedelta(days=300)).isoformat(), "PAR", oprid=oprid, source=source)
    step("Leaver (temporary)", "LOA", "Parental leave of absence -> Okta user suspended", w)
    w = hr.return_from_leave(conn, emplid, (d0 + timedelta(days=345)).isoformat(), oprid=oprid, source=source)
    step("Mover", "RFL", "Returned from leave -> Okta user unsuspended", w)
    w = hr.terminate(conn, emplid, (d0 + timedelta(days=370)).isoformat(), "RES", oprid=oprid, source=source)
    step("Leaver", "TER", "Resigned -> Okta user deactivated", w)
    w = hr.rehire(conn, emplid, (d0 + timedelta(days=395)).isoformat(), deptid="16000", jobcode="IAMENG", location="AUS01",
                  supervisor_id="100023", comp_rate=150000, oprid=oprid, source=source)
    step("Joiner (rehire)", "REH", "Rehired into IT & Security as Identity & Access Engineer -> Okta user reactivated", w)
    db.audit(conn, emplid, "JOURNEY", "Guided lifecycle journey completed", oprid, source)
    conn.commit()
    return {"emplid": emplid, "name": f"{first} {last}-Lee", "steps": steps}
