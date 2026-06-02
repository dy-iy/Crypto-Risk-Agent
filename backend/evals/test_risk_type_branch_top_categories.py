from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from app.agents.chat_agent.core.report import build_report
from app.agents.chat_agent.llm_agents.risk_type_branch_agent import (
    MAX_PARALLEL_RISK_BRANCHES,
    analyze_risk_type_branches,
)
from app.agents.chat_agent.schemas import DecisionResult, OrchestrationDecision, RiskCaseInput, RiskCaseResult
from app.agents.chat_agent.tools.risk_scanner import RISK_NAME_MAP, RISK_TYPE_ORDER, scan_fast_signals


def _mock_branch_response(prompt: str, **_: object) -> dict[str, object]:
    risk_type_match = re.search(r'"risk_type":\s*"([^"]+)"', prompt)
    score_match = re.search(r'"rule_score_100":\s*(\d+)', prompt)
    risk_type = risk_type_match.group(1) if risk_type_match else "score_hack"
    rule_score = int(score_match.group(1)) if score_match else 0
    established = rule_score >= 45
    return {
        "risk_type": risk_type,
        "established": established,
        "severity_score": rule_score if established else min(rule_score, 20),
        "evidence_strength": 70 if established else 20,
        "confidence": 0.75 if established else 0.35,
        "evidence_summary": [f"{RISK_NAME_MAP[risk_type]}分支完成审核"],
        "missing_evidence": [] if established else ["未发现该类别的直接证据"],
        "field_evidence": [],
        "reasoning": "分支审核完成",
    }


class RiskTypeBranchTopCategoriesTest(unittest.TestCase):
    def test_deep_analysis_selects_top_3_from_12_risk_categories(self) -> None:
        case_input = RiskCaseInput(
            case_id="test-case",
            raw_text="某交易所暂停提现，社群反馈无法提款，同时链上监测到巨鲸向交易所转入大额资产。",
            content="某交易所暂停提现，社群反馈无法提款，同时链上监测到巨鲸向交易所转入大额资产。",
        )
        signal_scan = scan_fast_signals(case_input.content)

        with patch(
            "app.agents.chat_agent.llm_agents.risk_type_branch_agent.call_llm_json",
            side_effect=_mock_branch_response,
        ) as mock_call:
            updated_scan, evidence, branches = analyze_risk_type_branches(case_input, signal_scan)

        expected_types = [
            risk_type
            for risk_type in RISK_TYPE_ORDER
            if float(signal_scan.raw_rule_scores.get(risk_type, 0.0)) > 0
        ]
        expected_types = sorted(
            expected_types,
            key=lambda risk_type: (
                risk_type in set(signal_scan.debug["high_risk_route"]["triggered_types"]),
                float(signal_scan.raw_rule_scores.get(risk_type, 0.0)),
                -RISK_TYPE_ORDER.index(risk_type),
            ),
            reverse=True,
        )[:MAX_PARALLEL_RISK_BRANCHES]

        self.assertLessEqual(len(branches), MAX_PARALLEL_RISK_BRANCHES)
        self.assertGreaterEqual(len(RISK_TYPE_ORDER), 12)
        self.assertEqual(mock_call.call_count, len(expected_types))
        self.assertEqual([branch["risk_type"] for branch in branches], expected_types)
        self.assertEqual(evidence.llm_call_count, len(expected_types))
        self.assertEqual(updated_scan.debug["risk_type_branch_candidates"]["available_risk_types"], RISK_TYPE_ORDER)
        self.assertEqual(updated_scan.debug["risk_type_branch_candidates"]["selected_risk_types"], expected_types)

        result = RiskCaseResult(
            case_input=case_input,
            signal_scan=updated_scan,
            orchestration=OrchestrationDecision(path="deep_analysis"),
            evidence=evidence,
            decision=DecisionResult(
                risk_score=61,
                pre_cap_score=61,
                risk_level="中高风险",
                risk_status="potential_risk",
                primary_scenario="S2_EXCHANGE_ABNORMALITY",
                confidence=0.75,
                reason_codes=["risk_type_branch_merge"],
            ),
        )
        report = build_report(result)
        reported_categories = {item["risk_category"] for item in report["evidence"]}
        evidence_explanations = [item["explanation"] for item in report["evidence"]]

        self.assertEqual(len(report["chat_agent_result"]["risk_type_branches"]), len(expected_types))
        self.assertEqual(reported_categories, {RISK_NAME_MAP[risk_type] for risk_type in expected_types})
        self.assertTrue(all("score_" not in item and "branch_score" not in item for item in evidence_explanations))
        self.assertTrue(all("风险类型：" in item and "分支评分：" in item for item in evidence_explanations))

    def test_low_risk_gate_handoff_type_is_forced_into_branch_analysis(self) -> None:
        case_input = RiskCaseInput(
            case_id="low-risk-gate-handoff",
            raw_text="某交易员以50倍杠杆做空HYPE，预计短期回调。",
            content="某交易员以50倍杠杆做空HYPE，预计短期回调。",
        )
        base_scan = scan_fast_signals(case_input.content)
        signal_scan = base_scan.model_copy(
            update={
                "raw_rule_scores": {
                    **base_scan.raw_rule_scores,
                    "score_volatility": 0.35,
                },
                "debug": {
                    **base_scan.debug,
                    "low_risk_gate_handoff": {
                        "risk_types": ["score_volatility"],
                        "source": "low_risk_gate",
                        "reason": "门控识别到异常行情波动风险",
                    },
                    "high_risk_route": {
                        **base_scan.debug["high_risk_route"],
                        "triggered": True,
                        "triggered_types": ["score_volatility"],
                    },
                },
            }
        )

        with patch(
            "app.agents.chat_agent.llm_agents.risk_type_branch_agent.call_llm_json",
            side_effect=_mock_branch_response,
        ):
            updated_scan, _, branches = analyze_risk_type_branches(case_input, signal_scan)

        self.assertGreaterEqual(len(branches), 1)
        self.assertEqual(branches[0]["risk_type"], "score_volatility")
        self.assertEqual(
            updated_scan.debug["risk_type_branch_candidates"]["handoff_risk_types"],
            ["score_volatility"],
        )


if __name__ == "__main__":
    unittest.main()
