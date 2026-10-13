import asyncio


import base64


import json


import logging


import os


import re


import time


from datetime import datetime


from pathlib import Path


from typing import Any, Dict, List


from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect


from app.attackpilot.knowledge import get_rag_service






from app.attackpilot.settings import JSONRPCS, LLM_NAME, PROJECT_PATH


from app.attackpilot.utils.llm_client import LLMClient


from .models import (
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantSource,
    DappCatalogItem,
    DappCatalogResponse,
    TaskCreateRequest,
    TaskResponse,
    TaskStatus,
    TxDetectItem,
    TxDetectRequest,
    TxDetectResponse,
    TxReviewRequest,
    TxReviewResponse,
)


from .review_service import build_automated_review


logger = logging.getLogger(__name__)


AGENT_LOG_ROOT = Path(PROJECT_PATH) / "agents" / "logs"


MAX_AGENT_LOG_BYTES = 2_000_000


PROCESSED_DATA_ROOT = Path(PROJECT_PATH) / "dataset" / "processed"


DISABLE_TASK_DELETE = os.getenv("DISABLE_TASK_DELETE", "true").lower() in {"1", "true", "yes", "on"}


RAW_DATA_ROOT = Path(PROJECT_PATH) / "dataset" / "raw"


KNOWLEDGE_ROOT = Path(PROJECT_PATH) / "data" / "knowledge"


TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")


DEFAULT_ANALYSIS_MODULES = [
    "attack_detection",
    "fault_localization",
    "rag_retrieval",
    "patch_generation",
    "patch_verification",
]


def _normalize_modules(modules):
    from app.attackpilot.schemas import normalize_modules
    return normalize_modules(modules)


def _b64_encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")


def _safe_relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _safe_processed_file_name(dapp_name: str) -> str:
    return dapp_name.replace("/", "_").replace("\\", "_")


