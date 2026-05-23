from __future__ import annotations

import re

from app.services.data_loader import shorten


RISK_RULES = [
    {
        "risk_type": "链上漏洞 / 攻击风险",
        "keywords": ["攻击", "漏洞", "被盗", "黑客", "exploit", "hack", "hacker", "attack", "flash loan"],
        "base": 86,
    },
    {
        "risk_type": "诈骗 / 跑路 / Rug Pull 风险",
        "keywords": ["诈骗", "跑路", "rug", "rug pull", "钓鱼", "骗局", "欺诈"],
        "base": 88,
    },
    {
        "risk_type": "监管与法律风险",
        "keywords": ["监管", "起诉", "调查", "罚款", "SEC", "诉讼", "合规", "制裁"],
        "base": 78,
    },
    {
        "risk_type": "交易所与系统运维风险",
        "keywords": ["交易所", "暂停提现", "无法提现", "宕机", "系统维护", "钱包维护", "下架"],
        "base": 82,
    },
    {
        "risk_type": "稳定币异常风险",
        "keywords": ["稳定币", "脱锚", "USDT", "USDC", "depeg", "赎回", "储备"],
        "base": 78,
    },
    {
        "risk_type": "爆仓 / 清算风险",
        "keywords": ["爆仓", "清算", "liquidation", "杠杆", "保证金", "空头挤压"],
        "base": 72,
    },
    {
        "risk_type": "大额转账 / 巨鲸行为风险",
        "keywords": ["巨鲸", "大额转账", "转入", "转出", "沉睡地址", "whale", "链上监测"],
        "base": 68,
    },
    {
        "risk_type": "异常行情波动风险",
        "keywords": ["暴跌", "暴涨", "闪崩", "波动", "下跌", "上涨", "价格", "跌至", "高点"],
        "base": 58,
    },
    {
        "risk_type": "项目治理 / 团队异常风险",
        "keywords": ["团队", "创始人", "治理", "DAO", "离职", "失联", "内讧"],
        "base": 62,
    },
    {
        "risk_type": "偿付能力 / 储备 / 流动性风险",
        "keywords": ["储备", "流动性", "挤兑", "资不抵债", "偿付", "流动性池"],
        "base": 76,
    },
    {
        "risk_type": "基础设施 / 协议层异常风险",
        "keywords": ["节点", "预言机", "跨链桥", "协议", "网络拥堵", "主网", "停机"],
        "base": 70,
    },
    {
        "risk_type": "宏观 / 政策冲击风险",
        "keywords": ["政策", "加息", "宏观", "关税", "禁令", "美联储"],
        "base": 60,
    },
]


def parse_score(value: object, risk_level: str = "") -> int | None:
    if value is not None and value != "":
        try:
            return max(0, min(100, int(float(value))))
        except (TypeError, ValueError):
            pass

    if risk_level == "高风险":
        return 85
    if risk_level == "中风险":
        return 60
    if risk_level == "低风险":
        return 30
    if risk_level == "无明显风险":
        return 10
    return None


def risk_level_from_score(score: int | float) -> str:
    if score >= 80:
        return "高风险"
    if score >= 50:
        return "中风险"
    return "低风险"


def sentence_with_keyword(text: str, keywords: list[str]) -> str:
    sentences = re.split(r"(?<=[。！？.!?])\s+|\n+", text)
    lowered_keywords = [keyword.lower() for keyword in keywords]
    for sentence in sentences:
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in lowered_keywords):
            return shorten(sentence, 150)
    return shorten(text, 150)


def rule_risk_scorer(title: str, content: str, risk_level: str = "") -> dict[str, object]:
    text = f"{title or ''}\n{content or ''}"
    lowered = text.lower()
    best_type = "异常行情波动风险"
    best_score = 28
    best_keywords: list[str] = []

    for rule in RISK_RULES:
        keywords = [str(keyword) for keyword in rule["keywords"]]
        hit_count = sum(1 for keyword in keywords if keyword.lower() in lowered)
        if hit_count:
            score = int(rule["base"]) + min(hit_count - 1, 4) * 4
            if score > best_score:
                best_score = score
                best_type = str(rule["risk_type"])
                best_keywords = keywords

    level_score = parse_score("", risk_level)
    if level_score is not None:
        best_score = max(best_score, level_score)

    score = max(0, min(100, best_score))
    evidence = (
        sentence_with_keyword(text, best_keywords)
        if best_keywords
        else shorten(text, 150)
    )
    return {
        "risk_score": score,
        "risk_level": risk_level_from_score(score),
        "risk_type": best_type,
        "evidence": evidence,
        "summary": shorten(f"{best_type}：{evidence}", 130),
    }
