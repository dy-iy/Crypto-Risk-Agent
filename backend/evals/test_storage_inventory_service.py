from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.services import (
    analysis_report_service,
    auth_service,
    daily_report_store,
    portfolio_watchlist_store,
    storage_inventory_service,
    task_audit_service,
)
from app.services.storage_inventory_service import (
    build_backup_manifest,
    build_storage_inventory,
    prune_invalid_json_backups,
)


class StorageInventoryServiceTest(unittest.TestCase):
    def test_storage_inventory_counts_runtime_datastores_without_creating_missing_dbs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            auth_db = root / "auth.sqlite3"
            report_db = root / "analysis_reports.sqlite3"
            portfolio_db = root / "portfolio.sqlite3"
            audit_db = root / "task_audit.sqlite3"
            daily_dir = root / "daily_reports"

            with closing(sqlite3.connect(auth_db)) as conn:
                conn.execute("CREATE TABLE users(id TEXT)")
                conn.execute("CREATE TABLE sessions(token TEXT)")
                conn.execute("CREATE TABLE favorites(id TEXT)")
                conn.execute("INSERT INTO users VALUES ('user-1')")
                conn.execute("INSERT INTO sessions VALUES ('session-1')")
                conn.commit()
            with closing(sqlite3.connect(report_db)) as conn:
                conn.execute("CREATE TABLE analysis_reports(id TEXT)")
                conn.execute("INSERT INTO analysis_reports VALUES ('report-1')")
                conn.commit()
            with closing(sqlite3.connect(portfolio_db)) as conn:
                conn.execute("CREATE TABLE portfolio_watchlist(id TEXT)")
                conn.execute("CREATE TABLE portfolio_metadata(key TEXT)")
                conn.execute("INSERT INTO portfolio_watchlist VALUES ('watch-1')")
                conn.commit()
            user_dir = daily_dir / "user-1"
            user_dir.mkdir(parents=True)
            (user_dir / "index.json").write_text(json.dumps({"reports": [{"report_id": "daily-1"}]}), encoding="utf-8")
            (user_dir / "daily-1.json").write_text(json.dumps({"headline": "风险日报"}), encoding="utf-8")

            with patch.object(auth_service, "AUTH_DB_PATH", auth_db), patch.object(
                analysis_report_service, "REPORT_DB_PATH", report_db
            ), patch.object(portfolio_watchlist_store, "PORTFOLIO_DB_PATH", portfolio_db), patch.object(
                task_audit_service, "TASK_AUDIT_DB_PATH", audit_db
            ), patch.object(daily_report_store, "DAILY_REPORTS_DIR", daily_dir), patch.object(
                storage_inventory_service.sim_engine, "account_count", return_value=2
            ):
                inventory = build_storage_inventory()

            stores = {item["name"]: item for item in inventory["datastores"]}
            self.assertEqual(stores["auth"]["tables"]["users"], 1)
            self.assertEqual(stores["auth"]["tables"]["sessions"], 1)
            self.assertEqual(stores["analysis_reports"]["tables"]["analysis_reports"], 1)
            self.assertEqual(stores["portfolio"]["tables"]["portfolio_watchlist"], 1)
            self.assertFalse(stores["task_audit"]["exists"])
            self.assertFalse(audit_db.exists())
            self.assertEqual(stores["daily_reports"]["user_dirs"], 1)
            self.assertEqual(stores["daily_reports"]["report_files"], 1)
            self.assertEqual(inventory["runtime"]["sim_accounts"], 2)
            self.assertEqual(inventory["sqlite_errors"], [])

    def test_backup_manifest_lists_existing_runtime_targets_and_sqlite_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            auth_db = root / "auth.sqlite3"
            report_db = root / "analysis_reports.sqlite3"
            portfolio_db = root / "portfolio.sqlite3"
            audit_db = root / "task_audit.sqlite3"
            daily_dir = root / "daily_reports"
            invalid_backup = root / "update_jobs.json.invalid.20260606T000000000000Z.bak"
            auth_db.write_bytes(b"auth-db")
            Path(f"{auth_db}-wal").write_bytes(b"wal")
            report_db.write_bytes(b"report-db")
            user_dir = daily_dir / "user-1"
            user_dir.mkdir(parents=True)
            (user_dir / "index.json").write_text(json.dumps({"reports": []}), encoding="utf-8")
            (root / "update_jobs.json").write_text(json.dumps({"job_id": "job-1"}), encoding="utf-8")
            invalid_backup.write_text("{broken", encoding="utf-8")

            with patch.object(auth_service, "AUTH_DB_PATH", auth_db), patch.object(
                analysis_report_service, "REPORT_DB_PATH", report_db
            ), patch.object(portfolio_watchlist_store, "PORTFOLIO_DB_PATH", portfolio_db), patch.object(
                task_audit_service, "TASK_AUDIT_DB_PATH", audit_db
            ), patch.object(daily_report_store, "DAILY_REPORTS_DIR", daily_dir), patch.object(
                storage_inventory_service, "DATA_DIR", root
            ):
                manifest = build_backup_manifest()
                inventory = build_storage_inventory()

            items = {item["name"]: item for item in manifest["items"]}
            stores = {item["name"]: item for item in inventory["datastores"]}
            self.assertTrue(items["auth"]["exists"])
            self.assertTrue(items["auth-wal"]["exists"])
            self.assertTrue(items["daily_reports:user-1/index.json"]["exists"])
            self.assertTrue(items["update_jobs.json"]["exists"])
            self.assertTrue(items[f"invalid_json_backup:{invalid_backup.name}"]["exists"])
            self.assertEqual(stores["invalid_json_backups"]["file_count"], 1)
            self.assertEqual(inventory["runtime"]["invalid_json_backups"], 1)
            self.assertFalse(portfolio_db.exists())
            self.assertGreaterEqual(manifest["target_count"], 4)
            self.assertTrue(any("WAL/SHM" in warning for warning in manifest["warnings"]))
            self.assertTrue(any("损坏隔离备份" in warning for warning in manifest["warnings"]))
            missing_names = {item["name"] for item in manifest["missing_expected_targets"]}
            self.assertIn("portfolio", missing_names)

    def test_prune_invalid_json_backups_removes_only_expired_invalid_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            old_backup = root / "update_jobs.json.invalid.20250101T000000000000Z.bak"
            fresh_backup = root / "sim_accounts.json.invalid.29990101T000000000000Z.bak"
            ordinary_backup = root / "manual.bak"
            old_backup.write_text("{old", encoding="utf-8")
            fresh_backup.write_text("{fresh", encoding="utf-8")
            ordinary_backup.write_text("manual", encoding="utf-8")
            old_time = (datetime.now(timezone.utc) - timedelta(days=60)).timestamp()
            fresh_time = datetime.now(timezone.utc).timestamp()
            os.utime(old_backup, (old_time, old_time))
            os.utime(fresh_backup, (fresh_time, fresh_time))
            os.utime(ordinary_backup, (old_time, old_time))

            with patch.object(storage_inventory_service, "DATA_DIR", root):
                result = prune_invalid_json_backups(retention_days=30)
                inventory = build_storage_inventory()

            self.assertEqual(result["deleted_files"], 1)
            self.assertFalse(old_backup.exists())
            self.assertTrue(fresh_backup.exists())
            self.assertTrue(ordinary_backup.exists())
            self.assertEqual(result["remaining_files"], 1)
            self.assertEqual(inventory["runtime"]["invalid_json_backups"], 1)


if __name__ == "__main__":
    unittest.main()
