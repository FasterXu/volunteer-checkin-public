import csv
import gc
import importlib
import os
import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path


class PositionFieldTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.database_path = Path(cls.temp_dir.name) / "legacy.db"
        db = sqlite3.connect(cls.database_path)
        try:
            db.executescript(
                """
                CREATE TABLE activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    location TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    start_time TEXT,
                    end_time TEXT,
                    status TEXT NOT NULL DEFAULT 'draft',
                    code TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE participants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    identifier TEXT NOT NULL,
                    phone TEXT NOT NULL DEFAULT '',
                    signed_in INTEGER NOT NULL DEFAULT 0,
                    sign_time TEXT,
                    source TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    UNIQUE(activity_id, identifier)
                );
                INSERT INTO activities(
                    name, location, description, status, code, created_at
                ) VALUES ('岗位测试活动', '', '', 'draft', 'ROLE01', '2026-01-01T00:00:00+08:00');
                INSERT INTO participants(
                    activity_id, name, identifier, phone, updated_at
                ) VALUES (1, '旧名单用户', 'OLD-001', '', '2026-01-01T00:00:00+08:00');
                """
            )
        finally:
            db.close()

        os.environ["SIGNIN_DATABASE"] = str(cls.database_path)
        os.environ.pop("ADMIN_PASSWORD", None)
        cls.app_module = importlib.import_module("app")
        cls.app_module.app.config.update(TESTING=True)
        cls.client = cls.app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("SIGNIN_DATABASE", None)
        cls.client = None
        gc.collect()
        cls.temp_dir.cleanup()

    def test_observer_link_is_public_and_read_only(self):
        with self.app_module.get_db() as db:
            activity = db.execute("SELECT * FROM activities WHERE id = 1").fetchone()
            participant = db.execute(
                "SELECT * FROM participants WHERE activity_id = 1 LIMIT 1"
            ).fetchone()
        token = activity["observer_token"]
        self.assertGreaterEqual(len(token), 24)

        create_response = self.client.post(
            "/activities", data={"name": "新建观察员测试活动"}
        )
        self.assertEqual(create_response.status_code, 302)
        with self.app_module.get_db() as db:
            created_token = db.execute(
                "SELECT observer_token FROM activities WHERE name = ?",
                ("新建观察员测试活动",),
            ).fetchone()["observer_token"]
        self.assertGreaterEqual(len(created_token), 24)
        self.assertNotEqual(created_token, token)

        os.environ["ADMIN_PASSWORD"] = "test-admin-password"
        try:
            admin_response = self.client.get("/admin")
            self.assertEqual(admin_response.status_code, 302)
            self.assertIn("/login", admin_response.headers["Location"])

            page_response = self.client.get(f"/observe/{token}")
            self.assertEqual(page_response.status_code, 200)
            page_html = page_response.data.decode("utf-8")
            self.assertIn("实时只读", page_html)
            self.assertIn(
                'class="stat-card success" data-filter="signed" role="button"',
                page_html,
            )
            self.assertEqual(page_html.count('class="table-sort"'), 11)
            self.assertIn('id="shiftGroupSummary"', page_html)
            self.assertIn('data-sort="sign_time"', page_html)
            self.assertIn('data-sort="location_status"', page_html)
            self.assertIn('data-sort="source_note"', page_html)
            self.assertNotIn('id="toggleCredentialVerifier"', page_html)
            self.assertNotIn("补签", page_html)
            self.assertNotIn("修改活动信息", page_html)
            self.assertNotIn("删除", page_html)

            api_response = self.client.get(f"/observe/{token}/participants")
            self.assertEqual(api_response.status_code, 200)
            observer_participants = api_response.get_json()["participants"]
            self.assertGreaterEqual(len(observer_participants), 1)
            self.assertIn("phone", observer_participants[0])
            self.assertIn("shift", observer_participants[0])
            self.assertIn("position", observer_participants[0])
            self.assertIn("location_status", observer_participants[0])
            self.assertIn("attendance_status", observer_participants[0])
            self.assertIn("location_distance", observer_participants[0])
            self.assertNotIn("id", observer_participants[0])
            self.assertNotIn("activity_id", observer_participants[0])
            self.assertNotIn("updated_at", observer_participants[0])

            export_response = self.client.get(f"/observe/{token}/export.csv")
            self.assertEqual(export_response.status_code, 200)
            self.assertIn("签到状态".encode("utf-8"), export_response.data)

            mutation_response = self.client.post(
                f"/participants/{participant['id']}/toggle",
                json={"signed": True},
            )
            self.assertEqual(mutation_response.status_code, 401)

            self.assertEqual(self.client.get("/observe/not-a-valid-token").status_code, 404)
            self.assertIn(self.client.post(f"/observe/{token}").status_code, {302, 405})
        finally:
            os.environ.pop("ADMIN_PASSWORD", None)

    def test_position_migration_import_search_edit_and_export(self):
        with self.app_module.get_db() as db:
            columns = {
                row["name"]
                for row in db.execute("PRAGMA table_info(participants)").fetchall()
            }
            legacy_position = db.execute(
                "SELECT shift, position FROM participants WHERE identifier = 'OLD-001'"
            ).fetchone()
            observer_token = db.execute(
                "SELECT observer_token FROM activities WHERE id = 1"
            ).fetchone()["observer_token"]
        self.assertIn("position", columns)
        self.assertIn("shift", columns)
        self.assertEqual(legacy_position["position"], "")
        self.assertEqual(legacy_position["shift"], "")
        self.assertGreaterEqual(len(observer_token), 24)

        roster = "姓名,学号/工号,手机号,班次,岗位\n测试用户,T-001,13800000000,上午班,签到引导\n"
        response = self.client.post(
            "/activities/1/upload",
            data={"roster": (BytesIO(roster.encode("utf-8")), "roster.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.get("/admin", query_string={"activity_id": 1})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="editParticipantShift"', response.data)
        self.assertIn(b'id="editParticipantPosition"', response.data)
        self.assertIn(b'id="copyObserverLink"', response.data)
        admin_html = response.data.decode("utf-8")
        self.assertIn(
            'class="stat-card danger" data-filter="unsigned" role="button"',
            admin_html,
        )
        self.assertEqual(admin_html.count('class="table-sort"'), 11)
        self.assertIn('data-sort="shift"', admin_html)
        self.assertIn('data-sort="position"', admin_html)
        self.assertIn('data-sort="location_status"', admin_html)
        self.assertIn('data-sort="attendance_status"', admin_html)

        response = self.client.get(
            "/api/activities/1/participants", query_string={"q": "签到引导"}
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        participants = payload["participants"]
        self.assertEqual(len(participants), 1)
        self.assertEqual(participants[0]["shift"], "上午班")
        self.assertEqual(participants[0]["position"], "签到引导")
        self.assertTrue(any(group["label"] == "上午班" for group in payload["groups"]["shifts"]))
        self.assertTrue(any(group["label"] == "签到引导" for group in payload["groups"]["positions"]))

        filtered = self.client.get(
            "/api/activities/1/participants", query_string={"shift": "上午班"}
        ).get_json()["participants"]
        self.assertEqual([person["identifier"] for person in filtered], ["T-001"])

        participant_id = participants[0]["id"]
        response = self.client.patch(
            f"/participants/{participant_id}",
            json={
                "name": "测试用户",
                "identifier": "T-001",
                "phone": "13800000000",
                "shift": "下午班",
                "position": "现场协调",
                "note": "",
            },
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/activities/1/export.csv")
        exported = response.data.decode("utf-8-sig")
        self.assertIn("姓名,学号/工号,手机号,班次,岗位,签到状态", exported)
        self.assertIn("下午班", exported)
        self.assertIn("现场协调", exported)

        sample_path = Path(__file__).resolve().parents[1] / "sample_roster.csv"
        with sample_path.open(encoding="utf-8-sig", newline="") as sample_file:
            rows = list(csv.reader(sample_file))
        self.assertEqual(rows[0], ["姓名", "学号/工号", "手机号", "班次", "岗位"])
        self.assertTrue(all(len(row) == 5 for row in rows))

    def test_attendance_status_normal_late_manual_and_no_start_time(self):
        response = self.client.post(
            "/activities/1/edit",
            data={
                "name": "考勤状态测试活动",
                "location": "",
                "description": "",
                "late_grace_minutes": "10",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.post("/activities/1/status", data={"status": "active"})

        with self.app_module.get_db() as db:
            for name, identifier in (
                ("无时间用户", "ATT-NORMAL"),
                ("迟到用户", "ATT-LATE"),
                ("补签用户", "ATT-MANUAL"),
            ):
                db.execute(
                    """
                    INSERT INTO participants(activity_id, name, identifier, phone, position, updated_at)
                    VALUES (1, ?, ?, '', '状态测试', ?)
                    """,
                    (name, identifier, self.app_module.now_text()),
                )

        self.client.post(
            "/sign/ROLE01", data={"name": "无时间用户", "identifier": "ATT-NORMAL"}
        )
        with self.app_module.get_db() as db:
            normal = db.execute(
                "SELECT * FROM participants WHERE identifier = 'ATT-NORMAL'"
            ).fetchone()
        self.assertEqual(normal["attendance_status"], "normal")
        self.assertEqual(normal["credential_token"], "")

        response = self.client.post(
            "/activities/1/edit",
            data={
                "name": "考勤状态测试活动",
                "location": "",
                "description": "",
                "start_time": "2000-01-01T00:00",
                "late_grace_minutes": "10",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.post(
            "/sign/ROLE01", data={"name": "迟到用户", "identifier": "ATT-LATE"}
        )

        with self.app_module.get_db() as db:
            manual_id = db.execute(
                "SELECT id FROM participants WHERE identifier = 'ATT-MANUAL'"
            ).fetchone()["id"]
        self.client.post(
            f"/participants/{manual_id}/toggle",
            json={"signed": True, "note": "现场确认"},
        )

        payload = self.client.get("/api/activities/1/participants").get_json()
        statuses = {
            person["identifier"]: person["attendance_status"]
            for person in payload["participants"]
            if person["identifier"].startswith("ATT-")
        }
        self.assertEqual(statuses["ATT-NORMAL"], "normal")
        self.assertEqual(statuses["ATT-LATE"], "late")
        self.assertEqual(statuses["ATT-MANUAL"], "manual")
        self.assertGreaterEqual(payload["summary"]["late"], 1)
        self.assertGreaterEqual(payload["summary"]["exception"], 2)

        late_rows = self.client.get(
            "/api/activities/1/participants", query_string={"status": "late"}
        ).get_json()["participants"]
        self.assertEqual([person["identifier"] for person in late_rows], ["ATT-LATE"])
        exception_ids = {
            person["identifier"]
            for person in self.client.get(
                "/api/activities/1/participants", query_string={"status": "exception"}
            ).get_json()["participants"]
        }
        self.assertEqual(exception_ids, {"ATT-LATE", "ATT-MANUAL"})

        exported = self.client.get(
            "/activities/1/export.csv", query_string={"status": "exception"}
        ).data.decode("utf-8-sig")
        self.assertIn("签到状态,考勤状态,签到时间", exported)
        self.assertIn("迟到", exported)
        self.assertIn("管理员补签", exported)
        self.assertNotIn("ATT-NORMAL", exported)

        with self.app_module.get_db() as db:
            db.execute("DELETE FROM participants WHERE identifier LIKE 'ATT-%'")
            db.execute(
                """
                UPDATE activities SET name = '岗位测试活动', status = 'draft',
                    start_time = NULL, end_time = NULL, late_grace_minutes = 0
                WHERE id = 1
                """
            )

    def test_credential_generation_qr_verification_and_revocation(self):
        self.client.post(
            "/activities/1/edit",
            data={
                "name": "电子凭证测试活动",
                "location": "",
                "description": "",
                "credential_check_enabled": "1",
            },
        )
        self.client.post("/activities/1/status", data={"status": "active"})
        with self.app_module.get_db() as db:
            db.execute(
                """
                INSERT INTO participants(
                    activity_id, name, identifier, phone, shift, position, updated_at
                ) VALUES (1, '凭证测试用户', 'CRED-001', '', '上午班', '现场引导', ?)
                """,
                (self.app_module.now_text(),),
            )

        sign_response = self.client.post(
            "/sign/ROLE01",
            data={"name": "凭证测试用户", "identifier": "CRED-001"},
        )
        self.assertEqual(sign_response.status_code, 302)
        self.assertIn("/credential/", sign_response.headers["Location"])

        with self.app_module.get_db() as db:
            participant = db.execute(
                "SELECT * FROM participants WHERE identifier = 'CRED-001'"
            ).fetchone()
            observer_token = db.execute(
                "SELECT observer_token FROM activities WHERE id = 1"
            ).fetchone()["observer_token"]
        credential_token = participant["credential_token"]
        self.assertGreaterEqual(len(credential_token), 24)

        credential_page = self.client.get(f"/credential/{credential_token}")
        credential_html = credential_page.get_data(as_text=True)
        self.assertEqual(credential_page.status_code, 200)
        self.assertIn("签到电子凭证", credential_html)
        self.assertIn("凭证测试用户", credential_html)
        self.assertIn(f"/credential/{credential_token}/qr.png", credential_html)

        qr_response = self.client.get(f"/credential/{credential_token}/qr.png")
        self.assertEqual(qr_response.status_code, 200)
        self.assertEqual(qr_response.mimetype, "image/png")
        self.assertTrue(qr_response.data.startswith(b"\x89PNG"))

        full_credential_url = f"https://example.test/credential/{credential_token}"
        admin_verify = self.client.post(
            "/api/activities/1/credentials/verify", json={"value": full_credential_url}
        )
        self.assertEqual(admin_verify.status_code, 200)
        self.assertTrue(admin_verify.get_json()["ok"])
        self.assertEqual(admin_verify.get_json()["credential"]["identifier"], "CRED-001")

        observer_verify = self.client.post(
            f"/observe/{observer_token}/credentials/verify",
            json={"value": credential_token},
        )
        self.assertEqual(observer_verify.status_code, 200)
        self.assertTrue(observer_verify.get_json()["ok"])

        self.client.post(
            "/activities",
            data={"name": "其他凭证测试活动", "credential_check_enabled": "1"},
        )
        with self.app_module.get_db() as db:
            other_activity_id = db.execute(
                "SELECT id FROM activities WHERE name = '其他凭证测试活动'"
            ).fetchone()["id"]
        cross_activity = self.client.post(
            f"/api/activities/{other_activity_id}/credentials/verify",
            json={"value": credential_token},
        )
        self.assertEqual(cross_activity.status_code, 404)
        self.assertIn("不属于当前活动", cross_activity.get_json()["message"])

        admin_page = self.client.get("/admin", query_string={"activity_id": 1}).get_data(as_text=True)
        observer_page = self.client.get(f"/observe/{observer_token}").get_data(as_text=True)
        for page_html in (admin_page, observer_page):
            self.assertIn('id="toggleCredentialVerifier"', page_html)
            self.assertIn('id="credentialScanInput"', page_html)
            self.assertIn('id="startCredentialCamera"', page_html)
            self.assertIn("html5-qrcode@2.3.8", page_html)

        self.client.post(
            "/activities/1/edit",
            data={"name": "电子凭证测试活动", "location": "", "description": ""},
        )
        disabled_verify = self.client.post(
            "/api/activities/1/credentials/verify", json={"value": credential_token}
        )
        self.assertEqual(disabled_verify.status_code, 403)
        self.assertIn("未启用", disabled_verify.get_json()["message"])
        self.assertEqual(self.client.get(f"/credential/{credential_token}").status_code, 404)
        disabled_admin_page = self.client.get(
            "/admin", query_string={"activity_id": 1}
        ).get_data(as_text=True)
        self.assertNotIn('id="toggleCredentialVerifier"', disabled_admin_page)

        self.client.post(
            "/activities/1/edit",
            data={
                "name": "电子凭证测试活动",
                "location": "",
                "description": "",
                "credential_check_enabled": "1",
            },
        )
        self.assertEqual(
            self.client.post(
                "/api/activities/1/credentials/verify", json={"value": credential_token}
            ).status_code,
            200,
        )

        self.client.post(
            f"/participants/{participant['id']}/toggle",
            json={"signed": False, "note": "取消测试"},
        )
        revoked = self.client.post(
            "/api/activities/1/credentials/verify", json={"value": credential_token}
        )
        self.assertEqual(revoked.status_code, 409)
        self.assertFalse(revoked.get_json()["ok"])
        self.assertIn("已失效", revoked.get_json()["message"])
        self.assertIn(
            "凭证已失效", self.client.get(f"/credential/{credential_token}").get_data(as_text=True)
        )

        with self.app_module.get_db() as db:
            db.execute("DELETE FROM participants WHERE identifier = 'CRED-001'")
            db.execute("DELETE FROM activities WHERE id = ?", (other_activity_id,))
            db.execute(
                "UPDATE activities SET name = '岗位测试活动', status = 'draft' WHERE id = 1"
            )

    def test_location_verification_two_step_and_server_enforcement(self):
        response = self.client.post(
            "/activities/1/edit",
            data={
                "name": "岗位测试活动",
                "location": "测试地点",
                "description": "",
                "location_check_enabled": "1",
                "latitude": "31.0000000",
                "longitude": "121.0000000",
                "location_radius": "150",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.post("/activities/1/status", data={"status": "active"})

        with self.app_module.get_db() as db:
            db.execute(
                """
                INSERT INTO participants(activity_id, name, identifier, phone, position, updated_at)
                VALUES (1, '定位测试用户', 'GEO-001', '', '位置测试', ?)
                """,
                (self.app_module.now_text(),),
            )

        page = self.client.get("/sign/ROLE01")
        page_html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="locationStep"', page_html)
        self.assertIn('id="identityStepToggle"', page_html)
        self.assertIn('id="locationStepToggle"', page_html)
        self.assertIn('id="locationStepContent" hidden', page_html)
        self.assertIn("核验签到位置", page_html)
        self.assertIn('data-location-required="true"', page_html)

        base_form = {"name": "定位测试用户", "identifier": "GEO-001"}
        self.client.post("/sign/ROLE01", data=base_form)
        with self.app_module.get_db() as db:
            signed = db.execute(
                "SELECT signed_in FROM participants WHERE identifier = 'GEO-001'"
            ).fetchone()["signed_in"]
        self.assertEqual(signed, 0)

        self.client.post(
            "/sign/ROLE01",
            data={
                **base_form,
                "latitude": "31.0100000",
                "longitude": "121.0000000",
                "location_accuracy": "15",
            },
        )
        with self.app_module.get_db() as db:
            signed = db.execute(
                "SELECT signed_in FROM participants WHERE identifier = 'GEO-001'"
            ).fetchone()["signed_in"]
        self.assertEqual(signed, 0)

        self.client.post(
            "/sign/ROLE01",
            data={
                **base_form,
                "latitude": "31.0000000",
                "longitude": "121.0000000",
                "location_accuracy": "12",
            },
        )
        with self.app_module.get_db() as db:
            participant = db.execute(
                "SELECT * FROM participants WHERE identifier = 'GEO-001'"
            ).fetchone()
        self.assertEqual(participant["signed_in"], 1)
        self.assertEqual(participant["location_status"], "verified")
        self.assertAlmostEqual(participant["location_distance"], 0, places=3)
        self.assertEqual(participant["location_accuracy"], 12)

        export = self.client.get("/activities/1/export.csv").data.decode("utf-8-sig")
        self.assertIn("位置核验,距签到点(米),定位精度(米)", export)
        self.assertIn("范围内,0,12", export)

        with self.app_module.get_db() as db:
            db.execute("DELETE FROM participants WHERE identifier = 'GEO-001'")
            db.execute(
                """
                UPDATE activities SET status = 'draft', location_check_enabled = 0,
                    latitude = NULL, longitude = NULL, location_radius = 200
                WHERE id = 1
                """
            )

    def test_passphrase_verification_follows_location_and_is_server_enforced(self):
        response = self.client.post(
            "/activities/1/edit",
            data={
                "name": "口令测试活动",
                "location": "测试地点",
                "description": "",
                "location_check_enabled": "1",
                "latitude": "31.0000000",
                "longitude": "121.0000000",
                "location_radius": "150",
                "passphrase_check_enabled": "1",
                "passphrase": "红星7",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.post("/activities/1/status", data={"status": "active"})

        with self.app_module.get_db() as db:
            activity = db.execute("SELECT * FROM activities WHERE id = 1").fetchone()
            original_hash = activity["passphrase_hash"]
            db.execute(
                """
                INSERT INTO participants(activity_id, name, identifier, phone, position, updated_at)
                VALUES (1, '口令测试用户', 'PASS-001', '', '口令测试', ?)
                """,
                (self.app_module.now_text(),),
            )
        self.assertEqual(activity["passphrase_check_enabled"], 1)
        self.assertEqual(activity["passphrase_length"], 3)
        self.assertNotIn("红星7", original_hash)
        self.assertTrue(self.app_module.check_password_hash(original_hash, "红星7"))

        page = self.client.get("/sign/ROLE01")
        page_html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn('data-passphrase-required="true"', page_html)
        self.assertIn('data-passphrase-length="3"', page_html)
        self.assertEqual(page_html.count('class="passphrase-cell"'), 3)
        self.assertLess(page_html.index('id="locationStep"'), page_html.index('id="passphraseStep"'))
        self.assertIn("<span>3</span><div><strong>核验签到口令</strong>", page_html)
        self.assertNotIn("红星7", page_html)

        base_form = {
            "name": "口令测试用户",
            "identifier": "PASS-001",
            "latitude": "31.0000000",
            "longitude": "121.0000000",
            "location_accuracy": "10",
        }
        wrong_response = self.client.post(
            "/sign/ROLE01", data={**base_form, "passphrase": "红星8"}, follow_redirects=True
        )
        self.assertIn("签到口令不正确", wrong_response.get_data(as_text=True))
        with self.app_module.get_db() as db:
            signed = db.execute(
                "SELECT signed_in FROM participants WHERE identifier = 'PASS-001'"
            ).fetchone()["signed_in"]
        self.assertEqual(signed, 0)

        self.client.post("/sign/ROLE01", data={**base_form, "passphrase": "红星7"})
        with self.app_module.get_db() as db:
            signed = db.execute(
                "SELECT signed_in FROM participants WHERE identifier = 'PASS-001'"
            ).fetchone()["signed_in"]
        self.assertEqual(signed, 1)

        preserve_response = self.client.post(
            "/activities/1/edit",
            data={
                "name": "口令测试活动",
                "location": "测试地点",
                "description": "",
                "passphrase_check_enabled": "1",
                "passphrase": "",
            },
        )
        self.assertEqual(preserve_response.status_code, 302)
        with self.app_module.get_db() as db:
            preserved = db.execute("SELECT * FROM activities WHERE id = 1").fetchone()
        self.assertEqual(preserved["passphrase_hash"], original_hash)
        self.assertEqual(preserved["passphrase_length"], 3)
        passphrase_only_page = self.client.get("/sign/ROLE01").get_data(as_text=True)
        self.assertIn('data-location-required="false"', passphrase_only_page)
        self.assertNotIn('id="locationStep"', passphrase_only_page)
        self.assertIn("<span>2</span><div><strong>核验签到口令</strong>", passphrase_only_page)

        disabled_response = self.client.post(
            "/activities/1/edit",
            data={"name": "岗位测试活动", "location": "", "description": ""},
        )
        self.assertEqual(disabled_response.status_code, 302)
        with self.app_module.get_db() as db:
            disabled = db.execute("SELECT * FROM activities WHERE id = 1").fetchone()
            db.execute("DELETE FROM participants WHERE identifier = 'PASS-001'")
            db.execute("UPDATE activities SET status = 'draft' WHERE id = 1")
        self.assertEqual(disabled["passphrase_check_enabled"], 0)
        self.assertEqual(disabled["passphrase_hash"], "")
        self.assertEqual(disabled["passphrase_length"], 0)


if __name__ == "__main__":
    unittest.main()
