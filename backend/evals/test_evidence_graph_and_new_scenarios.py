from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.agents.chat_agent import run_chat_agent


class EvidenceGraphAndNewScenariosTest(unittest.TestCase):
    def _run_offline(self, text: str) -> dict[str, object]:
        with patch.dict(os.environ, {"CRYPTO_RISK_AGENT_OFFLINE": "1"}):
            return run_chat_agent(text)

    def test_evidence_graph_and_decision_trace_are_reported(self) -> None:
        report = self._run_offline(
            "某 DeFi 协议遭受闪电贷攻击，攻击者利用漏洞盗取约 1200 万美元资产，团队正在追踪攻击者地址。"
        )

        self.assertTrue(report.get("evidence_graph"))
        self.assertTrue(report.get("scenario_assessments"))
        self.assertTrue(report.get("decision_trace"))
        self.assertEqual(report["decision_trace"]["final_score"], report["risk_score"])

    def test_planned_maintenance_has_counter_evidence_and_is_not_high_risk(self) -> None:
        report = self._run_offline(
            "Binance 将进行计划内钱包维护，期间暂停部分网络充值提现，预计 2 小时后恢复，用户资金安全。"
        )

        self.assertLessEqual(int(report["risk_score"]), 45)
        self.assertTrue(report.get("counter_evidence"))
        meanings = " ".join(str(item.get("meaning", "")) for item in report["counter_evidence"])
        self.assertIn("计划维护", meanings)

    def test_low_risk_security_context_uses_general_category(self) -> None:
        report = self._run_offline(
            "安全研究团队发布漏洞披露报告，未造成资金损失，用户资金未受影响。"
        )

        self.assertLessEqual(int(report["risk_score"]), 20)
        self.assertEqual(report["primary_category"], "综合风险")
        self.assertEqual(report["risk_categories"], ["综合风险"])

    def test_token_issuance_anomaly_gets_new_scenario(self) -> None:
        report = self._run_offline(
            "某协议合约漏洞导致攻击者未授权铸造价值 800 万美元代币并转入 DEX 抛售，供应量异常增加。"
        )

        self.assertEqual(report["chat_agent_result"]["primary_scenario"], "S9_TOKEN_ISSUANCE_ANOMALY")
        self.assertGreaterEqual(int(report["risk_score"]), 76)

    def test_bridge_attack_gets_new_scenario(self) -> None:
        report = self._run_offline(
            "某跨链桥被攻击，攻击者利用桥合约漏洞转出约 3000 万美元跨链资产，官方已暂停桥接合约。"
        )

        self.assertEqual(report["chat_agent_result"]["primary_scenario"], "S10_BRIDGE_CROSS_CHAIN_RISK")
        self.assertGreaterEqual(int(report["risk_score"]), 76)


if __name__ == "__main__":
    unittest.main()
