"""Import locally reviewed translations without sending reports to any provider.

Usage: python -m evals.import_attackpilot_translations /path/to/translations
Each TASK_ID.zh-CN.md must have a corresponding TASK_ID.md source export.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

from app.attackpilot import settings, store
from app.attackpilot.report_translation import LANGUAGE, PROTECTED


def import_translations(directory: Path) -> list[dict]:
    prepared = []
    for translated_path in sorted(directory.glob("*.zh-CN.md")):
        task_id = translated_path.name.removesuffix(".zh-CN.md")
        original_path = directory / f"{task_id}.md"
        task = store.get_task(task_id)
        if not task or not original_path.is_file():
            raise ValueError(f"Missing task or source export: {task_id}")
        original = original_path.read_text(encoding="utf-8")
        translated = translated_path.read_text(encoding="utf-8")
        if original != task.get("final_report"):
            raise ValueError(f"Source changed since export: {task_id}")
        if not re.search(r"[\u3400-\u9fff]", translated):
            raise ValueError(f"Translation contains no Chinese text: {task_id}")
        source_evidence = Counter(PROTECTED.findall(original))
        translated_evidence = Counter(PROTECTED.findall(translated))
        if source_evidence != translated_evidence:
            raise ValueError(f"Evidence counts changed: {task_id}; missing={dict(source_evidence-translated_evidence)!r}; extra={dict(translated_evidence-source_evidence)!r}")
        prepared.append({
            "task_id": task_id, "source_hash": hashlib.sha256(original.encode("utf-8")).hexdigest(),
            "language": LANGUAGE, "translated_report": translated,
            "model": "assistant-translation", "translated_at": store.now(), "public": task["is_demo"],
        })
    with store.connection() as db:
        for item in prepared:
            current = db.execute("SELECT final_report FROM tasks WHERE task_id=?", (item["task_id"],)).fetchone()
            if not current or hashlib.sha256((current["final_report"] or "").encode("utf-8")).hexdigest() != item["source_hash"]:
                raise ValueError(f"Source changed during import: {item['task_id']}")
            db.execute(
                "INSERT INTO report_translations(task_id,source_hash,language,translated_report,model,translated_at) VALUES (:task_id,:source_hash,:language,:translated_report,:model,:translated_at) "
                "ON CONFLICT(task_id,source_hash,language) DO UPDATE SET translated_report=excluded.translated_report,model=excluded.model,translated_at=excluded.translated_at",
                item,
            )
    return [{key: value for key, value in item.items() if key != "translated_report"} for item in prepared]


def write_public_bundle(destination: Path) -> int:
    """Only immutable public examples can be packaged for another deployment."""
    with store.connection() as db:
        rows = db.execute(
            "SELECT report_translations.*,tasks.final_report FROM report_translations JOIN tasks USING(task_id) "
            "WHERE tasks.is_demo=1 AND tasks.source='archive' AND report_translations.language='zh-CN' ORDER BY report_translations.task_id"
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        original = item.pop("final_report") or ""
        if hashlib.sha256(original.encode("utf-8")).hexdigest() == item["source_hash"]:
            items.append(item)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps({"schema_version": 1, "items": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return len(items)


if __name__ == "__main__":
    print(json.dumps(import_translations(Path(sys.argv[1])), ensure_ascii=False, indent=2))
    if "--bundle-public" in sys.argv[2:]:
        count = write_public_bundle(settings.PACKAGE_ROOT / "data/report-translations.zh-CN.json")
        print(f"Packaged {count} public report translations; private derivatives remain in the runtime database.")