def _load_json_file(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_knowledge_file(file_name: str) -> Dict[str, Any]:
    path = (KNOWLEDGE_ROOT / file_name).resolve()
    try:
        path.relative_to(KNOWLEDGE_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid knowledge file")

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Knowledge file is not available: {file_name}")

    try:
        return _load_json_file(path)
    except Exception as exc:
        logger.exception("[Knowledge] Failed to read %s", path)
        raise HTTPException(status_code=500, detail=f"Failed to load knowledge file: {exc}") from exc


def _load_knowledge_cases_payload(source: str) -> Dict[str, Any]:
    if source == "curated":
        return _load_knowledge_file("cases.json")
    if source == "generated":
        return _load_knowledge_file("case_index.generated.json")
    raise HTTPException(status_code=400, detail="source must be curated or generated")


def _filter_knowledge_cases(payload: Dict[str, Any], type_id: str | None, q: str | None) -> Dict[str, Any]:
    raw_items = payload.get("cases") if isinstance(payload.get("cases"), list) else payload.get("items", [])
    items = raw_items if isinstance(raw_items, list) else []
    external_items = payload.get("external_classic_cases", [])
    if isinstance(external_items, list):
        items = [*items, *external_items]

    filtered = []
    query = (q or "").strip().lower()
    for item in items:
        if type_id and type_id not in (item.get("vulnerability_type_ids") or []):
            continue
        if query:
            haystack = " ".join(
                str(item.get(key) or "")
                for key in ["name", "raw_cause", "root_cause", "platform", "why_selected", "learning_summary"]
            ).lower()
            if query not in haystack:
                continue
        filtered.append(item)

    return {
        "schema_version": payload.get("schema_version"),
        "source": payload.get("generated_by") or payload.get("data_source", {}).get("kind") or "curated",
        "total": len(filtered),
        "items": filtered,
    }


def _normalize_tx_hash(tx_hash: str) -> str:
    normalized = tx_hash.strip().lower()
    if not TX_HASH_RE.match(normalized):
        raise HTTPException(status_code=400, detail="tx_hash must be a 0x-prefixed 32-byte transaction hash")
    return normalized


def _try_normalize_tx_hash(tx_hash: str) -> str | None:
    normalized = str(tx_hash or "").strip().lower()
    return normalized if TX_HASH_RE.match(normalized) else None


def _normalize_tx_hashes(tx_hashes: List[str], *, max_count: int = 50) -> tuple[List[str], List[str]]:
    valid: List[str] = []
    invalid: List[str] = []
    seen = set()
    for raw_hash in tx_hashes[:max_count]:
        normalized = _try_normalize_tx_hash(raw_hash)
        if not normalized:
            invalid.append(str(raw_hash))
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        valid.append(normalized)
    return valid, invalid


def _normalize_hash_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().lower() for item in value if isinstance(item, str) and item.strip()]


def _case_match_payload(
    *,
    source: str,
    dataset_file: str,
    case_data: Dict[str, Any],
    matched_hash: str,
) -> Dict[str, Any]:
    name = str(case_data.get("name") or Path(dataset_file).stem)
    vulnerability_types = case_data.get("vulnerability_type_ids") or []
    return {
        "name": name,
        "case_id": case_data.get("case_id"),
        "dataset_file": dataset_file,
        "source": source,
        "matched_hash": matched_hash,
        "platform": case_data.get("platform"),
        "time": case_data.get("time"),
        "cause": case_data.get("cause") or case_data.get("raw_cause"),
        "root_cause": case_data.get("root_cause"),
        "loss": case_data.get("loss") or case_data.get("lost"),
        "report_link": case_data.get("report_link") or case_data.get("link"),
        "vulnerability_type_ids": vulnerability_types if isinstance(vulnerability_types, list) else [],
        "transaction_count": case_data.get("transaction_count")
        or len(_normalize_hash_list(case_data.get("transaction_hashes") or case_data.get("transaction_hash"))),
    }


def _matches_on_chain(tx_hash: str, chain: str) -> List[Dict[str, Any]]:
    aliases = {"ethereum"} if chain == "ethereum" else {"bnbchain", "bnb chain", "bsc"}
    return [item for item in _dedupe_case_matches([
        *_find_raw_tx_matches(tx_hash), *_find_generated_case_matches(tx_hash),
    ]) if str(item.get("platform") or "").strip().lower() in aliases]


def _find_raw_tx_matches(tx_hash: str) -> List[Dict[str, Any]]:
    if not RAW_DATA_ROOT.exists():
        return []

    matches: List[Dict[str, Any]] = []
    for raw_file in sorted(RAW_DATA_ROOT.glob("*.json"), key=lambda path: path.stem.lower()):
        try:
            raw_data = _load_json_file(raw_file)
        except Exception as exc:
            logger.warning("[TxReview] Skipping unreadable raw file %s: %s", raw_file, exc)
            continue

        tx_hashes = _normalize_hash_list(raw_data.get("transaction_hash"))
        if tx_hash not in tx_hashes:
            continue

        matches.append(
            _case_match_payload(
                source="dataset/raw",
                dataset_file=_safe_relative_path(raw_file, Path(PROJECT_PATH)),
                case_data=raw_data,
                matched_hash=tx_hash,
            )
        )

    return matches


def _find_generated_case_matches(tx_hash: str) -> List[Dict[str, Any]]:
    path = KNOWLEDGE_ROOT / "case_index.generated.json"
    if not path.exists():
        return []

    try:
        payload = _load_json_file(path)
    except Exception as exc:
        logger.warning("[TxReview] Failed to read generated case index: %s", exc)
        return []

    matches: List[Dict[str, Any]] = []
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        tx_hashes = _normalize_hash_list(item.get("transaction_hashes") or item.get("transaction_hash"))
        if tx_hash not in tx_hashes:
            continue
        matches.append(
            _case_match_payload(
                source="knowledge/generated",
                dataset_file=str(item.get("dataset_file") or ""),
                case_data=item,
                matched_hash=tx_hash,
            )
        )
    return matches


def _dedupe_case_matches(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in matches:
        key = (item.get("name"), item.get("matched_hash"), item.get("dataset_file"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _chain_to_platform(chain: str) -> str:
    normalized = (chain or "ethereum").strip().lower()
    mapping = {
        "eth": "Ethereum",
        "ethereum": "Ethereum",
        "mainnet": "Ethereum",
        "bnb": "BNBChain",
        "bsc": "BNBChain",
        "bnbchain": "BNBChain",
        "bnb_chain": "BNBChain",
    }
    platform = mapping.get(normalized)
    if not platform:
        raise HTTPException(status_code=400, detail="Unsupported chain. Supported values: ethereum, bnbchain")
    return platform


def _build_adhoc_dapp_payload(tx_hash: str, chain: str, tx_hashes: List[str] | None = None, modules: List[str] | None = None) -> Dict[str, Any]:
    platform = _chain_to_platform(chain)
    all_hashes = tx_hashes or [tx_hash]
    display_hash = _short_hash(tx_hash).replace("...", "_")
    display_name = f"{display_hash} +{len(all_hashes) - 1}" if len(all_hashes) > 1 else display_hash
    return {
        "name": f"Adhoc Tx Review {display_name}",
        "cause": "Adhoc transaction review",
        "platform": platform,
        "transaction_hash": all_hashes,
        "time": None,
        "lost": None,
        "root_cause": "Unknown before deep analysis",
        "report": (
            "Created from user-submitted transaction hash(es). "
            "The workflow will fetch chain evidence and let agents review whether the transaction set contains exploit behavior."
        ),
        "report_link": None,
        "source": "tx_review_deep_analysis",
        "enabled_modules": modules or [],
    }


def _hex_to_int(value: Any, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if not isinstance(value, str) or not value:
        return default
    try:
        return int(value, 16) if value.startswith("0x") else int(value)
    except ValueError:
        return default


async def _download_with_timeout(coro, timeout: float = 8.0):
    try:
        return await asyncio.wait_for(coro, timeout=timeout), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


async def _load_tx_observation(tx_hash: str, chain: str) -> Dict[str, Any]:
    import httpx
    platform = _chain_to_platform(chain)
    rpc_urls = JSONRPCS.get(platform) or []
    if not rpc_urls:
        return {"status": "unavailable", "errors": [f"No JSON-RPC endpoint configured for {platform}"]}

    # Interactive requests never write to the engine's shared cache. A task worker
    # has its own cache; this path remains isolated across both users and chains.
    async with httpx.AsyncClient(timeout=10) as client:
        async def rpc(method, params):
            for url in rpc_urls[:2]:
                try:
                    response = await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get("error"):
                        raise ValueError(str(payload["error"].get("message", "RPC rejected request")))
                    if payload.get("result") is None:
                        return None, f"{method}: transaction not found"
                    return payload["result"], None
                except (httpx.HTTPError, ValueError) as exc:
                    reason = f"{method}: {type(exc).__name__}"
                    if isinstance(exc, httpx.HTTPStatusError): reason += f" (HTTP {exc.response.status_code})"
                    elif isinstance(exc, ValueError): reason += f" ({str(exc)[:160]})"
            return None, reason
        (tx, tx_error), (receipt, receipt_error), (trace, trace_error) = await asyncio.gather(
            rpc("eth_getTransactionByHash", [tx_hash]),
            rpc("eth_getTransactionReceipt", [tx_hash]),
            rpc("debug_traceTransaction", [tx_hash, {"tracer": "callTracer"}]),
        )
    def flatten(node):
        if not isinstance(node, dict): return []
        return [{key: value for key, value in node.items() if key != "calls"},
                *[item for child in node.get("calls", []) for item in flatten(child)]]
    errors = [error for error in (tx_error, receipt_error, trace_error) if error]
    status = "ok" if tx or receipt or trace else "unavailable"
    if status == "ok" and errors: status = "partial"
    return {"status": status, "platform": platform, "tx": tx or {}, "receipt": receipt or {}, "trace": flatten(trace), "errors": errors}


def _input_selector(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.lower()
    if not value.startswith("0x") or len(value) < 10:
        return ""
    return value[:10]


def _build_signal(
    signal_id: str,
    name: str,
    level: str,
    summary: str,
    evidence: str,
    confidence: str = "medium",
) -> Dict[str, str]:
    return {
        "id": signal_id,
        "name": name,
        "level": level,
        "summary": summary,
        "evidence": evidence,
        "confidence": confidence,
    }


def _analyze_tx_observation(observation: Dict[str, Any]) -> tuple[List[Dict[str, str]], Dict[str, Any]]:
    tx = observation.get("tx") if isinstance(observation.get("tx"), dict) else {}
    receipt = observation.get("receipt") if isinstance(observation.get("receipt"), dict) else {}
    trace = observation.get("trace") if isinstance(observation.get("trace"), list) else []
    logs = receipt.get("logs") if isinstance(receipt.get("logs"), list) else []

    transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    transfer_logs = [
        log for log in logs
        if isinstance(log, dict)
        and isinstance(log.get("topics"), list)
        and log.get("topics")
        and str(log["topics"][0]).lower() == transfer_topic
    ]
    token_contracts = {
        str(log.get("address", "")).lower()
        for log in transfer_logs
        if isinstance(log, dict) and log.get("address")
    }

    trace_addresses = set()
    call_types = []
    selectors = []
    for item in trace:
        if not isinstance(item, dict):
            continue
        for key in ["from", "to"]:
            address = item.get(key)
            if isinstance(address, str) and address:
                trace_addresses.add(address.lower())
        call_type = str(item.get("type") or item.get("callType") or "").upper()
        if call_type:
            call_types.append(call_type)
        selector = _input_selector(item.get("input"))
        if selector:
            selectors.append(selector)

    root_selector = _input_selector(tx.get("input"))
    if root_selector:
        selectors.append(root_selector)

    selector_names = {
        "0x095ea7b3": "approve",
        "0x23b872dd": "transferFrom",
        "0xa9059cbb": "transfer",
        "0x022c0d9f": "UniswapV2Pair.swap",
        "0x128acb08": "UniswapV3Pool.swap",
        "0x414bf389": "exactInputSingle",
        "0xc04b8d59": "exactInput",
        "0x5cffe9de": "flashLoan",
        "0xab9c4b5d": "flashLoan",
        "0xe0232b42": "flashLoanSimple",
        "0xd0e30db0": "deposit",
        "0x2e1a7d4d": "withdraw",
    }
    matched_selectors = [selector_names[item] for item in selectors if item in selector_names]

    status_value = str(receipt.get("status") or "").lower()
    gas_used = _hex_to_int(receipt.get("gasUsed"))
    call_count = len(trace)
    contract_count = len({addr for addr in trace_addresses if addr})
    transfer_count = len(transfer_logs)
    unique_token_count = len(token_contracts)
    delegatecall_count = sum(1 for item in call_types if item in {"DELEGATECALL", "CALLCODE"})
    selfdestruct_count = sum(1 for item in call_types if item in {"SELFDESTRUCT", "SUICIDE"})

    metrics = {
        "observation_status": observation.get("status"),
        "gas_used": gas_used,
        "log_count": len(logs),
        "erc20_transfer_log_count": transfer_count,
        "token_contract_count": unique_token_count,
        "trace_call_count": call_count,
        "trace_contract_count": contract_count,
        "delegatecall_count": delegatecall_count,
        "selfdestruct_count": selfdestruct_count,
        "matched_method_names": sorted(set(matched_selectors)),
        "receipt_status": status_value or None,
        "observation_errors": observation.get("errors") or [],
    }

    signals: List[Dict[str, str]] = []
    if status_value == "0x0":
        signals.append(_build_signal(
            "reverted_tx",
            "交易执行失败或 revert",
            "medium",
            "失败交易可能是攻击试探、失败攻击或普通业务失败，需要结合上下文判断。",
            "receipt.status = 0x0",
            "high",
        ))

    if gas_used >= 1_500_000:
        signals.append(_build_signal(
            "high_gas",
            "高 gas 消耗",
            "medium",
            "复杂 DeFi 攻击通常包含多层合约调用和大量状态变化。",
            f"gasUsed = {gas_used:,}",
        ))

    if call_count >= 25 or contract_count >= 10:
        signals.append(_build_signal(
            "multi_contract_trace",
            "多合约调用链",
            "high" if contract_count >= 15 or call_count >= 40 else "medium",
            "交易涉及较多合约与内部调用，适合进入 trace 级别审查。",
            f"trace calls = {call_count}, unique trace addresses = {contract_count}",
        ))
    elif call_count >= 5 or contract_count >= 3:
        signals.append(_build_signal(
            "composable_defi_call",
            "组合式合约交互",
            "low",
            "该交易不是简单转账，存在合约组合调用，需要结合业务语义判断。",
            f"trace calls = {call_count}, unique trace addresses = {contract_count}",
        ))

    if transfer_count >= 6 or unique_token_count >= 3:
        signals.append(_build_signal(
            "dense_token_flow",
            "资产变化密集",
            "high" if transfer_count >= 12 or unique_token_count >= 5 else "medium",
            "同一交易内出现多笔 ERC20 Transfer 事件，可能涉及兑换、借贷、清算或获利转移。",
            f"ERC20 Transfer logs = {transfer_count}, token contracts = {unique_token_count}",
        ))

    if delegatecall_count > 0:
        signals.append(_build_signal(
            "delegatecall",
            "出现 delegatecall/callcode",
            "medium",
            "delegatecall 会复用调用方 storage，上下文错误时可能引入权限或存储风险。",
            f"delegatecall/callcode count = {delegatecall_count}",
            "high",
        ))

    if selfdestruct_count > 0:
        signals.append(_build_signal(
            "selfdestruct",
            "出现 selfdestruct",
            "high",
            "selfdestruct 可能改变合约生命周期或资产流，需要重点审查。",
            f"selfdestruct count = {selfdestruct_count}",
            "high",
        ))

    if any(name in {"approve", "transferFrom"} for name in matched_selectors):
        signals.append(_build_signal(
            "approval_flow",
            "授权/代扣相关调用",
            "medium",
            "approve 或 transferFrom 参与资金移动时，需要确认授权来源和受益地址是否异常。",
            f"matched methods = {', '.join(sorted(set(matched_selectors)))}",
        ))

    if any("flashLoan" in name for name in matched_selectors):
        signals.append(_build_signal(
            "flash_loan",
            "疑似 flash loan 入口",
            "high",
            "闪电贷本身不是漏洞，但常用于放大价格、会计或业务逻辑缺陷。",
            f"matched methods = {', '.join(sorted(set(matched_selectors)))}",
            "medium",
        ))

    if any("swap" in name or "exactInput" in name for name in matched_selectors):
        signals.append(_build_signal(
            "pool_interaction",
            "存在池子/兑换交互",
            "medium",
            "池子交互需要结合价格、储备量和资产变化判断是否存在操纵。",
            f"matched methods = {', '.join(sorted(set(matched_selectors)))}",
        ))

    if observation.get("status") == "unavailable":
        signals.append(_build_signal(
            "live_observation_unavailable",
            "链上轻量观测暂不可用",
            "low",
            "当前只完成本地案例库检查，实时交易特征需要稍后重试或进入深度分析。",
            "; ".join(observation.get("errors") or ["RPC returned no usable data"]),
            "low",
        ))

    return signals, metrics


def _risk_from_signals(signals: List[Dict[str, str]], has_match: bool, live_status: str) -> str:
    if has_match:
        return "high"
    weights = {"high": 3, "medium": 2, "low": 1}
    score = sum(weights.get(signal.get("level"), 0) for signal in signals)
    if any(signal.get("level") == "high" for signal in signals) or score >= 5:
        return "high"
    if score >= 2:
        return "medium"
    if live_status in {"ok", "partial"}:
        return "low"
    return "unknown"


def _classify_detect_item(risk_level: str, signal_details: List[Dict[str, str]], matches: List[Dict[str, Any]]) -> str:
    if matches:
        return "known_attack"
    signal_ids = {str(item.get("id") or "") for item in signal_details}
    if risk_level == "high":
        return "attack_candidate"
    if signal_ids.intersection({"flash_loan", "dense_token_flow", "pool_interaction", "delegatecall"}):
        return "auxiliary_candidate"
    if risk_level in {"medium", "unknown"}:
        return "needs_review"
    return "unrelated"


def _detect_item_summary(classification: str, risk_level: str, signals: List[str]) -> str:
    if classification == "known_attack":
        return "命中本地真实攻击案例库，建议直接进入复盘或重新运行分析。"
    if classification == "attack_candidate":
        return "链上轻量检测发现较强攻击信号，建议进入故障定位。"
    if classification == "auxiliary_candidate":
        return "存在资金、池子或权限相关信号，可能是准备交易或辅助交易。"
    if classification == "needs_review":
        return "存在可疑交互，但证据不足，需要结合上下文继续判断。"
    if risk_level == "unknown":
        return "链上数据暂不可用，当前只能给出本地索引检查结果。"
    return "暂未发现明显攻击信号。"


async def _detect_single_tx(tx_hash: str, chain: str) -> TxDetectItem:
    matches = _matches_on_chain(tx_hash, chain)
    observation = await _load_tx_observation(tx_hash, chain)
    observation_signals, metrics = _analyze_tx_observation(observation)
    live_status = str(observation.get("status") or "unavailable")

    if matches:
        primary = matches[0]
        case_signal = _build_signal(
            "known_case_match",
            "命中本地攻击案例",
            "high",
            "该交易已出现在本地真实攻击案例库中。",
            f"matched case = {primary.get('name')}",
            "high",
        )
        signal_details = [case_signal, *observation_signals]
    else:
        signal_details = observation_signals

    risk_level = _risk_from_signals(signal_details, has_match=bool(matches), live_status=live_status)
    classification = _classify_detect_item(risk_level, signal_details, matches)
    signal_names = [str(signal.get("name") or signal.get("id") or "signal") for signal in signal_details]

    return TxDetectItem(
        tx_hash=tx_hash,
        risk_level=risk_level,
        classification=classification,
        summary=_detect_item_summary(classification, risk_level, signal_names),
        signals=signal_names,
        signal_details=signal_details,
        metrics=metrics,
        matched_cases=matches,
        live_observation_status=live_status,
    )


def _as_reference(value: Any) -> Dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "time": value.get("time"),
        "link": value.get("link"),
    }


def _short_hash(value: str) -> str:
    return f"{value[:10]}...{value[-8:]}" if len(value) > 18 else value


def _summarize_balance_change(tx_hash: str, balance_change: Dict[str, Any]) -> Dict[str, Any]:
    tx_balance = balance_change.get(tx_hash, {}) if isinstance(balance_change, dict) else {}
    participants = []
    total_usd_delta = 0.0

    for address, token_changes in tx_balance.items():
        token_summary = []
        address_usd_delta = 0.0
        if not isinstance(token_changes, dict):
            continue
        for token_address, change in token_changes.items():
            if not isinstance(change, dict):
                continue
            usd_value = change.get("usd_value")
            if isinstance(usd_value, (int, float)):
                address_usd_delta += usd_value
                total_usd_delta += usd_value
            token_summary.append(
                {
                    "token": change.get("symbol") or token_address,
                    "name": change.get("name"),
                    "amount": change.get("fmt_amount"),
                    "usd_value": usd_value,
                    "contract": change.get("contract"),
                }
            )
        participants.append(
            {
                "address": address,
                "usd_delta": address_usd_delta,
                "tokens": token_summary[:8],
            }
        )

    participants.sort(key=lambda item: abs(item.get("usd_delta") or 0), reverse=True)
    return {
        "participant_count": len(participants),
        "total_usd_delta": total_usd_delta,
        "top_participants": participants[:8],
    }


def _summarize_transaction(
    tx_hash: str,
    processed_data: Dict[str, Any],
    index: int,
) -> Dict[str, Any]:
    detail = (processed_data.get("transaction_to_detail") or {}).get(tx_hash, {}) or {}
    attack_transactions = set(processed_data.get("attack_transactions") or [])
    auxiliary_transactions = set(processed_data.get("auxiliary_transactions") or [])
    debug_targets = set(processed_data.get("transactions_need_analyze") or [])
    address_roles = processed_data.get("transaction_roles") or {}
    from_addr = str(detail.get("from") or "").lower()
    to_addr = str(detail.get("to") or detail.get("contract_address") or "").lower()

    if tx_hash in attack_transactions:
        tx_type = "attack"
    elif tx_hash in auxiliary_transactions:
        tx_type = "auxiliary"
    else:
        tx_type = "candidate"

    involved_roles = []
    for address in [from_addr, to_addr]:
        role_item = address_roles.get(address) if isinstance(address_roles, dict) else None
        if role_item:
            involved_roles.append(
                {
                    "address": address,
                    "role": role_item.get("role"),
                    "description": role_item.get("description"),
                }
            )

    logs = ((detail.get("log_analysis") or {}).get("detailed_logs") or [])[:8]
    return {
        "hash": tx_hash,
        "display_hash": _short_hash(tx_hash),
        "type": tx_type,
        "is_debug_target": tx_hash in debug_targets,
        "order": index,
        "from": from_addr or None,
        "to": to_addr or None,
        "from_role": (address_roles.get(from_addr) or {}).get("role") if isinstance(address_roles, dict) else None,
        "to_role": (address_roles.get(to_addr) or {}).get("role") if isinstance(address_roles, dict) else None,
        "involved_roles": involved_roles,
        "block_number": detail.get("block_number"),
        "timestamp": detail.get("timestamp"),
        "function_signature": detail.get("function_signature"),
        "status": (detail.get("status") or {}).get("description"),
        "success": (detail.get("status") or {}).get("success"),
        "value_eth": (detail.get("value") or {}).get("eth"),
        "gas_used": (detail.get("gas") or {}).get("used"),
        "cost_eth": (detail.get("cost") or {}).get("total_eth"),
        "interacted_addresses": ((detail.get("log_analysis") or {}).get("interacted_addresses") or [])[:12],
        "event_logs": logs,
        "balance_summary": _summarize_balance_change(tx_hash, processed_data.get("balance_change") or {}),
    }


def _load_macro_analysis_payload(task: TaskResponse) -> Dict[str, Any]:
    from app.attackpilot import store
    processed_file = (PROCESSED_DATA_ROOT / f"{_safe_processed_file_name(task.dapp_name)}.json") if task.is_demo else store.task_dir(task.task_id) / "processed.json"
    if not processed_file.exists():
        raise HTTPException(status_code=404, detail="Processed macro analysis is not available yet")

    try:
        processed_data = json.loads(processed_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.exception("[Macro] Failed to read processed data for %s", task.dapp_name)
        raise HTTPException(status_code=500, detail=f"Failed to load processed macro analysis: {exc}") from exc

    tx_order = processed_data.get("transaction_hash_list") or (processed_data.get("dapp") or {}).get("transaction_hash") or []
    transaction_summaries = [
        _summarize_transaction(tx_hash, processed_data, index)
        for index, tx_hash in enumerate(tx_order)
    ]

    return {
        "task_id": task.task_id,
        "dapp_name": task.dapp_name,
        "processed_file": processed_file.name,
        "dapp": processed_data.get("dapp"),
        "transaction_hash_list": tx_order,
        "transaction_roles": processed_data.get("transaction_roles", {}),
        "attack_transactions": processed_data.get("attack_transactions", []),
        "auxiliary_transactions": processed_data.get("auxiliary_transactions", []),
        "transactions_need_analyze": processed_data.get("transactions_need_analyze", []),
        "bug_summary": processed_data.get("bug_summary", ""),
        "time_used": processed_data.get("time_used", {}),
        "token_used": processed_data.get("token_used", {}),
        "transactions": transaction_summaries,
        "balance_change": processed_data.get("balance_change", {}),
        "transaction_to_property": processed_data.get("transaction_to_property", {}),
    }


async def list_dapps():
    if not RAW_DATA_ROOT.exists():
        raise HTTPException(status_code=404, detail="Raw DApp dataset is not available")

    items: List[DappCatalogItem] = []
    for raw_file in sorted(RAW_DATA_ROOT.glob("*.json"), key=lambda path: path.stem.lower()):
        try:
            raw_data = _load_json_file(raw_file)
        except Exception as exc:
            logger.warning("[DApps] Skipping unreadable raw file %s: %s", raw_file, exc)
            continue

        name = str(raw_data.get("name") or raw_file.stem)
        tx_hashes = raw_data.get("transaction_hash") or []
        if not isinstance(tx_hashes, list):
            tx_hashes = []

        processed_file = PROCESSED_DATA_ROOT / f"{_safe_processed_file_name(name)}.json"
        has_processed = processed_file.exists()
        demo_ready = has_processed and bool(tx_hashes)

        items.append(
            DappCatalogItem(
                name=name,
                cause=raw_data.get("cause"),
                platform=raw_data.get("platform"),
                time=raw_data.get("time"),
                root_cause=raw_data.get("root_cause"),
                report=raw_data.get("report"),
                detection=_as_reference(raw_data.get("detection")),
                disclosure=_as_reference(raw_data.get("disclosure")),
                report_link=raw_data.get("report_link"),
                transaction_hash=[str(tx_hash) for tx_hash in tx_hashes],
                transaction_count=len(tx_hashes),
                raw_file=_safe_relative_path(raw_file, RAW_DATA_ROOT),
                processed_file=_safe_relative_path(processed_file, PROCESSED_DATA_ROOT) if has_processed else None,
                has_processed_analysis=has_processed,
                demo_ready=demo_ready,
            )
        )

    items.sort(key=lambda item: (not item.demo_ready, item.name.lower()))
    return DappCatalogResponse(
        total=len(items),
        demo_ready_count=sum(1 for item in items if item.demo_ready),
        items=items,
    )


async def detect_transaction_set(request: TxDetectRequest):
    chain = (request.chain or "ethereum").strip().lower()
    _chain_to_platform(chain)
    enabled_modules = _normalize_modules(request.modules)
    valid_hashes, invalid_hashes = _normalize_tx_hashes(request.tx_hashes, max_count=50)
    if not valid_hashes:
        raise HTTPException(status_code=400, detail="At least one valid transaction hash is required")

    if "attack_detection" not in enabled_modules:
        return TxDetectResponse(
            chain=chain,
            input_count=len(request.tx_hashes),
            analyzed_count=0,
            risk_level="unknown",
            summary="攻击检测模块未启用。本次仅保留输入交易，可直接进入后续复盘模块。",
            modules=enabled_modules,
            recommended_tx_hashes=valid_hashes,
            invalid_hashes=invalid_hashes,
            deep_analysis_ready=True,
        )

    semaphore = asyncio.Semaphore(4)

    async def run_one(tx_hash: str) -> TxDetectItem:
        async with semaphore:
            return await _detect_single_tx(tx_hash, chain)

    items = await asyncio.gather(*(run_one(tx_hash) for tx_hash in valid_hashes))
    attack_items = [
        item for item in items
        if item.classification in {"known_attack", "attack_candidate"} or item.risk_level == "high"
    ]
    attack_hashes = {item.tx_hash for item in attack_items}
    auxiliary_items = [
        item for item in items
        if item.tx_hash not in attack_hashes and item.classification in {"auxiliary_candidate", "needs_review"}
    ]
    auxiliary_hashes = {item.tx_hash for item in auxiliary_items}
    unrelated_items = [item for item in items if item.tx_hash not in attack_hashes and item.tx_hash not in auxiliary_hashes]

    recommended = [item.tx_hash for item in [*attack_items, *auxiliary_items]]
    if not recommended and items:
        recommended = [items[0].tx_hash]

    if attack_items:
        risk_level = "high"
        summary = f"检测到 {len(attack_items)} 笔高风险/已知攻击候选交易，建议进入故障定位。"
    elif auxiliary_items:
        risk_level = "medium"
        summary = f"检测到 {len(auxiliary_items)} 笔可疑辅助交易，建议结合上下文继续分析。"
    elif any(item.risk_level == "unknown" for item in items):
        risk_level = "unknown"
        summary = "部分链上数据暂不可用，当前未形成明确攻击判断。"
    else:
        risk_level = "low"
        summary = "暂未发现明显攻击候选交易，可根据人工上下文选择是否继续分析。"

    return TxDetectResponse(
        chain=chain,
        input_count=len(request.tx_hashes),
        analyzed_count=len(items),
        risk_level=risk_level,
        summary=summary,
        modules=enabled_modules,
        recommended_tx_hashes=recommended,
        attack_candidates=attack_items,
        auxiliary_candidates=auxiliary_items,
        unrelated_candidates=unrelated_items,
        invalid_hashes=invalid_hashes,
        deep_analysis_ready=bool(recommended),
    )


async def review_transaction_hash(request: TxReviewRequest):
    tx_hash = _normalize_tx_hash(request.tx_hash)
    chain = (request.chain or "ethereum").strip().lower()
    _chain_to_platform(chain)

    matches = _matches_on_chain(tx_hash, chain)
    observation = await _load_tx_observation(tx_hash, chain)
    observation_signals, metrics = _analyze_tx_observation(observation)
    live_status = str(observation.get("status") or "unavailable")

    if matches:
        primary = matches[0]
        case_signal = _build_signal(
            "known_case_match",
            "命中本地攻击案例",
            "high",
            "该交易已出现在本地真实攻击案例库中。",
            f"matched case = {primary.get('name')}",
            "high",
        )
        signal_details = [case_signal, *observation_signals]
        signals = [signal["name"] for signal in signal_details]
        if primary.get("root_cause"):
            signals.append(f"已有根因线索：{primary['root_cause']}")
        if primary.get("cause"):
            signals.append(f"原始风险标签：{primary['cause']}")

        evidence = [
            {
                "type": "dataset_match",
                "title": "交易 Hash 命中案例库",
                "content": f"{tx_hash} 出现在 {primary.get('name')} 的攻击交易列表中。",
                "source": primary.get("dataset_file") or primary.get("source") or "dataset/raw",
            }
        ]
        if primary.get("report_link"):
            evidence.append(
                {
                    "type": "incident_report",
                    "title": "外部事故报告",
                    "content": str(primary["report_link"]),
                    "source": "report_link",
                }
            )
        if primary.get("vulnerability_type_ids"):
            evidence.append(
                {
                    "type": "knowledge_tags",
                    "title": "漏洞知识库归类",
                    "content": "、".join(str(item) for item in primary["vulnerability_type_ids"]),
                    "source": "data/knowledge/case_index.generated.json",
                }
            )

        return TxReviewResponse(
            tx_hash=tx_hash,
            chain=chain,
            risk_level="high",
            tx_type="known_attack_case",
            summary=f"该交易已命中本地攻击案例库：{primary.get('name')}。建议直接进入对应案例查看攻击路径、证据链和修复方向。",
            signals=signals,
            signal_details=signal_details,
            evidence=evidence,
            metrics=metrics,
            live_observation_status=live_status,
            matched_cases=matches,
            recommend_deep_analysis=True,
            deep_analysis_ready=True,
        )

    risk_level = _risk_from_signals(observation_signals, has_match=False, live_status=live_status)
    if risk_level == "high":
        summary = "该交易未命中本地攻击案例库，但链上轻量审查发现高风险攻击线索，建议立即启动深度分析。"
    elif risk_level == "medium":
        summary = "该交易未命中本地攻击案例库，但存在可疑链上交互信号，建议结合 trace 和资金变化继续审查。"
    elif risk_level == "low":
        summary = "该交易未命中本地攻击案例库，轻量审查暂未发现强攻击信号；如仍有上下文怀疑，可启动深度分析。"
    else:
        summary = "该交易暂未命中本地攻击案例库，且实时链上观测暂不可用；建议稍后重试或直接进入深度分析。"

    signal_details = observation_signals or [
        _build_signal(
            "local_index_only",
            "仅完成本地查重",
            "low",
            "当前只确认该 Hash 未出现在本地攻击案例库中。",
            "dataset/raw and data/knowledge index checked",
            "medium",
        )
    ]

    return TxReviewResponse(
        tx_hash=tx_hash,
        chain=chain,
        risk_level=risk_level,
        tx_type="unreviewed_transaction",
        summary=summary,
        signals=[signal["name"] for signal in signal_details],
        signal_details=signal_details,
        evidence=[
            {
                "type": "local_index_check",
                "title": "本地案例库查重",
                "content": "已检查 dataset/raw/*.json 与 data/knowledge/case_index.generated.json，未发现相同交易 Hash。",
                "source": "local_knowledge_base",
            },
            {
                "type": "live_observation",
                "title": "链上轻量观测",
                "content": f"observation_status={live_status}; trace_calls={metrics.get('trace_call_count', 0)}; transfer_logs={metrics.get('erc20_transfer_log_count', 0)}",
                "source": "json_rpc",
            }
        ],
        metrics=metrics,
        live_observation_status=live_status,
        matched_cases=[],
        recommend_deep_analysis=risk_level in {"high", "medium", "unknown"},
        deep_analysis_ready=True,
    )


ASSISTANT_CONTEXT_LIMIT = 12000


ASSISTANT_LOG_LIMIT = 80


ASSISTANT_RESPONSE_TIMEOUT = 45


def _truncate_text(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...[truncated {len(text) - limit} chars]"


def _compact_json(value: Any, limit: int = 2400) -> str:
    return _truncate_text(json.dumps(value, ensure_ascii=False, default=str, indent=2), limit)


def _model_to_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return dict(value)


def _assistant_source(source_type: str, title: str, source: str, content: Any = None) -> AssistantSource:
    return AssistantSource(
        type=source_type,
        title=title,
        source=source,
        content=_truncate_text(content, 260) if content is not None else None,
    )


def _safe_load_macro_for_assistant(task: TaskResponse) -> Dict[str, Any] | None:
    try:
        return _load_macro_analysis_payload(task)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise


def _task_context_for_assistant(task: TaskResponse) -> tuple[str, List[AssistantSource]]:
    sources: List[AssistantSource] = [
        _assistant_source("task", "任务状态", f"task:{task.task_id}", {
            "task_id": task.task_id,
            "dapp_name": task.dapp_name,
            "status": task.status.value,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "error": task.error,
        })
    ]
    parts = [
        "## 当前任务",
        _compact_json({
            "task_id": task.task_id,
            "dapp_name": task.dapp_name,
            "status": task.status.value,
            "duration": task.duration,
            "error": task.error,
        }, 1200),
    ]

    if task.final_report:
        sources.append(_assistant_source("report", "最终分析报告", f"task:{task.task_id}:final_report", task.final_report))
        parts.extend(["## 最终报告摘要", _truncate_text(task.final_report, 4200)])

    macro = _safe_load_macro_for_assistant(task)
    if macro:
        compact_macro = {
            "dapp_name": macro.get("dapp_name"),
            "bug_summary": macro.get("bug_summary"),
            "attack_transactions": macro.get("attack_transactions"),
            "auxiliary_transactions": macro.get("auxiliary_transactions"),
            "transactions_need_analyze": macro.get("transactions_need_analyze"),
            "transaction_count": len(macro.get("transaction_hash_list") or []),
            "transactions": (macro.get("transactions") or [])[:6],
        }
        sources.append(_assistant_source("macro_analysis", "宏观交易分析", f"task:{task.task_id}:macro", compact_macro))
        parts.extend(["## 宏观交易分析", _compact_json(compact_macro, 3200)])

    logs = load_persisted_log_events(task.task_id, task.dapp_name, limit=ASSISTANT_LOG_LIMIT)
    if logs:
        compact_logs = [
            {
                "agent": item.get("agent"),
                "level": item.get("level"),
                "message_type": item.get("message_type"),
                "message": _truncate_text(item.get("message") or "", 420),
            }
            for item in logs[-ASSISTANT_LOG_LIMIT:]
        ]
        sources.append(_assistant_source("logs", "最近 Agent 日志", f"task:{task.task_id}:logs", f"{len(logs)} events"))
        parts.extend(["## 最近 Agent 日志", _compact_json(compact_logs, 3600)])

    return "\n\n".join(parts), sources


def _rag_context_for_assistant(question: str, top_k: int = 5) -> tuple[str, List[AssistantSource]]:
    try:
        result = get_rag_service().search(question, top_k=top_k)
    except Exception as exc:
        logger.warning("[RAG] Search failed: %s", exc)
        return "", []

    items = result.get("items", []) if isinstance(result, dict) else []
    if not items:
        return "", []

    compact = [
        {
            "title": item.get("title"),
            "source": item.get("source"),
            "tags": item.get("tags", [])[:4],
            "score": item.get("score"),
            "content": _truncate_text(item.get("content") or "", 480),
            "metadata": item.get("metadata", {}),
        }
        for item in items[:top_k]
    ]
    sources = [
        _assistant_source(
            "rag",
            str(item.get("title") or "RAG knowledge"),
            str(item.get("id") or item.get("source") or "data/rag/knowledge_index.json"),
            _truncate_text(item.get("content") or "", 420),
        )
        for item in items[:top_k]
    ]
    return "\n\n".join(["## RAG similar cases and vulnerability knowledge", _compact_json(compact, 3600)]), sources


def _knowledge_context_for_assistant(question: str, limit: int = 6) -> tuple[str, List[AssistantSource]]:
    query = question.lower()
    sources: List[AssistantSource] = []
    parts: List[str] = []

    vulnerabilities = _load_knowledge_file("vulnerability_types.json")
    vulnerability_items = vulnerabilities if isinstance(vulnerabilities, list) else vulnerabilities.get("items", [])
    if isinstance(vulnerability_items, list):
        scored = []
        for item in vulnerability_items:
            haystack = " ".join(
                str(item.get(key) or "")
                for key in ["id", "name_zh", "name_en", "one_liner", "mental_model", "tracepilot_usage"]
            ).lower()
            score = sum(1 for token in re.findall(r"[\w\u4e00-\u9fff]+", query) if token and token in haystack)
            scored.append((score, item))
        selected = [item for score, item in sorted(scored, key=lambda pair: pair[0], reverse=True)[:limit] if score > 0]
        if not selected:
            selected = vulnerability_items[: min(4, len(vulnerability_items))]
        compact = [
            {
                "id": item.get("id"),
                "name_zh": item.get("name_zh"),
                "name_en": item.get("name_en"),
                "one_liner": item.get("one_liner"),
                "trace_signals": item.get("trace_signals", [])[:4],
                "repair_hints": item.get("repair_hints", [])[:4],
            }
            for item in selected
        ]
        sources.append(_assistant_source("knowledge", "漏洞类型知识库", "data/knowledge/vulnerability_types.json", f"{len(compact)} items"))
        parts.extend(["## 漏洞类型知识", _compact_json(compact, 3200)])

    try:
        cases_payload = _load_knowledge_cases_payload("curated")
        case_items = _filter_knowledge_cases(cases_payload, type_id=None, q=None).get("items", [])
        compact_cases = [
            {
                "case_id": item.get("case_id"),
                "name": item.get("name"),
                "root_cause": item.get("root_cause"),
                "learning_summary": item.get("learning_summary"),
                "vulnerability_type_ids": item.get("vulnerability_type_ids"),
            }
            for item in case_items[:4]
        ]
        if compact_cases:
            sources.append(_assistant_source("knowledge", "精选案例知识库", "data/knowledge/cases.json", f"{len(compact_cases)} items"))
            parts.extend(["## 精选案例", _compact_json(compact_cases, 2400)])
    except HTTPException:
        pass

    return "\n\n".join(parts), sources


def _assistant_suggested_questions(scope: str, has_task: bool, has_tx: bool) -> List[str]:
    if scope == "task" or has_task:
        return [
            "这份报告最关键的漏洞证据是什么？",
            "用新手能懂的话解释这次攻击路径。",
            "补丁建议应该优先看哪一类问题？",
        ]
    if scope == "tx_review" or has_tx:
        return [
            "为什么这笔交易值得进一步审查？",
            "这些风险信号分别说明什么？",
            "下一步应该启动深度复盘吗？",
        ]
    return [
        "重入攻击一般怎么看 trace？",
        "PoC 是什么，和真实攻击有什么关系？",
        "常见漏洞通常怎么打补丁？",
    ]


def _build_assistant_messages(
    *,
    request: AssistantChatRequest,
    context: str,
) -> List[Dict[str, str]]:
    system_prompt = """你是 AttackPilot 的链上安全取证助手。
你的职责是帮助用户理解交易审查结果、攻击复盘报告、Agent 日志和漏洞知识库。
回答要求：
1. 只基于提供的上下文回答；上下文不足时明确说明缺口，并给出下一步应查看的证据。
2. 不要把轻量审查信号直接等同于攻击结论。
3. 优先用中文，表达简洁、专业、适合初学者理解。
4. 涉及漏洞定位时，按“现象 -> 证据 -> 可能原因 -> 下一步验证/补丁方向”组织。
5. 不编造交易哈希、函数名、金额、外部链接或源码证据。"""

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": f"当前可用上下文：\n{_truncate_text(context, ASSISTANT_CONTEXT_LIMIT)}"},
    ]
    for item in request.history[-6:]:
        if item.role in {"user", "assistant"}:
            messages.append({"role": item.role, "content": _truncate_text(item.content, 1200)})
    messages.append({"role": "user", "content": request.question.strip()})
    return messages


async def _call_assistant_llm(messages: List[Dict[str, str]]) -> str:
    client = LLMClient()
    response = await asyncio.wait_for(
        client.create_chat_completion(
            model=LLM_NAME,
            messages=messages,
            temperature=0.2,
            max_tokens=1200,
            extra_body={"thinking": {"type": "disabled"}},
        ),
        timeout=ASSISTANT_RESPONSE_TIMEOUT,
    )
    content = response.choices[0].message.content if response.choices else ""
    if not content or not content.strip():
        raise RuntimeError("LLM returned empty assistant answer")
    return content.strip()


async def chat_with_assistant(
    request: AssistantChatRequest,
    task_manager: Any,
):
    question = request.question.strip()
    context_parts: List[str] = []
    sources: List[AssistantSource] = []
    task: TaskResponse | None = None

    if request.task_id:
        task = task_manager.get_task(request.task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        task_context, task_sources = _task_context_for_assistant(task)
        context_parts.append(task_context)
        sources.extend(task_sources)

    if request.tx_hash:
        tx_review = await review_transaction_hash(TxReviewRequest(tx_hash=request.tx_hash, chain=request.chain))
        tx_review_payload = _model_to_dict(tx_review)
        sources.append(_assistant_source("tx_review", "交易轻量审查", f"tx:{tx_review.tx_hash}", tx_review_payload))
        context_parts.extend(["## 交易轻量审查", _compact_json(tx_review_payload, 3800)])

    knowledge_context, knowledge_sources = _knowledge_context_for_assistant(question)
    context_parts.append(knowledge_context)
    sources.extend(knowledge_sources)

    rag_context, rag_sources = _rag_context_for_assistant(question)
    if rag_context:
        context_parts.append(rag_context)
        sources.extend(rag_sources)

    if not context_parts:
        context_parts.append("当前没有绑定具体任务或交易，只能基于漏洞知识库做通用解释。")

    messages = _build_assistant_messages(request=request, context="\n\n".join(part for part in context_parts if part))
    suggested_questions = _assistant_suggested_questions(request.scope, bool(task), bool(request.tx_hash))

    try:
        answer = await _call_assistant_llm(messages)
        return AssistantChatResponse(
            answer=answer,
            scope=request.scope,
            model=LLM_NAME,
            sources=sources[:10],
            suggested_questions=suggested_questions,
            used_fallback=False,
        )
    except Exception as exc:
        logger.exception("[Assistant] Failed to generate answer")
        fallback = (
            "取证助手暂时无法调用大模型完成回答，但当前上下文已经整理好。"
            "你可以先查看上方交易审查信号、任务报告和漏洞知识卡；"
            f"本次失败原因：{type(exc).__name__}。"
        )
        return AssistantChatResponse(
            answer=fallback,
            scope=request.scope,
            model=LLM_NAME,
            sources=sources[:10],
            suggested_questions=suggested_questions,
            used_fallback=True,
        )


async def list_vulnerability_types():
    payload = _load_knowledge_file("vulnerability_types.json")
    items = payload if isinstance(payload, list) else payload.get("items", [])
    return {
        "total": len(items) if isinstance(items, list) else 0,
        "items": items if isinstance(items, list) else [],
    }


async def get_vulnerability_type(type_id: str):
    payload = _load_knowledge_file("vulnerability_types.json")
    items = payload if isinstance(payload, list) else payload.get("items", [])
    if not isinstance(items, list):
        raise HTTPException(status_code=500, detail="Invalid vulnerability knowledge format")

    for item in items:
        if item.get("id") == type_id:
            return item
    raise HTTPException(status_code=404, detail="Vulnerability type not found")


async def list_knowledge_cases(
    source: str = Query("curated", pattern="^(curated|generated)$"),
    type_id: str | None = Query(None),
    q: str | None = Query(None),
):
    payload = _load_knowledge_cases_payload(source)
    return _filter_knowledge_cases(payload, type_id=type_id, q=q)


async def get_knowledge_case(
    case_id: str,
    source: str = Query("curated", pattern="^(curated|generated)$"),
):
    payload = _load_knowledge_cases_payload(source)
    items = _filter_knowledge_cases(payload, type_id=None, q=None)["items"]
    for item in items:
        if item.get("case_id") == case_id:
            return item
    raise HTTPException(status_code=404, detail="Knowledge case not found")


async def get_knowledge_summary():
    vulnerabilities = _load_knowledge_file("vulnerability_types.json")
    curated = _load_knowledge_file("cases.json")
    generated = _load_knowledge_file("case_index.generated.json")
    try:
        generated_reports = _load_knowledge_file("generated_reports.json")
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        generated_reports = {"items": []}
    vulnerability_items = vulnerabilities if isinstance(vulnerabilities, list) else vulnerabilities.get("items", [])
    curated_items = curated.get("cases", [])
    external_items = curated.get("external_classic_cases", [])
    generated_items = generated.get("items", [])
    report_items = generated_reports.get("items", []) if isinstance(generated_reports, dict) else []
    return {
        "vulnerability_type_count": len(vulnerability_items) if isinstance(vulnerability_items, list) else 0,
        "curated_case_count": len(curated_items) if isinstance(curated_items, list) else 0,
        "external_case_count": len(external_items) if isinstance(external_items, list) else 0,
        "generated_case_count": len(generated_items) if isinstance(generated_items, list) else 0,
        "platform_report_count": len(report_items) if isinstance(report_items, list) else 0,
        "generated_type_counts": generated.get("type_counts", {}),
        "sources": curated.get("external_learning_sources", []),
    }



def load_persisted_log_events(task_id, dapp_name=None, limit=2000):
    from app.attackpilot import store
    return store.log_page(task_id, limit)["events"]
