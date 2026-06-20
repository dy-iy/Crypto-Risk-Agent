from __future__ import annotations

import unittest

from app.agents.chat_agent.core.decision import decide_from_branches
from app.agents.chat_agent.tools.risk_scanner import scan_fast_signals


class RiskScannerIllicitFundsTest(unittest.TestCase):
    def test_negated_security_event_does_not_score_as_hack_risk(self) -> None:
        text = "该协议没有安全事件，没有漏洞利用，没有资金损失，仅发布产品更新。"

        scan = scan_fast_signals(text)

        self.assertEqual(scan.raw_rule_scores["score_hack"], 0.0)
        self.assertTrue(scan.fast_exit_allowed)
        self.assertFalse(scan.debug["high_risk_route"]["triggered"])

    def test_illicit_fund_flow_gets_high_risk_floor(self) -> None:
        text = (
            "据 ChainCatcher 报道，链上监测显示，一批疑似黑客或钓鱼活动相关资金"
            "近期持续买入门罗币（XMR），累计购入规模约 2,300 万美元，"
            "并对市场价格产生明显影响。"
        )

        scan = scan_fast_signals(text)
        floor_signals = scan.debug.get("high_risk_floor_signals", [])
        floor_types = {item.get("risk_type") for item in floor_signals if isinstance(item, dict)}

        self.assertFalse(scan.fast_exit_allowed)
        self.assertIn("score_hack", floor_types)
        self.assertIn("score_whale", floor_types)
        self.assertGreaterEqual(scan.raw_rule_scores["score_whale"], 0.61)

        decision = decide_from_branches(scan)
        self.assertGreaterEqual(decision.risk_score, 65)
        self.assertIn("high_risk_floor_signal", decision.reason_codes)


if __name__ == "__main__":
    unittest.main()
