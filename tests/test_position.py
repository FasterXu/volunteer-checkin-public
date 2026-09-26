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
            self.assertEqual(page_html.count('class="table-sort"'), 8)
            self.assertIn('data-sort="sign_time"', page_html)
            self.assertIn('data-sort="source_note"', page_html)
            self.assertNotIn("补签", page_html)
            self.assertNotIn("修改活动信息", page_html)
            self.assertNotIn("删除", page_html)

            api_response = self.client.get(f"/observe/{token}/participants")
            self.assertEqual(api_response.status_code, 200)
            observer_participants = api_response.get_json()["participants"]
            self.assertGreaterEqual(len(observer_participants), 1)
            self.assertIn("phone", observer_participants[0])
            self.assertIn("position", observer_participants[0])
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
                "SELECT position FROM participants WHERE identifier = 'OLD-001'"
            ).fetchone()["position"]
            observer_token = db.execute(
                "SELECT observer_token FROM activities WHERE id = 1"
            ).fetchone()["observer_token"]
        self.assertIn("position", columns)
        self.assertEqual(legacy_position, "")
        self.assertGreaterEqual(len(observer_token), 24)

        roster = "姓名,学号/工号,手机号,岗位\n测试用户,T-001,13800000000,签到引导\n"
        response = self.client.post(
            "/activities/1/upload",
            data={"roster": (BytesIO(roster.encode("utf-8")), "roster.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)

        response = self.client.get("/admin", query_string={"activity_id": 1})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="editParticipantPosition"', response.data)
        self.assertIn(b'id="copyObserverLink"', response.data)
        admin_html = response.data.decode("utf-8")
        self.assertIn(
            'class="stat-card danger" data-filter="unsigned" role="button"',
            admin_html,
        )
        self.assertEqual(admin_html.count('class="table-sort"'), 8)
        self.assertIn('data-sort="position"', admin_html)

        response = self.client.get(
            "/api/activities/1/participants", query_string={"q": "签到引导"}
        )
        self.assertEqual(response.status_code, 200)
        participants = response.get_json()["participants"]
        self.assertEqual(len(participants), 1)
        self.assertEqual(participants[0]["position"], "签到引导")

        participant_id = participants[0]["id"]
        response = self.client.patch(
            f"/participants/{participant_id}",
            json={
                "name": "测试用户",
                "identifier": "T-001",
                "phone": "13800000000",
                "position": "现场协调",
                "note": "",
            },
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/activities/1/export.csv")
        exported = response.data.decode("utf-8-sig")
        self.assertIn("姓名,学号/工号,手机号,岗位,签到状态", exported)
        self.assertIn("现场协调", exported)

        sample_path = Path(__file__).resolve().parents[1] / "sample_roster.csv"
        with sample_path.open(encoding="utf-8-sig", newline="") as sample_file:
            rows = list(csv.reader(sample_file))
        self.assertEqual(rows[0], ["姓名", "学号/工号", "手机号", "岗位"])
        self.assertTrue(all(len(row) == 4 for row in rows))


if __name__ == "__main__":
    unittest.main()
