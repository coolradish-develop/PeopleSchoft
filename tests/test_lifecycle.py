"""Stdlib unit tests: python3 -m unittest -v"""
import base64
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="peopleschoft-test-")
os.environ["PS_DB_PATH"] = str(Path(TMP) / "test.db")
os.environ["OKTA_MODE"] = "dryrun"
os.environ["OKTA_SYNC_INTERVAL"] = "0"

from peopleschoft import db, hr, okta, scim  # noqa: E402
from peopleschoft.journey import run_journey  # noqa: E402
from peopleschoft.server import Handler  # noqa: E402

TODAY = date.today().isoformat()


def fresh_conn():
    conn = db.connect()
    db.reset_db(conn)
    hr.seed(conn)
    return conn


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()

    def tearDown(self):
        self.conn.close()

    def test_seed_counts_and_scenarios(self):
        workers, total = hr.list_workers(self.conn)
        self.assertEqual(total, 32)
        self.assertEqual(hr.get_worker(self.conn, "100026")["emplStatus"], "T")
        self.assertEqual(hr.get_worker(self.conn, "100020")["emplStatus"], "L")
        pre = hr.get_worker(self.conn, "100032")
        self.assertTrue(pre["preHire"])
        self.assertGreater(pre["hireDate"], TODAY)

    def test_effective_dating_as_of(self):
        self.assertEqual(hr.get_worker(self.conn, "100026", asof="2024-01-01")["emplStatus"], "A")
        self.assertEqual(hr.get_worker(self.conn, "100011", asof="2020-01-01")["job"]["action"], "HIR")
        self.assertEqual(hr.get_worker(self.conn, "100011")["job"]["action"], "PRO")


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        self.w = hr.hire(self.conn, {"firstName": "Ada", "lastName": "Lovelace", "deptid": "13000", "jobcode": "SWE2",
                                     "supervisorId": "100010", "hireDate": "2026-01-05"})
        self.id = self.w["emplid"]

    def test_hire_defaults(self):
        self.assertEqual(self.w["workEmail"], "ada.lovelace@gbi.example.com")
        self.assertEqual(self.w["job"]["location"], "SFHQ")  # from department
        self.assertEqual(self.w["emplStatus"], "A")
        self.assertEqual(self.w["job"]["action"], "HIR")

    def test_full_journey_transitions(self):
        w = hr.transfer(self.conn, self.id, "2026-02-01", deptid="13100", location="AUS01", supervisor_id="100014")
        self.assertEqual((w["job"]["deptid"], w["job"]["location"], w["job"]["supervisorId"]), ("13100", "AUS01", "100014"))
        w = hr.promote(self.conn, self.id, "SWE3", "2026-03-01", 170000)
        self.assertEqual(w["job"]["jobTitle"], "Senior Software Engineer")
        self.assertEqual(w["job"]["deptid"], "13100")  # carried forward
        w = hr.leave_of_absence(self.conn, self.id, "2026-04-01", "PAR")
        self.assertEqual(w["emplStatus"], "L")
        self.assertEqual(w["hrStatus"], "A")
        w = hr.return_from_leave(self.conn, self.id, "2026-05-01")
        self.assertEqual(w["emplStatus"], "A")
        w = hr.terminate(self.conn, self.id, "2026-06-01", "RES")
        self.assertEqual((w["emplStatus"], w["hrStatus"], w["terminationDate"], w["lastDateWorked"]), ("T", "I", "2026-06-01", "2026-05-31"))
        w = hr.rehire(self.conn, self.id, "2026-07-01", deptid="16000", jobcode="IAMENG")
        self.assertEqual((w["emplStatus"], w["rehireDate"], w["terminationDate"]), ("A", "2026-07-01", None))
        self.assertEqual(len(hr.job_history(self.conn, self.id)), 7)
        types = [r["EVENT_TYPE"] for r in db.rows(self.conn, "SELECT EVENT_TYPE FROM PS_OKTA_EVENTS WHERE EMPLID=? ORDER BY EVENT_ID", (self.id,))]
        self.assertEqual(types, ["worker.hired", "worker.transferred", "worker.promoted", "worker.leave_started",
                                 "worker.leave_ended", "worker.terminated", "worker.rehired"])

    def test_business_rules(self):
        with self.assertRaises(hr.HRError):
            hr.return_from_leave(self.conn, self.id)           # not on leave
        with self.assertRaises(hr.HRError):
            hr.rehire(self.conn, self.id)                      # still active
        with self.assertRaises(hr.HRError):
            hr.transfer(self.conn, self.id, supervisor_id=self.id)
        with self.assertRaises(hr.HRError):
            hr.transfer(self.conn, self.id, "2025-12-01", deptid="13100")   # before latest row
        with self.assertRaises(hr.HRError):
            hr.transfer(self.conn, self.id, deptid="99999")
        hr.terminate(self.conn, self.id, "2026-06-01")
        with self.assertRaises(hr.HRError):
            hr.terminate(self.conn, self.id, "2026-06-02")
        with self.assertRaises(hr.HRError):
            hr.promote(self.conn, self.id, "SWE3", "2026-06-02")

    def test_future_dated_termination_respected(self):
        future = (date.today() + timedelta(days=6)).isoformat()
        w = hr.terminate(self.conn, self.id, future)
        self.assertEqual(w["emplStatus"], "A")   # still active today
        with self.assertRaises(hr.HRError):
            hr.terminate(self.conn, self.id, future)  # latest row is already TER
        ev = db.rows(self.conn, "SELECT EVENT_TYPE, EFFDT FROM PS_OKTA_EVENTS WHERE EMPLID=? ORDER BY EVENT_ID", (self.id,))
        self.assertEqual([e["EVENT_TYPE"] for e in ev], ["worker.hired", "worker.termination_scheduled", "worker.terminated"])
        okta.sync_pending(self.conn)
        st = {r["EVENT_TYPE"]: r["STATUS"] for r in db.rows(self.conn, "SELECT EVENT_TYPE, STATUS FROM PS_OKTA_EVENTS WHERE EMPLID=?", (self.id,))}
        self.assertEqual(st["worker.terminated"], "SCHEDULED")
        self.assertEqual(st["worker.termination_scheduled"], "DRYRUN")

    def test_personal_data_change(self):
        w = hr.update_personal(self.conn, self.id, {"lastName": "King", "workEmail": "ada.king@gbi.example.com"})
        self.assertEqual((w["displayName"], w["workEmail"]), ("Ada King", "ada.king@gbi.example.com"))
        ev = db.row(self.conn, "SELECT ACTION_REASON, PAYLOAD FROM PS_OKTA_EVENTS WHERE EMPLID=? ORDER BY EVENT_ID DESC LIMIT 1", (self.id,))
        self.assertEqual(ev["ACTION_REASON"], "NAM")
        self.assertIn("lastName", json.loads(ev["PAYLOAD"])["changes"])

    def test_changed_since(self):
        _, n = hr.list_workers(self.conn, changed_since="2099-01-01T00:00:00Z")
        self.assertEqual(n, 0)
        _, n = hr.list_workers(self.conn, changed_since="2000-01-01T00:00:00Z")
        self.assertEqual(n, 33)

    def test_generic_action_router(self):
        w = hr.generic_action(self.conn, self.id, {"action": "xfr", "deptid": "14000", "effdt": "2026-02-01"})
        self.assertEqual(w["job"]["deptid"], "14000")
        self.assertEqual(w["job"]["supervisorId"], "100018")  # dept manager default
        with self.assertRaises(hr.HRError):
            hr.generic_action(self.conn, self.id, {"action": "NOPE"})


class OktaMappingTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        self.client = okta.OktaClient()

    def test_profile_and_status(self):
        w = hr.get_worker(self.conn, "100011")
        p = self.client.profile_from_worker(w)
        self.assertEqual(p["login"], "hannah.schmidt@gbi.example.com")
        self.assertEqual(p["employeeNumber"], "100011")
        self.assertEqual(p["managerId"], "100010")
        self.assertEqual(p["title"], "Senior Software Engineer")
        self.assertNotIn("hireDate", p)
        self.assertIn("hireDate", self.client.profile_from_worker(w, include_custom=True))
        self.assertEqual(self.client.desired_status(w), "ACTIVE")
        self.assertEqual(self.client.desired_status(hr.get_worker(self.conn, "100020")), "SUSPENDED")
        self.assertEqual(self.client.desired_status(hr.get_worker(self.conn, "100026")), "DEPROVISIONED")
        self.assertEqual(self.client.desired_status(hr.get_worker(self.conn, "100032")), "STAGED")

    def test_users_api_plan(self):
        w = hr.get_worker(self.conn, "100020")
        notes = [s["note"] for s in self.client.plan_users_api(w, existing={"id": "00u1", "status": "ACTIVE"})]
        self.assertIn("On leave -> suspend", notes)
        w = hr.get_worker(self.conn, "100026")
        notes = [s["note"] for s in self.client.plan_users_api(w, existing={"id": "00u1", "status": "ACTIVE"})]
        self.assertIn("Terminated -> deactivate", notes)
        notes = [s["note"] for s in self.client.plan_users_api(w, existing=None)]
        self.assertIn("No Okta user exists; nothing to deactivate", notes)
        w = hr.get_worker(self.conn, "100032")
        self.assertIn("Create user as STAGED (pre-hire)", [s["note"] for s in self.client.plan_users_api(w)])

    def test_journey_dryrun_sync(self):
        r = run_journey(self.conn)
        self.assertEqual(len(r["steps"]), 8)
        s = okta.sync_pending(self.conn)
        self.assertEqual((s["processed"], s["dryrun"], s["failed"]), (8, 8, 0))
        ev = db.rows(self.conn, "SELECT REQUEST_PREVIEW FROM PS_OKTA_EVENTS WHERE EMPLID=? ORDER BY EVENT_ID", (r["emplid"],))
        plans = [json.loads(e["REQUEST_PREVIEW"])["usersApi"] for e in ev]
        self.assertTrue(any("suspend" in s["url"] for s in plans[4]))
        self.assertTrue(any("deactivate" in s["url"] for s in plans[6]))

    def test_identity_source_plan(self):
        ws = [hr.get_worker(self.conn, "100011"), hr.get_worker(self.conn, "100026")]
        steps = self.client.plan_identity_source(ws)
        self.assertEqual([s["note"] for s in steps], ["Create import session", "Upsert joiners/movers", "Delete leavers", "Trigger import"])
        self.assertEqual(steps[1]["body"]["profiles"][0]["profile"]["userName"], "hannah.schmidt@gbi.example.com")
        self.assertEqual(steps[2]["body"]["profiles"][0]["externalId"], "100026")


class ScimTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        self.base = "http://test"

    def test_crud_and_linking(self):
        body = {"userName": "hannah.schmidt@gbi.example.com", "name": {"givenName": "Hannah", "familyName": "Schmidt"},
                "emails": [{"value": "hannah.schmidt@gbi.example.com", "primary": True}], "externalId": "00u1", "active": True}
        u = scim.create_user(self.conn, body, self.base)
        self.assertEqual(u[scim.ENT]["employeeNumber"], "100011")  # linked by email
        self.assertEqual(u["active"], True)
        u = scim.patch_user(self.conn, u["id"], {"Operations": [{"op": "replace", "value": {"active": False}}]}, self.base)
        self.assertFalse(u["active"])
        self.assertEqual(db.row(self.conn, "SELECT ACCTLOCK FROM PSOPRDEFN WHERE SCIM_ID=?", (u["id"],))["ACCTLOCK"], 1)
        u = scim.patch_user(self.conn, u["id"], {"Operations": [{"op": "replace", "path": "name.familyName", "value": "Berg"}]}, self.base)
        self.assertEqual(u["name"]["familyName"], "Berg")
        lst = scim.list_users(self.conn, self.base, 'userName eq "HANNAH.schmidt@gbi.example.com"')
        self.assertEqual(lst["totalResults"], 1)
        with self.assertRaises(scim.ScimError) as cm:
            scim.create_user(self.conn, body, self.base)
        self.assertEqual(cm.exception.status, 409)
        scim.delete_user(self.conn, u["id"])
        with self.assertRaises(scim.ScimError):
            scim.get_by_id(self.conn, u["id"]) or scim._by_id_or_404(self.conn, u["id"])


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fresh_conn().close()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.server_close()

    def call(self, method, path, body=None, auth="basic"):
        headers = {"Content-Type": "application/json"}
        if auth == "basic":
            headers["Authorization"] = "Basic " + base64.b64encode(b"PS:PS").decode()
        elif auth == "scim":
            headers["Authorization"] = "Bearer peopleschoft-scim-token"
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw and r.headers.get("Content-Type", "").find("json") >= 0 else raw
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, json.loads(raw) if raw else None

    def test_auth_and_endpoints(self):
        self.assertEqual(self.call("GET", "/api/v1/workers", auth=None)[0], 401)
        self.assertEqual(self.call("GET", "/api/v1/health", auth=None)[0], 200)
        st, body = self.call("GET", "/api/v1/workers?status=L")
        self.assertEqual((st, body["count"]), (200, 1))
        st, body = self.call("GET", "/PSIGW/RESTListeningConnector/PSFT_HR/WORKER.v1/100001")
        self.assertEqual((st, body["displayName"]), (200, "Margaret Chen"))
        st, body = self.call("POST", "/api/v1/workers", {"firstName": "Grace", "lastName": "Hopper", "deptid": "16000", "jobcode": "SECENG"})
        self.assertEqual(st, 201)
        emplid = body["emplid"]
        st, body = self.call("POST", f"/api/v1/workers/{emplid}/terminate", {"reason": "RES", "effdt": TODAY})
        self.assertEqual((st, body["emplStatus"]), (200, "T"))
        st, body = self.call("POST", f"/api/v1/workers/{emplid}/terminate", {"reason": "RES", "effdt": TODAY})
        self.assertEqual(st, 400)
        self.assertIn("already", body["error"])
        st, body = self.call("POST", "/api/v1/okta/sync")
        self.assertEqual((st, body["mode"]), (200, "dryrun"))
        self.assertEqual(self.call("GET", "/")[0], 200)
        self.assertEqual(self.call("GET", f"/employees/{emplid}")[0], 200)

    def test_scim_http(self):
        self.assertEqual(self.call("GET", "/scim/v2/Users", auth=None)[0], 401)
        st, body = self.call("GET", "/scim/v2/ServiceProviderConfig", auth="scim")
        self.assertEqual((st, body["patch"]["supported"]), (200, True))
        st, body = self.call("POST", "/scim/v2/Users", {"userName": "new.user@gbi.example.com", "name": {"givenName": "New", "familyName": "User"}}, auth="scim")
        self.assertEqual(st, 201)
        st, _ = self.call("DELETE", f"/scim/v2/Users/{body['id']}", auth="scim")
        self.assertEqual(st, 204)


