import hashlib
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from .models import TaskResponse
from app.attackpilot.utils.report_evidence import report_evidence


TX_HASH_RE = re.compile(r"(?<![0-9A-Za-z_])0x[a-fA-F0-9]{64}(?![a-fA-F0-9])")
FUNCTION_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*\(")
NOISE_FUNCTIONS = {
    "if",
    "for",
    "while",
    "require",
    "assert",
    "revert",
    "return",
    "emit",
    "address",
    "uint256",
    "balanceOf",
}

PATCH_KEYWORDS = ["patch", "fix", "mitigation", "补丁", "修复", "加固", "缓解"]
VERIFY_KEYWORDS = ["verify", "verification", "validation", "replay", "success", "failure", "验证", "校验", "回放", "成功", "失败"]
ROOT_CAUSE_KEYWORDS = ["root cause", "fault", "vulnerab", "faulty function", "漏洞", "根因", "故障", "缺陷"]


def _unique(values: List[str]) -> List[str]:
    return list(dict.fromkeys(values))


def _short_hash(value: str) -> str:
    return f"{value[:10]}...{value[-8:]}" if len(value) > 18 else value


def _extract_transactions(text: str) -> List[str]:
    return _unique([match.group(0).lower() for match in TX_HASH_RE.finditer(text or "")])


def _extract_functions(text: str) -> List[str]:
    functions = []
    for match in FUNCTION_RE.finditer(text or ""):
        name = match.group(1)
        if name in NOISE_FUNCTIONS or len(name) > 48:
            continue
        functions.append(name)
    return _unique(functions)[:24]


def _has_any(text: str, keywords: List[str]) -> bool:
    normalized = (text or "").lower()
    return any(keyword.lower() in normalized for keyword in keywords)


def _build_agent_signals(logs: List[Dict[str, Any]], task: TaskResponse) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for log in logs:
        agent = log.get("agent") or "Unknown"
        current = grouped.setdefault(agent, {"events": 0, "text": ""})
        current["events"] += 1
        current["text"] += "\n" + str(log.get("message") or "")
        current["text"] += "\n" + str(log.get("full_content") or "")

    signals = []
    for agent, payload in grouped.items():
        text = payload["text"]
        signals.append(
            {
                "agent": agent,
                "events": payload["events"],
                "transactions": _extract_transactions(text),
                "functions": _extract_functions(text),
                "mentions_patch": _has_any(text, PATCH_KEYWORDS),
                "mentions_verification": _has_any(text, VERIFY_KEYWORDS),
                "mentions_root_cause": _has_any(text, ROOT_CAUSE_KEYWORDS),
            }
        )

    if task.final_report:
        text = task.final_report
        signals.append(
            {
                "agent": "Final Report",
                "events": 1,
                "transactions": _extract_transactions(text),
                "functions": _extract_functions(text),
                "mentions_patch": _has_any(text, PATCH_KEYWORDS),
                "mentions_verification": _has_any(text, VERIFY_KEYWORDS),
                "mentions_root_cause": _has_any(text, ROOT_CAUSE_KEYWORDS),
            }
        )

    return signals


def _shared_values(signals: List[Dict[str, Any]], field: str) -> List[Dict[str, Any]]:
    mapping: Dict[str, Set[str]] = {}
    for signal in signals:
        for value in signal.get(field, []):
            mapping.setdefault(value, set()).add(signal["agent"])

    items = [
        {"value": value, "agents": sorted(list(agents))}
        for value, agents in mapping.items()
        if len(agents) >= 2
    ]
    return sorted(items, key=lambda item: (-len(item["agents"]), item["value"]))[:12]


def _contains_any_transaction(signals: List[Dict[str, Any]], agents: List[str], txs: List[str]) -> bool:
    normalized = {tx.lower() for tx in txs}
    return any(
        tx in normalized
        for signal in signals
        if signal["agent"] in agents
        for tx in signal.get("transactions", [])
    )


def _functions_for_agents(signals: List[Dict[str, Any]], agents: List[str]) -> List[str]:
    values = []
    for signal in signals:
        if signal["agent"] in agents:
            values.extend(signal.get("functions", []))
    return _unique(values)


def _make_check(
    check_id: str,
    title: str,
    description: str,
    score: int,
    evidence: List[str],
    recommendation: Optional[str] = None,
) -> Dict[str, Any]:
    if score >= 75:
        status = "pass"
    elif score >= 45:
        status = "warning"
    else:
        status = "risk"
    return {
        "id": check_id,
        "title": title,
        "description": description,
        "status": status,
        "score": score,
        "evidence": evidence,
        "recommendation": recommendation,
    }


def build_automated_review(
    task: TaskResponse,
    logs: List[Dict[str, Any]],
    macro: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if task.status != "completed" or not (task.final_report or "").strip():
        return {
            "task_id": task.task_id, "dapp_name": task.dapp_name,
            "generated_at": datetime.now().isoformat(),
            "review_type": "deterministic_cross_agent_consistency",
            "status": "unavailable", "score": None, "checks": [],
            "agent_signals": [], "shared_transactions": [], "shared_functions": [],
            "next_actions": ["分析尚未完成或未生成有效报告，无法评估结论一致性。"],
            "llm_review_agent_used": False,
        }
    agent_signals = _build_agent_signals(logs, task)
    result = task.result if isinstance(task.result, dict) else {}
    verification = result.get('verification')
    verification = verification if isinstance(verification, dict) else {}
    machine = report_evidence({'verification': verification, 'verdict': verification.get('judge_verdict')},
                              result.get('replay_evidence'))
    patches = result.get('applied_patches')
    verified = (not task.is_demo and machine['evidence_trusted']
                and isinstance(patches, str)
                and hashlib.sha256(patches.encode()).hexdigest() == verification.get('applied_patch_sha256'))
    baseline = result.get('baseline_validation')
    known = set(baseline.get('transactions', {})) if isinstance(baseline, dict) and isinstance(baseline.get('transactions'), dict) else set()
    if isinstance(macro, dict):
        for key in ('transaction_hash_list', 'transactions_need_analyze', 'attack_transactions', 'auxiliary_transactions'):
            items = macro.get(key)
            if isinstance(items, list):
                known.update(item for item in items if isinstance(item, str))
    known = {value.lower() for value in known if TX_HASH_RE.fullmatch(value)}
    # A repeated bytes32 value or report repeating itself is not independent
    # transaction evidence. Keep only known input hashes and distinct stages.
    stages = [signal for signal in agent_signals if signal['agent'] != 'Final Report']
    shared_transactions = [item for item in _shared_values(stages, "transactions") if item['value'] in known]
    shared_functions = _shared_values(agent_signals, "functions")

    debug_targets = []
    attack_transactions = []
    if macro:
        debug_targets = macro.get("transactions_need_analyze") or macro.get("attack_transactions") or []
        attack_transactions = macro.get("attack_transactions") or []

    debug_agents = ["Transaction Debugger", "GlobalMemory Administrator"]
    patch_agents = ["Code Patcher", "Transaction Judge"]
    root_agents = ["TxFaultAgent", "Task Organizer", "Transaction Debugger", "GlobalMemory Administrator"]

    if debug_targets:
        covered_count = sum(
            1 for tx in debug_targets if _contains_any_transaction(agent_signals, debug_agents, [tx])
        )
        macro_tx_covered = covered_count > 0
        macro_score = round(covered_count / len(debug_targets) * 100)
        macro_evidence = [
            f"{len(debug_targets)} macro debug target(s): "
            + ", ".join(_short_hash(tx) for tx in debug_targets[:4]),
            "Trace/debug stage references at least one macro target."
            if macro_tx_covered
            else "No macro target was found in Trace/debug outputs.",
        ]
    else:
        macro_tx_covered = bool(shared_transactions)
        macro_score = 70 if macro_tx_covered else 35
        macro_evidence = ["No macro debug target is available; fallback uses shared transaction mentions."]

    root_functions = _functions_for_agents(agent_signals, root_agents)
    patch_functions = _functions_for_agents(agent_signals, patch_agents)
    overlapping_functions = [name for name in root_functions if name in patch_functions]

    root_cause_agents = [signal["agent"] for signal in stages if signal.get("mentions_root_cause")]

    checks = [
        _make_check(
            "macro-to-debug",
            "Macro transaction selection -> Trace debugging",
            "Checks whether macro-selected attack/debug target transactions are reused by Trace Debugger or final report.",
            macro_score,
            macro_evidence,
            None if macro_tx_covered else "Require Trace Debugger and final report to cite macro-selected attack transactions.",
        ),
        _make_check(
            "attack-classification-overlap",
            "Attack transaction agreement",
            "Checks whether multiple agents cite the same attack transaction instead of drifting to unrelated transactions.",
            88 if len(shared_transactions) >= 2 else 62 if len(shared_transactions) == 1 else 35 if attack_transactions else 50,
            [
                f"{_short_hash(item['value'])} shared by {', '.join(item['agents'])}"
                for item in shared_transactions[:4]
            ]
            or ["No transaction hash is shared by two or more agents."],
            None if shared_transactions else "Promote transaction hashes into structured outputs for cross-agent agreement.",
        ),
        _make_check(
            "root-to-patch",
            "Root cause function -> Patch continuity",
            "Checks whether functions mentioned by localization/debugging are also referenced by patch or verification outputs.",
            88 if len(overlapping_functions) >= 2 else 68 if len(overlapping_functions) == 1 else 42 if root_functions and patch_functions else 25,
            [f"{name} appears in both localization/debug and patch stages." for name in overlapping_functions[:6]]
            or [
                f"Root/debug functions: {', '.join(root_functions[:6])}" if root_functions else "No root/debug function candidates extracted.",
                f"Patch functions: {', '.join(patch_functions[:6])}" if patch_functions else "No patch-stage function candidates extracted.",
            ],
            None if overlapping_functions else "Require patch reports to cite the same faulty functions and trace indices found by debugging.",
        ),
        _make_check(
            "verification-loop",
            "Patch verification loop",
            "Uses validated paired replay evidence bound to the applied patch; text mentions cannot establish verification.",
            100 if verified else 25,
            [
                "Recorded trigger interception is verified; normal business regression remains untested."
                if verified else "No trusted patch interception result is available.",
                f"Verification status: {machine['verification'].get('status', 'not_run')}",
            ],
            None if verified else "Resolve the recorded verification blocker or missing evidence before claiming patch effectiveness.",
        ),
        _make_check(
            "root-cause-quorum",
            "Root cause quorum",
            "Checks whether root-cause language appears across multiple agents instead of only in the final report.",
            90 if len(root_cause_agents) >= 3 else 68 if len(root_cause_agents) == 2 else 42 if len(root_cause_agents) == 1 else 20,
            [f"Root-cause signals found in: {', '.join(root_cause_agents)}"] if root_cause_agents else ["No root-cause signal detected."],
            None if len(root_cause_agents) >= 2 else "Ask major stages to emit a structured root-cause field.",
        ),
    ]

    score = round(sum(check["score"] for check in checks) / len(checks))
    if not verified:
        score = min(score, 74)
    if score >= 75:
        status = "pass"
    elif score >= 45:
        status = "warning"
    else:
        status = "risk"

    return {
        "task_id": task.task_id,
        "dapp_name": task.dapp_name,
        "generated_at": datetime.now().isoformat(),
        "review_type": "deterministic_cross_agent_consistency",
        "score_scope": "text_reference_coverage_only",
        "evidence_boundary": "文字交叉引用与结构化回放核验分别检查；分数不能证明根因正确、交易安全或正常功能通过。",
        "status": status,
        "score": score,
        "checks": checks,
        "agent_signals": agent_signals,
        "shared_transactions": shared_transactions,
        "shared_functions": shared_functions,
        "next_actions": [
            check["recommendation"]
            for check in checks
            if check.get("recommendation") and check["status"] != "pass"
        ],
        "llm_review_agent_used": False,
    }
