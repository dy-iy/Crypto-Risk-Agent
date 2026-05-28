from __future__ import annotations

import hashlib
import re

from app.agents.chat_agent.schemas import RiskCaseInput
from app.tools.chat_tools import prepare_chat_input


def _detect_language(text: str) -> str:
    return "zh" if re.search(r"[\u4e00-\u9fff]", text or "") else "en"


def normalize_input(message: str) -> RiskCaseInput:
    raw_text = str(message or "").strip()
    cleaned_text = " ".join(raw_text.split())
    state = prepare_chat_input({"original_text": raw_text, "raw_agent_outputs": {}})
    case_id = hashlib.sha256(cleaned_text.encode("utf-8")).hexdigest()[:16]

    return RiskCaseInput(
        case_id=case_id,
        raw_text=raw_text,
        content=cleaned_text,
        language=_detect_language(cleaned_text),
        input_type=state.get("input_type", "unknown"),
        source_name=state.get("source_hint", ""),
        entities=state.get("entities", {}),
        keyword_refs=state.get("keyword_refs", []),
        metadata={"parsed_input": state.get("parsed_input", {})},
    )
