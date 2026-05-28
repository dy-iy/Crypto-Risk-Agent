from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.llm import call_llm_json
from app.agents.chat_agent.prompts import build_evidence_prompt
from app.agents.chat_agent.schemas import (
    EvidenceContract,
    EvidenceExtractionResult,
    EvidenceFieldResult,
    RiskCaseInput,
)


class _LLMEvidenceItem(BaseModel):
    scenario: str
    field: str
    value: Any = None
    status: str = "missing"
    evidence_text: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class _LLMEvidenceResponse(BaseModel):
    items: list[_LLMEvidenceItem] = Field(default_factory=list)


def _has_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term in text or term.lower() in lowered for term in terms)


def _context(text: str, terms: list[str], window: int = 60) -> str | None:
    lowered = text.lower()
    for term in terms:
        index = lowered.find(term.lower())
        if index >= 0:
            start = max(0, index - window)
            end = min(len(text), index + len(term) + window)
            return text[start:end]
    return None


def _amount_usd(text: str) -> float:
    patterns = [
        r"([0-9]+(?:\.[0-9]+)?)\s*(亿|万)?\s*(?:美元|美金|USD|USDT|USDC)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(million|billion)\s*(?:usd|dollars?)",
    ]
    values: list[float] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = float(match.group(1))
            unit = (match.group(2) or "").lower()
            if unit == "亿" or unit == "billion":
                value *= 100_000_000
            elif unit == "万":
                value *= 10_000
            elif unit == "million":
                value *= 1_000_000
            values.append(value)
    return max(values, default=0.0)


def _pct(text: str) -> float:
    values = []
    for match in re.finditer(r"([+-]?[0-9]+(?:\.[0-9]+)?)\s*%", text):
        values.append(abs(float(match.group(1))))
    return max(values, default=0.0)


def _field(
    scenario: str,
    field: str,
    value: Any,
    status: str,
    evidence_text: str | None,
    confidence: float = 0.65,
) -> EvidenceFieldResult:
    return EvidenceFieldResult(
        scenario=scenario,  # type: ignore[arg-type]
        field=field,
        value=value,
        status=status,  # type: ignore[arg-type]
        evidence_text=evidence_text,
        confidence=confidence,
    )


