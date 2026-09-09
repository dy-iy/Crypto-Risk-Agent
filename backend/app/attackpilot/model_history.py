"""Trim only complete tool exchanges and preserve DeepSeek reasoning fields."""
import copy
import json

def tool_history(messages: list[dict], budget: int, count_tokens) -> list[dict]:
    messages = copy.deepcopy(messages)
    system = [message for message in messages if message.get("role") == "system"]
    body = [message for message in messages if message.get("role") != "system"]
    groups = []
    index = 0
    while index < len(body):
        message = body[index]
        if message.get("role") == "tool":
            index += 1
            continue
        group = [message]
        if message.get("tool_calls"):
            expected = {call["id"] for call in message["tool_calls"]}
            received = set()
            while index + 1 < len(body) and body[index + 1].get("role") == "tool":
                index += 1
                response = body[index]
                if response.get("tool_call_id") in expected:
                    group.append(response); received.add(response["tool_call_id"])
            if received != expected:
                index += 1
                continue
        groups.append(group)
        index += 1
    used = count_tokens(json.dumps(system, ensure_ascii=False))
    kept = []
    for group in reversed(groups):
        cost = count_tokens(json.dumps(group, ensure_ascii=False))
        if used + cost > budget:
            break
        kept[0:0] = group
        used += cost
    if not kept:
        raise ValueError("工具对话超过上下文预算，请缩小分析范围")
    return system + kept
