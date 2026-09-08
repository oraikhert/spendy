"""Workspace migration checks on disposable SQLite with foreign keys enabled."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC = Path(sys.executable).with_name("alembic")
TABLES = ("accounts", "cards", "transactions", "source_payloads", "transaction_observations", "bank_statement_details", "transaction_source_links")


class WorkspaceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="spendy-workspace-migration-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "database.sqlite3"
        self.migrate("upgrade", "txn_summary_excl_001")

    def migrate(self, *args, success=True):
        result = subprocess.run([str(ALEMBIC), *args], cwd=ROOT,
            env={**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{self.path}", "DEBUG": "false"},
            capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def connect(self):
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def seed(self, users=True, finances=True):
        with self.connect() as db:
            if users:
                db.executescript("""
                INSERT INTO users(id,email,username,hashed_password,is_active,is_superuser,created_at,updated_at)
                VALUES (9,'nine@example.test','nine','unused',1,1,'2026-01-01','2026-01-01'),
                       (3,'three@example.test','three','unused',0,0,'2026-01-01','2026-01-01');
                """)
            if finances:
                db.executescript("""
                INSERT INTO accounts VALUES (1,'Synthetic bank','Main','AED','2026-01-01','2026-01-01','UTC');
                INSERT INTO cards(id,account_id,card_masked_number,card_type,name,created_at,updated_at)
                VALUES(1,1,'****1111','credit','Card','2026-01-01','2026-01-01');
                INSERT INTO transactions(id,card_id,amount,currency,description,transaction_kind,created_at,updated_at)
                VALUES(1,1,-10,'AED','Synthetic','purchase','2026-01-01','2026-01-01');
                INSERT INTO source_payloads(id,source_kind,media_type,ingestion_method,raw_text,content_hash,idempotency_key,received_at,processing_status,ingestion_metadata,created_at,updated_at)
                VALUES(1,'sms','text/plain','phone_api','Synthetic','hash','key','2026-01-01','processed','{}','2026-01-01','2026-01-01');
                INSERT INTO transaction_observations(id,source_payload_id,source_item_key,account_id,card_id,extraction_metadata,created_at,updated_at)
                VALUES(1,1,'1',1,1,'{}','2026-01-01','2026-01-01');
                INSERT INTO bank_statement_details(source_payload_id,account_id,card_id) VALUES(1,1,1);
                INSERT INTO transaction_source_links(observation_id,transaction_id,match_method,matched_at)
                VALUES(1,1,'migration','2026-01-01');
                """)

    def test_backfill_owner_constraints_and_safe_downgrade(self):
        self.seed()
        with self.connect() as db:
            db.execute("UPDATE sqlite_sequence SET seq=50 WHERE name='transaction_observations'")
        self.migrate("upgrade", "head")
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT seq FROM sqlite_sequence WHERE name='transaction_observations'").fetchone()[0], 50)
            self.assertIn("AUTOINCREMENT", db.execute("SELECT sql FROM sqlite_master WHERE name='transaction_observations'").fetchone()[0])
            self.assertNotIn("is_superuser", [row[1] for row in db.execute("PRAGMA table_info(users)")])
            workspace_id = db.execute("SELECT id FROM workspaces WHERE name='Legacy Workspace'").fetchone()[0]
            self.assertEqual(db.execute("SELECT user_id,role FROM workspace_members ORDER BY user_id").fetchall(), [(3,"owner"),(9,"editor")])
            for table in TABLES:
                self.assertEqual(db.execute(f"SELECT workspace_id FROM {table}").fetchall(), [(workspace_id,)])
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(f"UPDATE {table} SET workspace_id=NULL")
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.migrate("downgrade", "txn_summary_excl_001")
        with self.connect() as db:
            for table in TABLES:
                self.assertEqual(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT seq FROM sqlite_sequence WHERE name='transaction_observations'").fetchone()[0], 50)
            self.assertEqual(db.execute("SELECT is_superuser FROM users").fetchall(), [(0,), (0,)])
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.migrate("upgrade", "head")

    def test_same_workspace_graph_and_guarded_downgrade(self):
        self.seed()
        self.migrate("upgrade", "head")
        with self.connect() as db:
            db.execute("INSERT INTO workspaces(id,name,status,created_at,updated_at) VALUES(2,'Other','active','2026-01-01','2026-01-01')")
            # Each edge, not just each standalone workspace FK, must be protected.
            for table in TABLES[1:]:
                if table == "source_payloads":
                    continue
                with self.subTest(table=table), self.assertRaises(sqlite3.IntegrityError):
                    db.execute(f"UPDATE {table} SET workspace_id=2")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE workspace_members SET role='admin'")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO workspace_members(workspace_id,user_id,role,joined_at,created_at,updated_at) SELECT workspace_id,user_id,role,joined_at,created_at,updated_at FROM workspace_members LIMIT 1")
        failed = self.migrate("downgrade", "txn_summary_excl_001", success=False)
        self.assertIn("multiple workspace scopes", failed.stderr)
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT version_num FROM alembic_version").fetchone()[0], "workspace_ownership_001")
            self.assertEqual(db.execute("SELECT count(*) FROM workspaces").fetchone()[0], 2)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_retained_finances_without_users(self):
        self.seed(users=False)
        self.migrate("upgrade", "head")
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT name,created_by_user_id FROM workspaces").fetchall(), [("Legacy Workspace",None)])
            self.assertEqual(db.execute("SELECT count(*) FROM workspace_members").fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_empty_installation_and_users_only(self):
        self.migrate("upgrade", "head")
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM workspaces").fetchone()[0], 0)
        self.migrate("downgrade", "txn_summary_excl_001")
        self.seed(finances=False)
        self.migrate("upgrade", "head")
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT user_id,role FROM workspace_members ORDER BY user_id").fetchall(), [(3,"owner"),(9,"editor")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
