RISK_CATEGORIES = [
    "链上漏洞 / 攻击风险",
    "诈骗 / 跑路 / Rug Pull 风险",
    "监管与法律风险",
    "交易所与系统运维风险",
    "稳定币异常风险",
    "爆仓 / 清算风险",
    "大额转账 / 巨鲸行为风险",
    "异常行情波动风险",
    "项目治理 / 团队异常风险",
    "偿付能力 / 储备 / 流动性风险",
    "基础设施 / 协议层异常风险",
    "宏观 / 政策冲击风险",
]


def build_classify_prompt(cleaned_text: str, risk_signals: list[str]) -> str:
    categories = "\n".join(f"- {category}" for category in RISK_CATEGORIES)
    return f"""
你是加密货币金融风控分类 Agent。

只能从以下固定风险类别中选择，不允许创造新类别：
{categories}

用户文本：
{cleaned_text}

已识别风险信号：
{risk_signals}

请返回 JSON：
{{
  "risk_categories": ["固定风险类别"],
  "reason": "分类理由"
}}
""".strip()
