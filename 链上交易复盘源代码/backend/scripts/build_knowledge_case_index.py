import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = PROJECT_ROOT / "dataset" / "raw"
KNOWLEDGE_ROOT = PROJECT_ROOT / "data" / "knowledge"
OUTPUT_PATH = KNOWLEDGE_ROOT / "case_index.generated.json"


KEYWORD_RULES = [
    (
        "reentrancy",
        [
            "reentrancy",
            "reentrant",
            "callback",
            "fallback",
        ],
    ),
    (
        "oracle_manipulation",
        [
            "oracle",
            "price manipulation",
            "manipulate",
            "bad price",
            "sandwich",
            "slippage",
        ],
    ),
    (
        "precision_rounding",
        [
            "precision",
            "rounding",
            "rounding error",
            "unit mismatch",
            "calculation",
            "decimal",
            "10000",
            "1000",
        ],
    ),
    (
        "accounting_drift",
        [
            "inflation",
            "donation",
            "exchange rate",
            "exchangerate",
            "share",
            "healthfactor",
            "reserve",
            "rewarddebt",
            "token duplication",
            "burn",
        ],
    ),
    (
        "access_control",
        [
            "access control",
            "incorrect access",
            "lack of access",
            "arbitrary external call",
            "unchecked external call",
            "unverified external call",
            "signature",
            "initialize",
            "storage collision",
            "malicious proposal",
            "owner",
            "permission",
        ],
    ),
    (
        "signature_replay",
        [
            "signature replay",
            "incorrect signature",
            "signature verification",
            "nonce",
            "permit",
        ],
    ),
    (
        "flash_loan_amplifier",
        [
            "flashloan",
            "flash loan",
        ],
    ),
    (
        "business_logic",
        [
            "business logic",
            "logic bug",
            "logic flaw",
            "lack of inspection",
            "lack of input validation",
            "insufficient validation",
            "contract vulnerability",
            "malicious code logic",
            "phishing",
            "arbitrage",
            "emergencywithdraw",
            "claim",
            "flow",
        ],
    ),
]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def classify(raw):
    text_parts = [
        raw.get("cause"),
        raw.get("root_cause"),
        raw.get("report"),
        raw.get("name"),
    ]
    text = " ".join(str(part or "") for part in text_parts).lower()
    normalized_text = text.replace("-", " ").replace("_", " ")

    matched = []
    matched_rules = {}
    for type_id, keywords in KEYWORD_RULES:
        hits = [
            keyword
            for keyword in keywords
            if keyword in text or keyword.replace("-", " ") in normalized_text
        ]
        if hits:
            matched.append(type_id)
            matched_rules[type_id] = hits

    if not matched:
        matched = ["business_logic"]
        matched_rules["business_logic"] = ["fallback_default"]

    return matched, matched_rules


def build_item(path: Path):
    raw = load_json(path)
    type_ids, matched_rules = classify(raw)
    tx_hashes = raw.get("transaction_hash") or []
    if not isinstance(tx_hashes, list):
        tx_hashes = []

    return {
        "case_id": f"raw_{path.stem.lower().replace(' ', '_').replace('(', '').replace(')', '').replace('-', '_')}",
        "name": raw.get("name") or path.stem,
        "dataset_file": path.relative_to(PROJECT_ROOT).as_posix(),
        "vulnerability_type_ids": type_ids,
        "raw_cause": raw.get("cause"),
        "platform": raw.get("platform"),
        "time": raw.get("time"),
        "loss": raw.get("lost"),
        "root_cause": raw.get("root_cause"),
        "transaction_count": len(tx_hashes),
        "transaction_hashes": [str(tx_hash) for tx_hash in tx_hashes],
        "report_link": raw.get("report_link") or raw.get("link"),
        "matched_rules": matched_rules,
        "manual_review_status": "auto_classified_needs_review",
    }


def main():
    if not RAW_ROOT.exists():
        raise SystemExit(f"Raw dataset not found: {RAW_ROOT}")

    items = []
    skipped = []
    for path in sorted(RAW_ROOT.glob("*.json"), key=lambda item: item.stem.lower()):
        try:
            items.append(build_item(path))
        except Exception as exc:
            skipped.append({"file": path.name, "error": str(exc)})

    type_counts = {}
    for item in items:
        for type_id in item["vulnerability_type_ids"]:
            type_counts[type_id] = type_counts.get(type_id, 0) + 1

    payload = {
        "schema_version": "0.1.0",
        "generated_by": "scripts/build_knowledge_case_index.py",
        "source_root": "dataset/raw",
        "total": len(items),
        "skipped": skipped,
        "type_counts": dict(sorted(type_counts.items())),
        "items": items,
    }

    KNOWLEDGE_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT).as_posix()} ({len(items)} cases)")
    if skipped:
        print(f"skipped {len(skipped)} files")


if __name__ == "__main__":
    main()
