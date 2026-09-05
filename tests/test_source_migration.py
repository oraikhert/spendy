"""Disposable SQLite upgrade/downgrade checks for the source split revision."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC = Path(sys.executable).with_name("alembic")


class SourceMigrationTests(unittest.TestCase):
    def run_alembic(self, database: Path, *arguments: str) -> subprocess.CompletedProcess:
        environment = {
            **os.environ,
            "DATABASE_URL": f"sqlite+aiosqlite:///{database}",
            "DEBUG": "false",
        }
        return subprocess.run(
            [str(ALEMBIC), *arguments],
            cwd=PROJECT_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_strict_backfill_conflict_resolution_and_lossy_downgrade(self):
        with tempfile.TemporaryDirectory(prefix="spendy-source-migration-") as directory:
            database = Path(directory) / "migration.sqlite3"
            self.run_alembic(database, "upgrade", "recipients_sender_001")
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    INSERT INTO accounts(id,institution,name,account_currency,created_at,updated_at)
                    VALUES(1,'Synthetic bank','Main','AED','2026-01-01','2026-01-01');
                    INSERT INTO cards(id,account_id,card_masked_number,card_type,name,created_at,updated_at)
                    VALUES(1,1,'****1111','credit','Card','2026-01-01','2026-01-01');
                    INSERT INTO transactions(id,card_id,amount,currency,description,transaction_kind,created_at,updated_at)
                    VALUES
                      (1,1,-10,'AED','One','purchase','2026-01-01','2026-01-01'),
                      (2,1,-10,'AED','Two','purchase','2026-01-01','2026-01-01');
                    INSERT INTO source_events(
                      id,source_type,transaction_datetime,raw_text,file_path,raw_hash,
                      parsed_amount,parsed_currency,parsed_description,parsed_card_number,
                      parsed_transaction_kind,account_id,card_id,parse_status,created_at,updated_at,sender
                    ) VALUES
                      (1,'sms_text','2026-01-01','Synthetic SMS',NULL,
                       'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                       -10,'AED','Merchant','1111','purchase',1,1,'parsed','2026-01-01','2026-01-01','Bank'),
                      (2,'pdf_statement','2026-01-01',NULL,'private.pdf',
                       'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                       NULL,NULL,NULL,NULL,NULL,1,1,'new','2026-01-01','2026-01-01',NULL),
                      (3,'sms_text','2026-01-01','Second synthetic SMS',NULL,
                       'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
                       -10,'AED','Second merchant','1111','purchase',1,1,'parsed','2026-01-01','2026-01-01','Bank');
                    INSERT INTO transaction_source_links(transaction_id,source_event_id,match_confidence,is_primary)
                    VALUES
                      (1,1,0.8,0),(2,1,0.9,1),(1,2,NULL,0),
                      (2,3,0.7,0),(1,3,0.6,0);
                    """
                )

            upgraded = self.run_alembic(database, "upgrade", "head")
            self.assertIn("discarded 1 links without observations", upgraded.stderr)
            self.assertIn("2 conflicting links", upgraded.stderr)
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM source_payloads").fetchone()[0], 3)
                self.assertEqual(connection.execute("SELECT count(*) FROM transaction_observations").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT count(*) FROM bank_statement_details").fetchone()[0], 1)
                self.assertEqual(
                    connection.execute(
                        "SELECT observation_id,transaction_id,match_method "
                        "FROM transaction_source_links ORDER BY observation_id"
                    ).fetchall(),
                    [(1, 2, "migration"), (3, 1, "migration")],
                )
                self.assertNotIn(
                    "source_events",
                    {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")},
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT timezone FROM accounts WHERE id=1"
                    ).fetchone()[0],
                    "UTC",
                )
                self.assertIsNone(
                    connection.execute(
                        "SELECT timezone FROM cards WHERE id=1"
                    ).fetchone()[0]
                )

            self.run_alembic(database, "downgrade", "recipients_sender_001")
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM source_events").fetchone()[0], 3)
                self.assertEqual(connection.execute("SELECT count(*) FROM transaction_source_links").fetchone()[0], 2)
                self.assertEqual(
                    connection.execute(
                        "SELECT transaction_id,source_event_id,is_primary "
                        "FROM transaction_source_links ORDER BY source_event_id"
                    ).fetchall(),
                    [(2, 1, 0), (1, 3, 0)],
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