def _heuristic_item(text: str, scenario: str, field: str) -> EvidenceFieldResult:
    if scenario == "S1_ATTACK_EXPLOIT":
        attack_terms = ["遭受攻击", "遭攻击", "攻击事件", "漏洞攻击", "漏洞利用", "被盗", "黑客", "exploit", "hack"]
        research_terms = ["安全研究", "漏洞披露", "审计报告", "漏洞赏金", "白帽"]
        if field == "exploit_occurred" and _has_any(text, attack_terms):
            return _field(scenario, field, True, "confirmed", _context(text, attack_terms), 0.72)
        if field == "attack_vector" and _has_any(text, ["重入", "闪电贷", "预言机", "私钥", "社会工程", "未授权铸造"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["重入", "闪电贷", "预言机", "私钥", "社会工程", "未授权铸造"]), 0.64)
        if field == "loss_usd":
            amount = _amount_usd(text)
            if amount and _has_any(text, ["损失", "被盗", "盗取", "窃取", "转出", "stolen", "lost", "drained"]):
                return _field(scenario, field, amount, "confirmed", _context(text, ["损失", "被盗", "盗取", "窃取", "stolen", "lost"]), 0.7)
        if field == "user_fund_affected" and _has_any(text, ["用户资金", "用户资产", "资金池", "流动性池"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["用户资金", "用户资产", "资金池", "流动性池"]), 0.58)
        if field == "is_security_research_only" and _has_any(text, research_terms):
            return _field(scenario, field, True, "confirmed", _context(text, research_terms), 0.72)
        if field == "mitigation_status" and _has_any(text, ["已修复", "完成修复", "冻结", "已恢复", "未受影响", "无资金损失"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["已修复", "完成修复", "冻结", "已恢复", "未受影响", "无资金损失"]), 0.65)
        if field == "is_historical_event" and _has_any(text, ["此前", "曾经", "历史", "复盘"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["此前", "曾经", "历史", "复盘"]), 0.6)

    if scenario == "S2_EXCHANGE_ABNORMALITY":
        if field == "withdrawal_suspended" and _has_any(text, ["暂停提现", "停止提现", "提现暂停", "无法提现", "暂停提款", "无法提款"]):
            if _has_any(text, ["传闻", "网传", "未经证实", "尚未发布公告", "缺少官方"]) and not _has_any(
                text,
                ["官方公告", "公告称", "状态页", "交易所表示", "平台表示", "官方表示"],
            ):
                return _field(
                    scenario,
                    field,
                    True,
                    "uncertain",
                    _context(text, ["暂停提现", "停止提现", "提现暂停", "无法提现", "暂停提款", "无法提款"]),
                    0.42,
                )
            return _field(scenario, field, True, "confirmed", _context(text, ["暂停提现", "停止提现", "提现暂停", "无法提现", "暂停提款", "无法提款"]), 0.75)
        if field == "deposit_suspended" and _has_any(text, ["暂停充值", "充值暂停", "无法充值"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["暂停充值", "充值暂停", "无法充值"]), 0.7)
        if field == "trading_halted" and _has_any(text, ["暂停交易", "停止交易", "交易暂停", "无法交易", "撮合异常"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["暂停交易", "停止交易", "交易暂停", "无法交易", "撮合异常"]), 0.7)
        if field == "planned_maintenance" and _has_any(text, ["例行维护", "计划内维护", "系统升级", "常规维护", "钱包维护"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["例行维护", "计划内维护", "系统升级", "常规维护", "钱包维护"]), 0.7)
        if field == "recovery_time" and _has_any(text, ["预计恢复", "恢复时间", "将于", "小时后", "已恢复"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["预计恢复", "恢复时间", "将于", "小时后", "已恢复"]), 0.6)
        if field == "fund_safety_statement" and _has_any(text, ["用户资金安全", "资金安全", "不影响用户资产", "用户资金未受影响"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["用户资金安全", "资金安全", "不影响用户资产", "用户资金未受影响"]), 0.68)
        if field == "already_resolved" and _has_any(text, ["已恢复", "恢复正常", "已解决"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["已恢复", "恢复正常", "已解决"]), 0.68)

    if scenario == "S3_STABLECOIN_RESERVE":
        if field == "depeg_mentioned" and _has_any(text, ["脱锚", "depeg", "跌破1美元", "跌破 1 美元"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["脱锚", "depeg", "跌破1美元", "跌破 1 美元"]), 0.72)
        if field == "reserve_issue" and _has_any(text, ["储备不足", "储备危机", "储备透明度", "准备金不足"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["储备不足", "储备危机", "储备透明度", "准备金不足"]), 0.66)
        if field == "redemption_suspended" and _has_any(text, ["暂停赎回", "无法赎回", "赎回暂停"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["暂停赎回", "无法赎回", "赎回暂停"]), 0.68)

    if scenario == "S5_REGULATORY_ENFORCEMENT":
        if field == "regulator" and _has_any(text, ["SEC", "CFTC", "司法部", "法院", "监管机构", "FCA", "央行"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["SEC", "CFTC", "司法部", "法院", "监管机构", "FCA", "央行"]), 0.68)
        if field == "target_entity" and _has_any(text, ["交易平台", "交易所", "加密公司", "发行方", "项目方", "平台"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["交易平台", "交易所", "加密公司", "发行方", "项目方", "平台"]), 0.6)
        if field == "enforcement_action" and _has_any(text, ["起诉", "罚款", "禁令", "冻结", "逮捕", "查封", "制裁", "判刑", "指控"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["起诉", "罚款", "禁令", "冻结", "逮捕", "查封", "制裁", "判刑", "指控"]), 0.7)
        if field == "penalty_or_freeze" and _has_any(text, ["罚款", "冻结", "查封", "制裁"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["罚款", "冻结", "查封", "制裁"]), 0.7)
        if field == "lawsuit_or_charge" and _has_any(text, ["起诉", "诉讼", "指控"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["起诉", "诉讼", "指控"]), 0.7)
        if field == "is_policy_discussion_only" and _has_any(text, ["讨论", "草案", "征求意见", "咨询", "呼吁", "建议"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["讨论", "草案", "征求意见", "咨询", "呼吁", "建议"]), 0.68)
        if field == "is_positive_regulatory_clarity" and _has_any(text, ["驳回", "放行", "批准", "豁免", "不构成证券", "合法化"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["驳回", "放行", "批准", "豁免", "不构成证券", "合法化"]), 0.68)

    if scenario == "S4_INFRASTRUCTURE_FAILURE":
        if field == "network_outage" and _has_any(text, ["网络中断", "网络停止", "主网暂停", "网络故障", "停机", "宕机"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["网络中断", "网络停止", "主网暂停", "网络故障", "停机", "宕机"]), 0.7)
        if field == "block_production_stopped" and _has_any(text, ["停止出块", "出块停止", "停止区块生产", "区块停止"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["停止出块", "出块停止", "停止区块生产", "区块停止"]), 0.75)
        if field == "oracle_failure" and _has_any(text, ["预言机异常", "预言机故障", "价格预言机", "oracle failure"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["预言机异常", "预言机故障", "价格预言机", "oracle failure"]), 0.72)
        if field == "bridge_paused" and _has_any(text, ["跨链桥暂停", "桥暂停", "bridge paused", "暂停跨链"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["跨链桥暂停", "桥暂停", "bridge paused", "暂停跨链"]), 0.7)
        if field == "rpc_or_node_failure" and _has_any(text, ["RPC故障", "RPC 故障", "RPC 异常", "节点故障", "验证者离线", "节点掉线"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["RPC故障", "RPC 故障", "RPC 异常", "节点故障", "验证者离线", "节点掉线"]), 0.68)
        if field == "user_transactions_affected" and _has_any(text, ["交易无法确认", "交易失败", "用户交易受影响", "无法转账"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["交易无法确认", "交易失败", "用户交易受影响", "无法转账"]), 0.65)
        if field == "funds_at_risk" and _has_any(text, ["资金风险", "资产风险", "资金被锁", "资金无法提取"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["资金风险", "资产风险", "资金被锁", "资金无法提取"]), 0.62)
        if field == "already_resolved" and _has_any(text, ["已恢复", "恢复正常", "已修复", "已解决"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["已恢复", "恢复正常", "已修复", "已解决"]), 0.68)

    if scenario == "S7_FRAUD_GOVERNANCE":
        if field == "phishing_site" and _has_any(text, ["钓鱼网站", "钓鱼链接", "诈骗网站", "phishing", "恶意链接"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["钓鱼网站", "钓鱼链接", "诈骗网站", "phishing", "恶意链接"]), 0.76)
        if field == "fake_airdrop" and _has_any(text, ["假空投", "虚假空投", "空投骗局", "冒充空投", "空投虚假", "空投虚假的", "airdrop scam"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["假空投", "虚假空投", "空投骗局", "冒充空投", "空投虚假", "空投虚假的", "airdrop scam"]), 0.75)
        if field == "impersonation" and _has_any(text, ["冒充", "假冒", "仿冒", "伪装成", "impersonat"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["冒充", "假冒", "仿冒", "伪装成", "impersonat"]), 0.72)
        if field == "fake_token" and _has_any(text, ["假代币", "虚假代币", "空投虚假代币", "虚假的", "fake token", "仿盘代币"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["假代币", "虚假代币", "空投虚假代币", "虚假的", "fake token", "仿盘代币"]), 0.72)
        if field == "wallet_connection_lure" and _has_any(text, ["诱导用户连接钱包", "诱导用户连接", "连接钱包", "授权钱包", "钱包授权", "签名授权"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["诱导用户连接钱包", "诱导用户连接", "连接钱包", "授权钱包", "钱包授权", "签名授权"]), 0.7)
        if field == "user_loss_confirmed" and _has_any(text, ["用户损失", "受害者损失", "已被骗", "资产被盗", "盗取用户"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["用户损失", "受害者损失", "已被骗", "资产被盗", "盗取用户"]), 0.72)
        if field == "fraud_claim" and _has_any(text, ["诈骗", "骗局", "欺诈", "钓鱼", "scam", "fraud"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["诈骗", "骗局", "欺诈", "钓鱼", "scam", "fraud"]), 0.7)
        if field == "rug_pull_or_exit" and _has_any(text, ["跑路", "Rug Pull", "rug", "卷款", "退出骗局"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["跑路", "Rug Pull", "rug", "卷款", "退出骗局"]), 0.75)
        if field == "team_missing" and _has_any(text, ["团队失联", "项目方失联", "删除社交媒体", "官网无法访问"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["团队失联", "项目方失联", "删除社交媒体", "官网无法访问"]), 0.68)
        if field == "funds_removed" and _has_any(text, ["资金转走", "流动性移除", "资金池抽走", "卷走资金"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["资金转走", "流动性移除", "资金池抽走", "卷走资金"]), 0.7)
        if field == "official_response" and _has_any(text, ["官方提醒", "官方警告", "官方否认", "安全团队提醒"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["官方提醒", "官方警告", "官方否认", "安全团队提醒"]), 0.62)
        if field == "is_ordinary_team_change" and _has_any(text, ["普通人事调整", "正常离职", "组织调整", "团队变动"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["普通人事调整", "正常离职", "组织调整", "团队变动"]), 0.65)

    if scenario == "S8_WHALE_ONCHAIN_FLOW":
        if field == "large_transfer" and _has_any(text, ["巨鲸", "大额转账", "大额转移", "链上监测", "未知钱包", "whale"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["巨鲸", "大额转账", "大额转移", "链上监测", "未知钱包", "whale"]), 0.7)
        if field == "to_exchange" and _has_any(text, ["转入交易所", "流入交易所", "转至 Binance", "转至OKX", "to exchange"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["转入交易所", "流入交易所", "转至 Binance", "转至OKX", "to exchange"]), 0.72)
        if field == "from_exchange" and _has_any(text, ["转出交易所", "从交易所转出", "流出交易所", "from exchange"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["转出交易所", "从交易所转出", "流出交易所", "from exchange"]), 0.66)
        if field == "amount_usd":
            amount = _amount_usd(text)
            if amount:
                return _field(scenario, field, amount, "confirmed", _context(text, ["美元", "USDT", "USDC", "USD"]), 0.65)
        if field == "internal_transfer" and _has_any(text, ["内部调拨", "钱包归集", "冷钱包迁移", "热钱包迁移", "官方钱包迁移"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["内部调拨", "钱包归集", "冷钱包迁移", "热钱包迁移", "官方钱包迁移"]), 0.72)
        if field == "wallet_address" and re.search(r"0x[a-fA-F0-9]{40}|T[A-Za-z0-9]{33}|bc1[a-zA-Z0-9]{25,62}", text):
            return _field(scenario, field, True, "confirmed", _context(text, ["0x", "bc1"]), 0.65)
        if field == "sell_pressure_indicated" and _has_any(text, ["准备出售", "抛售", "卖出", "砸盘", "转入交易所准备卖出"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["准备出售", "抛售", "卖出", "砸盘", "转入交易所准备卖出"]), 0.68)

    if scenario == "S6_MARKET_LIQUIDATION":
        if field == "price_drop_pct":
            pct = _pct(text)
            if pct and _has_any(text, ["跌", "下跌", "暴跌", "闪崩", "回调", "跌破"]):
                return _field(scenario, field, pct, "confirmed", _context(text, ["跌", "下跌", "暴跌", "闪崩", "回调", "跌破"]), 0.64)
        if field == "liquidation_amount_usd":
            amount = _amount_usd(text)
            if amount and _has_any(text, ["爆仓", "清算", "liquidation", "强平"]):
                return _field(scenario, field, amount, "confirmed", _context(text, ["爆仓", "清算", "liquidation", "强平"]), 0.68)
        if field == "is_normal_market_commentary" and _has_any(text, ["行情日报", "每日行情", "技术分析", "支撑位", "阻力位"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["行情日报", "每日行情", "技术分析", "支撑位", "阻力位"]), 0.68)
        if field == "is_forecast_only" and _has_any(text, ["预测", "预计", "或将", "可能", "有望"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["预测", "预计", "或将", "可能", "有望"]), 0.62)
        if field == "liquidity_stress_mentioned" and _has_any(text, ["流动性枯竭", "流动性压力", "恐慌抛售"]):
            return _field(scenario, field, True, "confirmed", _context(text, ["流动性枯竭", "流动性压力", "恐慌抛售"]), 0.65)

    return EvidenceFieldResult(scenario=scenario, field=field, status="missing")  # type: ignore[arg-type]


