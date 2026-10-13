from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from settings import PROJECT_PATH


KNOWLEDGE_ROOT = Path(PROJECT_PATH) / "data" / "knowledge"
GENERATED_REPORTS_PATH = KNOWLEDGE_ROOT / "generated_reports.json"
MAX_CONTENT_CHARS = 6000
_write_lock = threading.Lock()


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _extract_report_summary(report: str, max_chars: int = MAX_CONTENT_CHARS) -> str:
    text = (report or "").strip()
    if not text:
        return ""

    sections = []
    current_title = ""
    current_lines: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines)))
            current_title = line.lstrip("#").strip()
            current_lines = []
            continue
        current_lines.append(line)
    if current_lines:
        sections.append((current_title, "\n".join(current_lines)))

    priority_keywords = [
        "root cause",
        "vulnerability",
        "attack",
        "exploit",
        "patch",
        "verification",
        "根因",
        "漏洞",
        "攻击",
        "补丁",
        "验证",
    ]
    picked = []
    for title, body in sections:
        haystack = f"{title}\n{body}".lower()
        if any(keyword.lower() in haystack for keyword in priority_keywords):
            picked.append(f"{title}\n{body}" if title else body)
        if len("\n\n".join(picked)) >= max_chars:
            break

    summary = "\n\n".join(picked) if picked else text
    return summary[:max_chars].rstrip()


def _extract_tags(dapp_name: str, report: str, result: Dict[str, Any] | None) -> List[str]:
    tags = {dapp_name}
    lower = report.lower()
    keyword_tags = {
        "oracle": ["oracle", "price", "预言机", "价格"],
        "reentrancy": ["reentrancy", "重入"],
        "access_control": ["access control", "owner", "permission", "权限"],
        "flash_loan": ["flash loan", "flashloan", "闪电贷"],
        "delegatecall": ["delegatecall", "storage collision", "存储"],
        "accounting": ["share", "accounting", "rounding", "会计", "舍入"],
        "patch_verified": ["verified", "补丁", "验证"],
    }
    for tag, keywords in keyword_tags.items():
        if any(keyword in lower for keyword in keywords):
            tags.add(tag)

    enabled_modules = None
    if isinstance(result, dict):
        enabled_modules = result.get("enabled_modules")
    if isinstance(enabled_modules, list):
        tags.update(str(item) for item in enabled_modules if item)

    return sorted(tag for tag in tags if tag)


def _load_payload() -> Dict[str, Any]:
    if not GENERATED_REPORTS_PATH.exists():
        return {"items": []}
    try:
        payload = json.loads(GENERATED_REPORTS_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            return payload
    except Exception:
        pass
    return {"items": []}


def persist_generated_report_knowledge(task) -> bool:
    report = getattr(task, "final_report", None)
    if not isinstance(report, str) or not report.strip():
        return False

    task_id = str(getattr(task, "task_id", "") or "")
    dapp_name = str(getattr(task, "dapp_name", "") or "AttackPilot case")
    result = getattr(task, "result", None)
    result_dict = result if isinstance(result, dict) else None
    completed_at = getattr(task, "completed_at", None)
    completed_at_text = completed_at.isoformat() if hasattr(completed_at, "isoformat") else None
    content = _extract_report_summary(report)
    if not content:
        return False

    item = {
        "id": f"task:{task_id}",
        "source": "platform_report",
        "title": f"{dapp_name} 攻击复盘报告",
        "content": content,
        "tags": _extract_tags(dapp_name, report, result_dict),
        "metadata": {
            "task_id": task_id,
            "dapp_name": dapp_name,
            "completed_at": completed_at_text,
            "duration": getattr(task, "duration", None),
            "status": str(getattr(task, "status", "") or ""),
            "summary": _normalize_space(content[:360]),
        },
    }

    with _write_lock:
        KNOWLEDGE_ROOT.mkdir(parents=True, exist_ok=True)
        payload = _load_payload()
        items = [entry for entry in payload.get("items", []) if isinstance(entry, dict) and entry.get("id") != item["id"]]
        items.insert(0, item)
        payload = {
            "updated_at": datetime.now().isoformat(),
            "source": "AttackPilot completed reports",
            "items": items[:200],
        }
        GENERATED_REPORTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        from app.services.rag_service import get_rag_service

        get_rag_service().rebuild()
    except Exception as exc:
        print(f"[GeneratedReportKnowledge] Saved report but failed to rebuild RAG index: {exc}")

    return True
