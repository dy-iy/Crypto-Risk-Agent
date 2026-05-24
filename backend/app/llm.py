import json
import os
import re
from pathlib import Path
from collections.abc import AsyncIterator

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI


load_dotenv(Path(__file__).resolve().parent / ".env")

DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")


def _extract_json(text: str) -> dict[str, object]:
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        parsed = json.loads(cleaned[start : end + 1])
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    return {"_raw_text": text}


def call_llm_json(prompt: str, temperature: float = 0.2) -> dict[str, object]:
    if os.getenv("CRYPTO_RISK_AGENT_OFFLINE") == "1":
        return {"_llm_error": "LLM disabled by CRYPTO_RISK_AGENT_OFFLINE"}

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return {"_llm_error": "DEEPSEEK_API_KEY is not configured"}

    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=float(os.getenv("DEEPSEEK_TIMEOUT", "30")),
    )

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "你是严格输出 JSON 的加密货币金融风控助手。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
        )
        content = response.choices[0].message.content or "{}"
        return _extract_json(content)
    except Exception as exc:  # API failures should not crash the MVP demo path.
        return {"_llm_error": str(exc)}


def call_llm_text(
    prompt: str,
    system_prompt: str = "你是专业、谨慎的加密货币金融风控助手。",
    temperature: float = 0.3,
) -> str:
    if os.getenv("CRYPTO_RISK_AGENT_OFFLINE") == "1":
        return "LLM disabled by CRYPTO_RISK_AGENT_OFFLINE"

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return "DEEPSEEK_API_KEY is not configured"

    client = OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=float(os.getenv("DEEPSEEK_TIMEOUT", "30")),
    )

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        return f"DeepSeek request failed: {exc}"


async def call_llm_json_async(prompt: str, temperature: float = 0.2) -> dict[str, object]:
    if os.getenv("CRYPTO_RISK_AGENT_OFFLINE") == "1":
        return {"_llm_error": "LLM disabled by CRYPTO_RISK_AGENT_OFFLINE"}

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return {"_llm_error": "DEEPSEEK_API_KEY is not configured"}

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=float(os.getenv("DEEPSEEK_TIMEOUT", "30")),
    )

    try:
        response = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "你是严格输出 JSON 的加密货币金融风控助手。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
        )
        content = response.choices[0].message.content or "{}"
        return _extract_json(content)
    except Exception as exc:
        return {"_llm_error": str(exc)}
    finally:
        await client.close()


async def stream_llm_text(
    prompt: str,
    system_prompt: str = "你是专业、谨慎的加密货币金融风控助手。",
    temperature: float = 0.3,
) -> AsyncIterator[str]:
    if os.getenv("CRYPTO_RISK_AGENT_OFFLINE") == "1":
        yield "LLM disabled by CRYPTO_RISK_AGENT_OFFLINE"
        return

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        yield "DEEPSEEK_API_KEY is not configured"
        return

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        timeout=float(os.getenv("DEEPSEEK_TIMEOUT", "30")),
    )

    try:
        stream = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
    except Exception as exc:
        yield f"DeepSeek request failed: {exc}"
    finally:
        await client.close()
