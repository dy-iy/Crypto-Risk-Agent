from __future__ import annotations

import unittest

from app.api.sim import _resolve_account_id
from app.services.sim_engine import DEFAULT_SIM_ACCOUNT_ID, INITIAL_CASH, sim_engine


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
            _resolve_account_id(None, " browser client / 1 "),
            "guest:browser_client___1",
        )

    def test_sim_api_falls_back_to_demo_without_user_or_client_id(self) -> None:
        self.assertEqual(_resolve_account_id(None, None), DEFAULT_SIM_ACCOUNT_ID)


if __name__ == "__main__":
    unittest.main()
