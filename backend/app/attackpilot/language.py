"""Output language policy shared by transaction analysis and the report viewer."""

CHINESE_OUTPUT_RULES = """\n\n【输出语言】
面向用户的分析、解释、风险结论、最终报告（包括 fault_report、fix_report）、标题和小节使用简体中文。
保留原有输出格式以及所有 JSON 字段名、枚举值、工具名称和参数协议；仅翻译自然语言字段值。
交易哈希、合约地址、函数名、变量名、代码、引用编号、金额、数量、币种符号和 URL 必须保持原样。
不要因为使用中文而省略证据、改变不确定性或补造事实。"""


def chinese_messages(messages):
    """Copy messages so repeated calls do not append rules to stored history."""
    copied = [dict(item) if isinstance(item, dict) else item for item in messages]
    for item in copied:
        if isinstance(item, dict) and item.get("role") == "system" and isinstance(item.get("content"), str):
            if CHINESE_OUTPUT_RULES not in item["content"]:
                item["content"] += CHINESE_OUTPUT_RULES
            break
    else:
        copied.insert(0, {"role": "system", "content": CHINESE_OUTPUT_RULES.strip()})
    return copied