if __name__ == "__main__":
    unittest.main()


class SSOTests(unittest.TestCase):
    """Header-based sign-on for Okta Access Gateway."""

    def setUp(self):
        self.conn = fresh_conn()
        for k in ("PS_SSO_SECRET", "PS_SSO_TRUSTED_PROXIES", "PS_SSO_AUTOCREATE"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.conn.close()
        for k in ("PS_SSO_SECRET", "PS_SSO_TRUSTED_PROXIES", "PS_SSO_AUTOCREATE"):
            os.environ.pop(k, None)

    def test_no_header_is_rejected(self):
        from peopleschoft import sso
        with self.assertRaises(sso.SSOError) as cm:
            sso.authenticate(self.conn, {}, "127.0.0.1")
        self.assertEqual(cm.exception.status, 401)

    def test_seeded_profile_and_roles(self):
        from peopleschoft import sso
        p = sso.authenticate(self.conn, {"PS_SSO_UID": "margaret.chen@gbi.example.com"}, "127.0.0.1")
        self.assertEqual((p.oprid, p.emplid, p.is_admin, p.created), ("margaret.chen@gbi.example.com", "100001", False, False))
        p = sso.authenticate(self.conn, {"PS-SSO-UID": "margaret.chen@gbi.example.com", "PS_SSO_GROUPS": "Everyone, HR Administrator"}, "127.0.0.1")
        self.assertTrue(p.is_admin)
        self.assertIn("HR Administrator", p.roles)
        self.assertIsNotNone(db.row(self.conn, "SELECT LASTSIGNONDTTM FROM PSOPRDEFN WHERE OPRID=?", (p.oprid,))["LASTSIGNONDTTM"])

    def test_fallback_header_and_jit(self):
        from peopleschoft import sso
        p = sso.authenticate(self.conn, {"OAM_REMOTE_USER": "hannah.schmidt@gbi.example.com"}, "127.0.0.1")
        self.assertEqual((p.emplid, p.created, p.header_name), ("100011", True, "OAM_REMOTE_USER"))
        p = sso.authenticate(self.conn, {"PS_SSO_UID": "someone@okta.example", "PS_SSO_NAME": "Some One"}, "127.0.0.1")
        self.assertEqual((p.emplid, p.created, p.name), ("", True, "Some One"))
        os.environ["PS_SSO_AUTOCREATE"] = "0"
        with self.assertRaises(sso.SSOError) as cm:
            sso.authenticate(self.conn, {"PS_SSO_UID": "nobody@okta.example"}, "127.0.0.1")
        self.assertEqual(cm.exception.status, 403)

    def test_secret_and_trusted_proxies(self):
        from peopleschoft import sso
        os.environ["PS_SSO_SECRET"] = "s3cret"
        with self.assertRaises(sso.SSOError):
            sso.authenticate(self.conn, {"PS_SSO_UID": "margaret.chen@gbi.example.com"}, "127.0.0.1")
        p = sso.authenticate(self.conn, {"PS_SSO_UID": "margaret.chen@gbi.example.com", "PS_SSO_SECRET": "s3cret"}, "127.0.0.1")
        self.assertEqual(p.emplid, "100001")
        os.environ["PS_SSO_TRUSTED_PROXIES"] = "10.0.0.0/8, 192.168.1.5"
        with self.assertRaises(sso.SSOError):
            sso.authenticate(self.conn, {"PS_SSO_UID": "margaret.chen@gbi.example.com", "PS_SSO_SECRET": "s3cret"}, "127.0.0.1")
        p = sso.authenticate(self.conn, {"PS_SSO_UID": "margaret.chen@gbi.example.com", "PS_SSO_SECRET": "s3cret"}, "10.20.30.40")
        self.assertEqual(p.emplid, "100001")

    def test_locked_profile(self):
        from peopleschoft import sso
        self.conn.execute("UPDATE PSOPRDEFN SET ACCTLOCK=1 WHERE OPRID='margaret.chen@gbi.example.com'")
        self.conn.commit()
        with self.assertRaises(sso.SSOError) as cm:
            sso.authenticate(self.conn, {"PS_SSO_UID": "margaret.chen@gbi.example.com"}, "127.0.0.1")
        self.assertIn("locked", cm.exception.detail)


class SSOHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fresh_conn().close()
        os.environ["PS_UI_AUTH"] = "header"
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PS_UI_AUTH", None)
        cls.httpd.server_close()

    def get(self, path, headers=None, method="GET", data=None):
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as ex:
            return ex.code, ex.read().decode()

    def test_ui_requires_gateway_headers(self):
        self.assertEqual(self.get("/employees")[0], 401)
        st, body = self.get("/employees/100001", {"PS_SSO_UID": "margaret.chen@gbi.example.com"})
        self.assertEqual(st, 200)
        self.assertIn("Read only", body)
        st, _ = self.get("/employees/100001/personal", {"PS_SSO_UID": "margaret.chen@gbi.example.com"}, "POST", b"firstName=M&lastName=C")
        self.assertEqual(st, 403)
        st, body = self.get("/employees/100001/personal", {"PS_SSO_UID": "margaret.chen@gbi.example.com", "PS_SSO_GROUPS": "HR Administrator"},
                            "POST", b"firstName=Margaret&lastName=Chen&preferredFirstName=Maggie&workEmail=margaret.chen@gbi.example.com")
        self.assertIn(st, (200, 303))   # urllib follows the 303 to the saved page
        self.assertIn("Saved", body) if st == 200 else None
        self.assertEqual(self.get("/signon", {"PS_SSO_UID": "margaret.chen@gbi.example.com"})[0], 200)

    def test_api_auth_still_works_in_gateway_mode(self):
        basic = {"Authorization": "Basic " + base64.b64encode(b"PS:PS").decode()}
        self.assertEqual(self.get("/api/v1/workers", basic)[0], 200)
        self.assertEqual(self.get("/api/v1/workers", {"PS_SSO_UID": "margaret.chen@gbi.example.com"})[0], 200)
        self.assertEqual(self.get("/api/v1/workers")[0], 401)
        self.assertEqual(self.get("/scim/v2/Users", {"Authorization": "Bearer peopleschoft-scim-token"})[0], 200)


class HrMasterTests(unittest.TestCase):
    """HR-as-a-source: SCIM feed for the Okta Provisioning Agent and SQL export for the Generic Databases connector."""

    def setUp(self):
        self.conn = fresh_conn()
        self.base = "http://hr"

    def tearDown(self):
        self.conn.close()

    def test_feed_list_filter_and_paging(self):
        from peopleschoft import hrscim
        page = hrscim.list_users(self.conn, self.base, 1, None, 1, 10)
        self.assertEqual((page["totalResults"], page["itemsPerPage"], page["startIndex"]), (32, 10, 1))
        self.assertEqual(page["schemas"], ["urn:scim:schemas:core:1.0"])
        u = page["Resources"][0]
        self.assertEqual((u["id"], u["userName"], u["active"]), ("100001", "margaret.chen@gbi.example.com", True))
        self.assertEqual(u["urn:scim:schemas:extension:enterprise:1.0"]["employeeNumber"], "100001")
        self.assertIn("urn:okta:peopleschoft:1.0:user", u)
        last = hrscim.list_users(self.conn, self.base, 1, None, 31, 10)
        self.assertEqual(last["itemsPerPage"], 2)
        f = hrscim.list_users(self.conn, self.base, 1, 'userName eq "MARGARET.chen@gbi.example.com"')
        self.assertEqual(f["totalResults"], 1)
        f = hrscim.list_users(self.conn, self.base, 1, 'urn:scim:schemas:extension:enterprise:1.0.employeeNumber eq "100026"')
        self.assertEqual((f["totalResults"], f["Resources"][0]["active"]), (1, False))
        self.assertEqual(hrscim.list_users(self.conn, self.base, 1, 'userName eq "nobody"')["totalResults"], 0)
        self.assertEqual(hrscim.list_users(self.conn, self.base, 1, 'meta.lastModified gt "2099-01-01T00:00:00Z"')["totalResults"], 0)
        with self.assertRaises(hrscim.HrScimError):
            hrscim.list_users(self.conn, self.base, 1, 'title co "x"')
        v2 = hrscim.list_users(self.conn, self.base, 2, None, 1, 1)
        self.assertEqual(v2["schemas"], ["urn:ietf:params:scim:api:messages:2.0:ListResponse"])
        self.assertEqual(v2["Resources"][0]["schemas"][0], "urn:ietf:params:scim:schemas:core:2.0:User")

    def test_incremental_and_prehire_window(self):
        from peopleschoft import hrscim
        import time
        time.sleep(1.1)
        ts = db.now_iso()
        time.sleep(1.1)
        hr.promote(self.conn, "100011", "SWE4", effdt=TODAY, comp_rate=1)
        f = hrscim.list_users(self.conn, self.base, 1, f'meta.lastModified gt "{ts}"')
        self.assertEqual([u["id"] for u in f["Resources"]], ["100011"])
        far = hr.hire(self.conn, {"firstName": "Far", "lastName": "Future", "deptid": "13000", "jobcode": "SWE1",
                                  "hireDate": (date.today() + timedelta(days=60)).isoformat()})
        self.assertFalse(hrscim.visible(far))
        with self.assertRaises(hrscim.HrScimError):
            hrscim.get_user(self.conn, far["emplid"], self.base, 1)
        near = hr.get_worker(self.conn, "100032")
        self.assertTrue(hrscim.visible(near))
        self.assertTrue(hrscim.to_user(near, self.base, 1)["active"])

    def test_groups_and_capabilities(self):
        from peopleschoft import hrscim
        g = hrscim.list_groups(self.conn, self.base, 1)
        self.assertEqual(g["totalResults"], 10)
        eng = hrscim.get_group(self.conn, "13000", self.base, 1)
        self.assertIn({"value": "100011", "display": "Hannah Schmidt"}, eng["members"])
        spc = hrscim.service_provider_config(self.base, 1)
        self.assertIn("IMPORT_NEW_USERS", spc["urn:okta:schemas:scim:providerconfig:1.0"]["userManagementCapabilities"])
        with self.assertRaises(hrscim.HrScimError) as cm:
            hrscim.replace_user(self.conn, "100001", {"active": False}, self.base, 1)
        self.assertEqual(cm.exception.status, 405)

    def test_writeback_when_enabled(self):
        from peopleschoft import hrscim
        os.environ["PS_HR_SCIM_WRITEBACK"] = "1"
        try:
            u = hrscim.replace_user(self.conn, "100013", {"name": {"givenName": "Sofia", "familyName": "Rossi-Bianchi"}, "active": False}, self.base, 1)
            self.assertEqual((u["active"], u["name"]["familyName"]), (False, "Rossi-Bianchi"))
            self.assertEqual(hr.get_worker(self.conn, "100013")["emplStatus"], "T")
        finally:
            os.environ.pop("PS_HR_SCIM_WRITEBACK", None)

    def test_sql_export_loads_and_tracks_changes(self):
        import sqlite3
        from peopleschoft import sqlexport
        mirror = sqlite3.connect(":memory:")
        mirror.executescript(sqlexport.render(self.conn, "sqlite"))
        self.assertEqual(mirror.execute("SELECT COUNT(*) FROM hr_worker").fetchone()[0], 32)
        self.assertEqual(mirror.execute("SELECT account_status FROM hr_worker WHERE emplid='100026'").fetchone()[0], "INACTIVE")
        self.assertEqual(mirror.execute("SELECT entitlements FROM hr_worker_v WHERE emplid='100001'").fetchone()[0],
                         "DEPT:10000,JOBCODE:CEO001,ROLE:Employee,ROLE:PeopleSoft User")
        hr.transfer(self.conn, "100011", deptid="13100", location="AUS01", supervisor_id="100014")
        mirror.executescript(sqlexport.render(self.conn, "sqlite", include_ddl=False))
        self.assertEqual(mirror.execute("SELECT department FROM hr_worker WHERE emplid='100011'").fetchone()[0], "Platform Engineering")
        self.assertEqual(mirror.execute("SELECT is_deleted FROM hr_worker_entitlement WHERE emplid='100011' AND entitlement_id='DEPT:13000'").fetchone()[0], 1)
        for d in ("postgres", "mysql", "mssql"):
            text = sqlexport.render(self.conn, d)
            self.assertNotIn("None", text)
            self.assertIn("hr_worker_v", text)
        with self.assertRaises(ValueError):
            sqlexport.render(self.conn, "oracle")
