from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.services import sim_engine as sim_engine_module
from app.services.sim_account_service import resolve_sim_account_id
from app.services.sim_engine import DEFAULT_SIM_ACCOUNT_ID, INITIAL_CASH, SimEngine, sim_engine


class SimAccountIsolationTest(unittest.TestCase):
    def test_sim_engine_wallets_are_isolated_by_account_id(self) -> None:
        account_a = "test-sim-isolation-a"
        account_b = "test-sim-isolation-b"

        sim_engine.reset(account_a)
        sim_engine.reset(account_b)
        sim_engine.buy("BTCUSDT", 1000, account_a)
        sim_engine.next(account_a)

        state_a = sim_engine.state(account_a)
        state_b = sim_engine.state(account_b)

        self.assertEqual(state_a["current_index"], 1)
        self.assertLess(state_a["cash"], INITIAL_CASH)
        self.assertTrue(state_a["positions"])
        self.assertTrue(state_a["trade_history"])

        self.assertEqual(state_b["current_index"], 0)
        self.assertEqual(state_b["cash"], INITIAL_CASH)
        self.assertEqual(state_b["positions"], [])
        self.assertEqual(state_b["trade_history"], [])

    def test_sim_api_uses_guest_client_id_when_not_logged_in(self) -> None:
        self.assertEqual(
            resolve_sim_account_id(None, " browser client / 1 "),
            "guest:browser_client___1",
        )

    def test_sim_api_falls_back_to_demo_without_user_or_client_id(self) -> None:
        self.assertEqual(resolve_sim_account_id(None, None), DEFAULT_SIM_ACCOUNT_ID)

    def test_sim_engine_persists_accounts_across_engine_instances(self) -> None:
        account_id = "test-sim-persisted-user"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sim_accounts.json"
            with patch.object(sim_engine_module, "SIM_ACCOUNTS_PATH", path):
                first_engine = SimEngine()
                first_engine.reset(account_id)
                first_engine.buy("ETH", 500, account_id)
                first_engine.next(account_id)

                restored_engine = SimEngine()
                restored = restored_engine.state(account_id)

        self.assertEqual(restored["current_index"], 1)
        self.assertLess(restored["cash"], INITIAL_CASH)
        self.assertEqual(restored["positions"][0]["symbol"], "ETHUSDT")
        self.assertEqual(restored["trade_history"][0]["side"], "BUY")

    def test_sim_engine_quarantines_corrupt_account_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sim_accounts.json"
            path.write_text("{broken", encoding="utf-8")
            with patch.object(sim_engine_module, "SIM_ACCOUNTS_PATH", path):
                engine = SimEngine()
                self.assertEqual(engine.account_count(), 0)
                self.assertFalse(path.exists())
                backups = list(path.parent.glob("sim_accounts.json.invalid.*.bak"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(encoding="utf-8"), "{broken")

                state = engine.state("user-restored")
                persisted = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(state["cash"], INITIAL_CASH)
        self.assertIn("user-restored", persisted["accounts"])

    def test_sim_engine_prunes_only_expired_guest_accounts(self) -> None:
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sim_accounts.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "accounts": {
                            "guest:old": {
                                "current_index": 0,
                                "cash": INITIAL_CASH,
                                "positions": {},
                                "trade_history": [],
                                "updated_at": (now - timedelta(days=30)).isoformat(),
                            },
                            "guest:new": {
                                "current_index": 0,
                                "cash": INITIAL_CASH,
                                "positions": {},
                                "trade_history": [],
                                "updated_at": now.isoformat(),
                            },
                            "user-1": {
                                "current_index": 0,
                                "cash": INITIAL_CASH,
                                "positions": {},
                                "trade_history": [],
                                "updated_at": (now - timedelta(days=300)).isoformat(),
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(sim_engine_module, "SIM_ACCOUNTS_PATH", path):
                engine = SimEngine()
                result = engine.prune_guest_accounts(retention_days=14)
                persisted = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(result["deleted_accounts"], 1)
        self.assertEqual(result["remaining_accounts"], 2)
        self.assertNotIn("guest:old", persisted["accounts"])
        self.assertIn("guest:new", persisted["accounts"])
        self.assertIn("user-1", persisted["accounts"])


if __name__ == "__main__":
    unittest.main()
