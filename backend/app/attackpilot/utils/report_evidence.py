"""Render report status and applied code from recorded evidence, not model prose."""
import copy
import json
import re

from app.attackpilot.utils.verification import VERIFICATION_POLICY_VERSION, replay_evidence_digest


def _replay_coverage(value):
    if (not isinstance(value, dict)
            or value.get("mode") != "independent_historical_transaction_pairs"
            or value.get("sequence_replay_verified") is not False):
        return None
    addresses = value.get("modified_addresses")
    if (not isinstance(addresses, list) or not addresses
            or any(not isinstance(address, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", address)
                   for address in addresses)):
        return None
    groups = [value.get(key) for key in (
        "intercepted_transaction_hashes", "unaffected_transaction_hashes", "unresolved_transaction_hashes",
    )]
    if any(not isinstance(group, list) or any(
            not isinstance(tx_hash, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", tx_hash)
            for tx_hash in group) for group in groups):
        return None
    hashes = [tx_hash.lower() for group in groups for tx_hash in group]
    if len(set(hashes)) != len(hashes):
        return None
    return {"intercepted": len(groups[0]), "unaffected": len(groups[1]), "unresolved": len(groups[2])}


def report_evidence(judge_result, replay_logs):
    result = judge_result if isinstance(judge_result, dict) else {}
    state = result.get("verification")
    state = copy.deepcopy(state) if isinstance(state, dict) else {}
    # Free-form reasoning may originate with the judge model; keep it outside
    # the machine-authoritative status envelope and rendered summary.
    state.pop("reason", None)
    dimensions = state.get("dimensions")
    dimensions = dimensions if isinstance(dimensions, dict) else {}
    coverage = _replay_coverage(state.get("coverage"))
    valid_coverage = (coverage is not None and coverage["intercepted"] > 0
                      and coverage["unresolved"] == 0)
    structured = (isinstance(replay_logs, dict)
                  and type(replay_logs.get("schema_version")) is int
                  and replay_logs["schema_version"] == 1)
    digest = replay_evidence_digest(replay_logs) if structured else None
    trusted = (
        structured and type(state.get("schema_version")) is int and state["schema_version"] == 2
        and type(state.get("evidence_version")) is int and state["evidence_version"] == 1
        and type(state.get("verification_policy_version")) is int
        and state["verification_policy_version"] == VERIFICATION_POLICY_VERSION
        and state.get("evidence_validated") is True
        and state.get("scope") == "attack_path_only"
        and valid_coverage
        and digest is not None and state.get("replay_evidence_sha256") == digest
        and state.get("applied_patch_sha256") == replay_logs.get("applied_patch_sha256")
    )
    attack = dimensions.get("attack_interception", {})
    verified = (
        trusted and isinstance(attack, dict) and attack.get("status") == "passed"
        and state.get("status") == "verified" and state.get("replay_completed") is True
        and result.get("verdict") == "VERIFIED" and state.get("judge_verdict") == "VERIFIED"
    )
    # This evidence protocol records independent attack transactions only.
    # There is no normal-business sample or complete profit measurement in it;
    # arbitrary dimension fields cannot supply either missing experiment.
    trusted = verified
    dimensions = {
        "attack_interception": {"status": "passed" if verified else "unavailable"},
        "normal_regression": {"status": "not_run"},
        "profit": {"status": "unavailable", "usd": None},
    }
    status = state.get("status", "unverified")
    if (status == "verified" and not verified) or (status == "failed" and not trusted):
        status = "unverified"
        state["reason_code"] = "replay_evidence_invalid"
    state["evidence_validated"] = bool(trusted)
    labels = {
        "failed": "攻击回放未通过", "blocked": "无法验证", "error": "验证异常",
        "skipped": "未执行回放", "not_run": "尚未执行回放", "unverified": "尚未确认",
    }
    state.update(status=status, dimensions=dimensions)
    return {
        "verification": state,
        "label": ("触发交易拦截通过" if coverage else "攻击路径回放通过") if verified
        else labels.get(status, "尚未确认"),
        "structured_evidence_available": structured,
        "evidence_trusted": bool(trusted),
        "replay_evidence": copy.deepcopy(replay_logs) if structured else None,
        "legacy_replay_diagnostics": replay_logs if isinstance(replay_logs, str) else None,
        "judge_interpretation": {
            "authority": "model_interpretation_only",
            "verdict": result.get("verdict"),
            "reason": result.get("reason"),
            "analysis_details": result.get("analysis_details"),
        },
    }


def _cell(value):
    return str(value).replace("\n", " ").replace("|", "\\|").replace("`", "'")


def render_verification_summary(evidence):
    state = evidence["verification"]
    dimensions = state["dimensions"]
    coverage = _replay_coverage(state.get("coverage"))
    replay_not_run = state.get("replay_attempted") is False and state.get("replay_completed") is False
    labels = {"passed": "通过", "failed": "未通过", "unavailable": "证据不足", "not_run": "未执行"}

    def dimension(name):
        item = dimensions.get(name)
        return labels.get(item.get("status"), "证据不足") if isinstance(item, dict) else "证据不足"

    profit = dimensions.get("profit", {})
    amount = profit.get("usd") if isinstance(profit, dict) else None
    profit_text = f"{amount} USD" if amount is not None else "未知（缺失数据不按 0 计算）"
    rows = [
        ("执行阶段 / 状态", f"{state.get('stage', 'unknown')} / {state.get('status', 'unverified')}"),
        ("原因代码", state.get("reason_code", "evidence_missing")),
        ("结构化证据校验", "通过" if evidence["evidence_trusted"] else "未执行回放" if replay_not_run else "未确认"),
        ("验证范围", ("记录中触发交易的拦截（attack_path_only）" if coverage
                     else "记录中的攻击路径（attack_path_only）")
         if evidence["evidence_trusted"] else "缺少已校验范围"),
        ("触发交易拦截" if coverage else "攻击路径拦截", "未执行" if replay_not_run else dimension("attack_interception")),
        ("正常功能回归", dimension("normal_regression")),
        ("回放收益估值", profit_text),
    ]
    stop_reasons = {
        "no_attack_evidence": "初步分类未筛出攻击候选，后续根因调查与补丁回放已跳过。",
        "no_attack_hypothesis": "调查未形成可验证的攻击假设，未生成或回放补丁。",
    }
    if coverage:
        rows[5:5] = [
            ("独立历史回放覆盖", f"拦截证据 {coverage['intercepted']} 笔；未触及修改代码 {coverage['unaffected']} 笔；未确认 {coverage['unresolved']} 笔"),
            ("整条攻击链顺序回放", "未验证（各笔独立回放不传递状态）"),
        ]
    if state.get("reason_code") in stop_reasons:
        rows.insert(2, ("停止原因", stop_reasons[state["reason_code"]]))
    table = "\n".join(f"| {_cell(name)} | {_cell(value)} |" for name, value in rows)
    boundary = (
        f"已确认拦截 {coverage['intercepted']} 笔触发交易；另有 {coverage['unaffected']} 笔独立历史回放未触及修改代码。"
        "各笔回放不传递状态，不能据此确认整条攻击链或正常功能通过。"
        if coverage and evidence["evidence_trusted"] and state.get("status") == "verified" else
        "验证结论仅覆盖记录中的链、交易和攻击路径。未执行的正常功能回归、目标链执行及单项补丁效果均不能据此认定通过。"
    )
    return (
        f"## 补丁验证状态：{evidence['label']}\n\n"
        "| 检查项 | 记录结果 |\n|---|---|\n" + table + "\n\n"
        + boundary
    )


def sanitize_report_body(value):
    """Model prose cannot supply the report's authoritative patch code section."""
    if not isinstance(value, str):
        return "报告正文生成结果不可用；请以执行状态和实际补丁记录为准。"
    lines = []
    fence = None
    fenced_lines = []
    trace_fence = False
    replacement = False
    reserved_section = None
    for line in value.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence is not None:
            fenced_lines.append(line)
            if marker:
                current = marker.group(1)
                closes = (current[0] == fence[0] and len(current) >= len(fence)
                          and not line.strip()[len(current):].strip())
            else:
                closes = False
            if closes:
                body = "\n".join(fenced_lines[1:-1])
                patch_code = re.search(
                    r"^\s*(?:<<<<<<<\s*SEARCH|>>>>>>>\s*REPLACE|=======\s*$|#\s*File:|"
                    r"diff --git\b|---\s+(?:a/|/dev/null)|\+\+\+\s+(?:b/|/dev/null)|@@|"
                    r"[+-]?\s*(?:(?:function|contract|library|interface)\s+\w+|"
                    r"pragma\s+solidity\b|(?:require|assert|revert)\s*\(|assembly\s*\{))",
                    body, re.MULTILINE,
                )
                if trace_fence and patch_code is None and reserved_section is None and not replacement:
                    lines.extend(fenced_lines)
                fence = None
                fenced_lines = []
            continue
        if marker:
            fence = marker.group(1)
            info = line.strip()[len(fence):].strip().lower().split()
            trace_fence = bool(info) and info[0] in {"text", "plaintext", "mermaid"}
            fenced_lines = [line]
            continue
        heading = re.match(r"^\s*(#{1,6})\s+(.+)$", line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2)
            if re.search(r"applied\s+patches|补丁验证状态|verification\s+status", title, re.IGNORECASE):
                reserved_section = level
                continue
            if reserved_section is not None and level <= reserved_section:
                reserved_section = None
        if reserved_section is not None:
            continue
        if re.match(r"^\s*<<<<<<< SEARCH\s*$", line):
            replacement = True
            continue
        if replacement:
            if re.match(r"^\s*>>>>>>> REPLACE\s*$", line):
                replacement = False
            continue
        if re.match(r"^\s*#\s*File:\s*", line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def render_applied_patches(patches):
    text = patches.strip() if isinstance(patches, str) else ""
    if not text or text.startswith(("No finalized patch", "No patch generated", "No applicable patch")):
        return "## Applied Patches（实际应用补丁）\n\n没有可确认的已应用补丁记录。"
    longest = max((len(match) for match in re.findall(r"`{3,}", text)), default=2)
    fence = "`" * max(3, longest + 1)
    return (
        "## Applied Patches（实际应用补丁）\n\n"
        "以下代码直接来自本次实际应用记录。应用记录不代表每项改动均被本次回放触发，也不代表正常功能已通过回归。\n\n"
        f"{fence}diff\n{text}\n{fence}"
    )


def render_recorded_analysis(hypothesis, memory):
    """Keep collected analysis deliverable when only the final prose call fails.

    This is a presentation fallback, never a replacement for missing analysis or
    replay. Require the same hypothesis fields the coordinator collected and
    original transaction identities; an empty model response alone is no report.
    """
    if not isinstance(hypothesis, dict) or not isinstance(memory, dict):
        return None
    fault = hypothesis.get("fault_report")
    trace = hypothesis.get("final_trace")
    fix = hypothesis.get("fix_report")
    transactions = memory.get("transactions_need_analyze")
    if (not isinstance(fault, str) or not fault.strip()
            or not isinstance(trace, str) or not trace.strip()
            or not isinstance(fix, (str, dict)) or not fix
            or not isinstance(transactions, list) or not transactions
            or any(not isinstance(tx, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", tx)
                   for tx in transactions)):
        return None
    fault = sanitize_report_body(fault)
    if not fault:
        return None

    def recorded_block(text):
        longest = max((len(marker) for marker in re.findall(r"`{3,}", text)), default=2)
        fence = "`" * max(3, longest + 1)
        return f"{fence}text\n{text}\n{fence}"

    fix_text = json.dumps(fix, ensure_ascii=False, indent=2) if isinstance(fix, dict) else fix
    return "\n\n".join((
        "## 已记录的复盘分析\n\n文字整理服务未返回可用正文，以下根据本次已记录资料生成。"
        "根因与修复建议仍属于分析假设；回放是否通过、实际修改及未完成项目以上方结构化结果和下方补丁记录为准。",
        "### 调查交易\n\n" + "\n".join(f"- `{tx}`" for tx in dict.fromkeys(transactions)),
        "### 已记录的根因假设（待证据复核）\n\n" + fault,
        "### 调查结束时的调用轨迹\n\n" + recorded_block(trace),
        "### 已记录的修复建议（不代表实际应用）\n\n" + recorded_block(fix_text),
    ))