def _fallback_items(case_input: RiskCaseInput, contracts: list[EvidenceContract]) -> list[EvidenceFieldResult]:
    text = case_input.raw_text
    return [
        _heuristic_item(text, contract.scenario, field)
        for contract in contracts
        for field in contract.fields
    ]


def _heuristic_result(
    case_input: RiskCaseInput,
    contracts: list[EvidenceContract],
    errors: list[str] | None = None,
    raw_llm_output: dict[str, Any] | None = None,
    llm_call_count: int = 1,
    json_parse_error_count: int = 0,
) -> EvidenceExtractionResult:
    items = _fallback_items(case_input, contracts)
    return EvidenceExtractionResult(
        items=items,
        missing_fields=[item.field for item in items if item.status == "missing"],
        extraction_errors=errors or [],
        raw_llm_output=raw_llm_output or {},
        extraction_mode="heuristic_fallback",
        llm_call_count=llm_call_count,
        fallback_count=1,
        json_parse_error_count=json_parse_error_count,
    )


def extract_evidence(case_input: RiskCaseInput, contracts: list[EvidenceContract]) -> EvidenceExtractionResult:
    if not contracts:
        return EvidenceExtractionResult(extraction_mode="fast_exit")

    raw_result = call_llm_json(build_evidence_prompt(case_input, contracts), temperature=0.0)
    if raw_result.get("_llm_error"):
        return _heuristic_result(
            case_input,
            contracts,
            errors=[str(raw_result["_llm_error"])],
            raw_llm_output=raw_result,
        )

    valid_scenarios = {contract.scenario for contract in contracts}
    valid_fields = {(contract.scenario, field) for contract in contracts for field in contract.fields}
    try:
        parsed = _LLMEvidenceResponse.model_validate(raw_result)
    except ValidationError as exc:
        return _heuristic_result(
            case_input,
            contracts,
            errors=[str(exc)],
            raw_llm_output=raw_result,
            json_parse_error_count=1,
        )

    normalized: list[EvidenceFieldResult] = []
    seen: set[tuple[str, str]] = set()
    errors: list[str] = []
    for item in parsed.items:
        scenario = item.scenario
        key = (scenario, item.field)
        if scenario not in valid_scenarios or key not in valid_fields:
            errors.append(f"ignored_unknown_field:{scenario}.{item.field}")
            continue
        status = item.status if item.status in {"confirmed", "denied", "missing", "uncertain", "not_applicable"} else "missing"
        evidence_text = item.evidence_text if status == "confirmed" else item.evidence_text
        if status == "confirmed" and not evidence_text:
            status = "uncertain"
        normalized.append(
            EvidenceFieldResult(
                scenario=scenario,  # type: ignore[arg-type]
                field=item.field,
                value=item.value,
                status=status,  # type: ignore[arg-type]
                evidence_text=evidence_text,
                confidence=item.confidence,
            )
        )
        seen.add(key)

    for contract in contracts:
        for field in contract.fields:
            if (contract.scenario, field) not in seen:
                normalized.append(EvidenceFieldResult(scenario=contract.scenario, field=field, status="missing"))

    return EvidenceExtractionResult(
        items=normalized,
        missing_fields=[item.field for item in normalized if item.status == "missing"],
        extraction_errors=errors,
        raw_llm_output=raw_result,
        extraction_mode="llm",
        llm_call_count=1,
        fallback_count=0,
        json_parse_error_count=0,
    )
