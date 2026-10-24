"""Offline review of stored replay artifacts; preview unless --apply is explicit."""
import argparse
import copy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid

from . import settings, store
from .errors import AgentContractError, TenderlyAPIError
from .utils.patch_replay import (
    MAX_ARTIFACT_BYTES, TRACE_SUMMARY_POLICY_VERSION, PatchReplayEvidenceStore,
    _digest, execution_summary, historical_payload, public_context,
    runtime_overrides, validate_historical_header, validate_patch_context,
)
from .utils.replay_validation import validate_simulated_transaction
from .utils.report_evidence import _replay_coverage, report_evidence, render_verification_summary
from .utils.verification import adjudicate_patch_verification, replay_evidence_digest

REVIEWABLE_REASONS = {"patched_trace_unavailable", "patch_revert_not_matched",
                     "patched_trace_format_unsupported", "patched_trace_invalid",
                     "revert_propagation_unproven", "patch_guard_location_unproven",
                     "modified_code_not_reached", "judge_unresolved", "judge_negative_unsubstantiated"}

_INCOMPLETE_WARNING_START = (
    "\n" + "!" * 80 + "\n"
    "⚠️  WARNING: ANALYSIS INCOMPLETE / UNVERIFIED REPORT  ⚠️\n"
    "The system failed to verify the fix within the allowed turns.\n"
    "The following report is generated based on the LAST HYPOTHESIS.\n"
    "It may contain inaccurate root causes or ineffective patches.\n"
    "Final Status: "
)
_INCOMPLETE_WARNING = re.compile(
    re.escape(_INCOMPLETE_WARNING_START) + r"([^\r\n]{1,16384})" + re.escape("\n" + "!" * 80 + "\n\n"))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _artifact(task_root, reference, role, transaction_hash):
    _require(isinstance(reference, dict), "Missing artifact reference")
    digest = reference.get("sha256")
    _require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest), "Invalid artifact digest")
    relative = Path("cache/patch_replay/artifacts") / f"{digest}.json"
    _require(reference.get("relative_path") == relative.as_posix(), "Unexpected artifact path")
    path = task_root / relative
    _require(path.resolve() == path, "Artifact path must not follow symlinks")
    with path.open("rb") as handle:
        raw = handle.read(MAX_ARTIFACT_BYTES + 1)
    _require(len(raw) <= MAX_ARTIFACT_BYTES and hashlib.sha256(raw).hexdigest() == digest,
             "Artifact bytes do not match SHA256")
    record = json.loads(raw)
    _require(isinstance(record, dict), "Invalid artifact record")
    _require(type(record.get("schema_version")) is int and record["schema_version"] == 1
             and record.get("role") == role
             and record.get("original_transaction_hash") == transaction_hash, "Artifact identity mismatch")
    request = record.get("request")
    _require(isinstance(request, dict) and record.get("request_digest") == _digest(request)
             and record["request_digest"] == reference.get("request_digest"), "Request digest mismatch")
    _require(isinstance(record.get("response"), dict), "Missing artifact response")
    return request, record["response"]


def _legacy_verified_prefix(original):
    """Match the former deterministic display, only after raw-artifact review.

    This is not an evidence upgrade: it reconstructs the exact old prefix so
    it can be replaced after the current gate has independently passed.
    Unknown older report formats must still be reviewed manually.
    """
    coverage = _replay_coverage(original.get("coverage"))
    dimensions = {
        "attack_interception": {"status": "passed"},
        "normal_regression": {"status": "not_run"},
        "profit": {"status": "unavailable", "usd": None},
    }
    _require(coverage is not None and coverage["intercepted"] > 0 and coverage["unresolved"] == 0
             and original.get("dimensions") == dimensions, "Unsupported legacy verification display")
    return render_verification_summary({
        "verification": original, "label": "触发交易拦截通过", "evidence_trusted": True,
    })


def _stored_report_parts(report, prefix, *, allow_warning=False):
    """Accept the canonical summary or its exact generated incomplete wrapper."""
    _require(isinstance(report, str), "Missing stored report")
    if report.startswith(prefix + "\n\n"):
        return "", report[len(prefix):]
    match = _INCOMPLETE_WARNING.match(report) if allow_warning else None
    _require(match is not None and not any(ord(char) < 32 or ord(char) == 127 for char in match[1]),
             "Report prefix does not match stored verification")
    remaining = report[match.end():]
    _require(remaining.startswith(prefix + "\n\n"), "Report prefix does not match stored verification")
    return report[:match.end()], remaining[len(prefix):]


def _stable_sequence_pairs(pairs):
    """Derived parser fields may change; execution identities and effects may not."""
    stable = copy.deepcopy(pairs)
    for pair in stable:
        _require(isinstance(pair, dict), "Invalid sequential replay pair")
        for role in ("control", "patched"):
            execution = pair.get(role)
            _require(isinstance(execution, dict), "Missing sequential replay execution")
            for field in ("trace", "security_observations", "native_balance_change"):
                execution.pop(field, None)
    return stable


def _refresh_sequential_replay(replay, original, patches, root):
    """Reparse immutable bundle responses without replacing their recorded scope."""
    from .utils.sequence_replay import resolve_sequence, sequence_pairs
    from .utils.patch_replay import validate_sequential_evidence
    from .utils.security_checks import plan_digest, validate_plan_authority, validate_verification_plan
    from .workflow import _validate_runtime_artifacts

    _require(original.get("schema_version") == 2 and original.get("evidence_version") == 2
             and original.get("execution_evidence_validated") is True
             and original.get("scope") in {"declared_attack_chain", "declared_attack_chain_and_normal_cases"}
             and replay.get("scope") == "sequential_attack_and_regression"
             and original.get("replay_evidence_sha256") == replay_evidence_digest(replay),
             "Sequential replay is not bound to the stored verification")
    _require(original.get("replay_completed") is True and replay.get("status") == "completed",
             "Offline sequential review requires complete paired executions")
    _require(isinstance(patches, str) and hashlib.sha256(patches.encode()).hexdigest()
             == replay.get("applied_patch_sha256") == original.get("applied_patch_sha256")
             and replay.get("verification_plan_sha256") == original.get("verification_plan_sha256"),
             "Sequential replay patch or plan binding mismatch")
    evidence_store = PatchReplayEvidenceStore(root / "cache")
    normal = replay.get("normal_regression")
    cases = normal.get("cases") if isinstance(normal, dict) else None
    _require(isinstance(cases, list), "Missing sequential regression scope")
    addresses, plan = replay["patched_addresses"], replay.get("verification_plan")
    _require(isinstance(plan, dict) and validate_verification_plan(plan) == plan
             and plan_digest(plan) == replay.get("verification_plan_sha256")
             and validate_plan_authority(plan, cache_root=root / "cache"),
             "Sequential verification plan or source evidence is invalid")
    artifact_hashes = []
    for group in [replay, *cases]:
        _require(isinstance(group, dict) and isinstance(group.get("sequence"), dict)
                 and isinstance(group.get("transactions"), list) and group["transactions"],
                 "Invalid sequential execution group")
        sequence, pairs = group["sequence"], group["transactions"]
        hashes = sequence.get("ordered_transaction_hashes")
        _require(isinstance(hashes, list) and hashes
                 and all(isinstance(tx, str) and re.fullmatch(r"0x[0-9a-f]{64}", tx) for tx in hashes),
                 "Invalid sequential transaction order")
        originals = resolve_sequence(evidence_store, [{"hash": tx} for tx in hashes], int(plan["network_id"]))
        bundles, artifacts, overrides = {}, {}, None
        for role in ("control", "patched"):
            descriptor = sequence.get(role)
            _require(isinstance(descriptor, dict), "Missing sequential execution descriptor")
            reference = descriptor.get("artifact")
            request, response = _artifact(root, reference, role, hashes[0])
            if role == "patched":
                simulations = request.get("simulations")
                objects = (simulations[0].get("state_objects") if isinstance(simulations, list)
                           and simulations and isinstance(simulations[0], dict) else None)
                _require(isinstance(objects, dict) and objects
                         and all(isinstance(item, dict) and set(item) == {"code"} for item in objects.values()),
                         "Sequential replay may override only runtime code")
                overrides = runtime_overrides({address: item["code"] for address, item in objects.items()})
                _require(sorted(overrides) == addresses, "Sequential patched address scope mismatch")
            bundles[role], artifacts[role] = response.get("simulation_results"), reference
            artifact_hashes.append(reference["sha256"])
        rebuilt = sequence_pairs(originals, bundles, artifacts, addresses, overrides, plan)
        _require(_stable_sequence_pairs(pairs) == _stable_sequence_pairs(rebuilt),
                 "Sequential execution identity or effects changed from immutable evidence")
        group["transactions"] = rebuilt
    validation = validate_sequential_evidence(replay, cache_root=root / "cache")
    _require(isinstance(validation, dict) and validation.get("status") == "validated",
             "Sequential raw artifacts failed validation")
    integrity = replay.get("runtime_integrity")
    _require(isinstance(integrity, dict) and integrity.get("status") == "validated"
             and integrity.get("applied_patch_sha256") == replay.get("applied_patch_sha256")
             and isinstance(integrity.get("contracts"), dict)
             and set(integrity["contracts"]) == set(addresses),
             "Missing sequential runtime integrity evidence")
    for contract in integrity["contracts"].values():
        _require(isinstance(contract, dict) and contract.get("storage_layout_checked") is True
                 and contract.get("immutable_checked") is True
                 and all(isinstance(contract.get(field), str) and re.fullmatch(r"[0-9a-f]{64}", contract[field])
                         for field in ("original_runtime_sha256", "original_compiled_runtime_sha256",
                                       "patched_runtime_sha256")), "Invalid sequential runtime integrity evidence")
    _validate_runtime_artifacts(replay, integrity["contracts"], task_root=root)
    return artifact_hashes


def revalidate_result(result: dict, task_root: Path | str, *, refresh_unverified: bool = False) -> dict:
    """Return an independently checked revision of saved execution evidence.

    No files, database records, clocks, models, or remote services are modified.
    Invalid evidence raises ValueError. An explicit refresh may replace the
    diagnosis of an already unverified result; it never downgrades a verified
    record silently or manufactures the evidence needed to upgrade one.
    """
    _require(isinstance(result, dict) and isinstance(result.get("verification"), dict),
             "Missing verification record")
    original = result["verification"]
    legacy_verified = (
        type(original.get("schema_version")) is int and original["schema_version"] == 2
        and type(original.get("evidence_version")) is int and original["evidence_version"] == 1
        and original.get("status") == "verified" and original.get("evidence_validated") is True
        and original.get("reason_code") == "attack_path_intercepted"
        and original.get("scope") == "attack_path_only" and original.get("replay_completed") is True
        and original.get("judge_verdict") == "VERIFIED"
        and "replay_evidence_sha256" not in original and "applied_patch_sha256" not in original
    )
    _require(legacy_verified or original.get("status") == "unverified"
             and original.get("reason_code") in REVIEWABLE_REASONS, "Result is outside this review scope")
    revised = copy.deepcopy(result)
    replay = revised.get("replay_evidence")
    _require(isinstance(replay, dict), "Missing replay evidence")
    pairs, addresses = replay.get("transactions"), replay.get("patched_addresses")
    _require(isinstance(pairs, list) and 1 <= len(pairs) <= 4, "Invalid replay pairs")
    _require(isinstance(addresses, list) and bool(addresses)
             and all(isinstance(address, str) and re.fullmatch(r"0x[0-9a-f]{40}", address)
                     for address in addresses)
             and addresses == sorted(set(addresses)), "Invalid patch addresses")
    coverage = original.get("coverage")
    _require(isinstance(coverage, dict), "Missing required trigger scope")
    coverage_required = coverage.get("required_trigger_transaction_hashes")
    _require(isinstance(coverage_required, list) and coverage_required
             and replay.get("required_trigger_transaction_hashes") == coverage_required,
             "Required trigger scope is missing or inconsistent")
    root = Path(task_root).resolve()
    evidence_store = PatchReplayEvidenceStore(root / "cache")
    artifact_hashes = []
    sequential = replay.get("schema_version") == 2
    if sequential:
        artifact_hashes = _refresh_sequential_replay(replay, original, revised.get("applied_patches"), root)
    for pair in ([] if sequential else pairs):
        _require(isinstance(pair, dict) and isinstance(pair.get("context"), dict)
                 and isinstance(pair.get("comparison"), dict), "Invalid replay pair")
        tx_hash = pair["original_transaction_hash"]
        context, transaction = evidence_store.original_context(tx_hash, int(pair["context"]["network_id"]))
        _require(pair["context"] == public_context(context, transaction)
                 and pair["patched_addresses"] == addresses, "Historical pair context mismatch")
        for role in ("control", "patched"):
            previous = pair.get(role)
            _require(isinstance(previous, dict), "Missing replay execution")
            reference = previous.get("artifact")
            request, response = _artifact(root, reference, role, tx_hash)
            overrides = None
            if role == "patched":
                objects = request["simulations"][0]["state_objects"]
                _require(isinstance(objects, dict) and all(isinstance(item, dict) for item in objects.values()),
                         "Invalid runtime overrides")
                overrides = runtime_overrides({address: item["code"] for address, item in objects.items()})
                _require(sorted(overrides) == addresses, "Patched address scope mismatch")
                integrity = replay.get("runtime_integrity")
                if integrity is not None:
                    _require(isinstance(integrity, dict) and integrity.get("status") == "validated"
                             and integrity.get("applied_patch_sha256") == replay.get("applied_patch_sha256")
                             and isinstance(integrity.get("contracts"), dict)
                             and set(integrity["contracts"]) == set(addresses), "Runtime integrity identity mismatch")
                    for address, override in overrides.items():
                        contract = integrity["contracts"][address]
                        _require(isinstance(contract, dict) and contract.get("patched_runtime_sha256")
                                 == hashlib.sha256(bytes.fromhex(override["code"][2:])).hexdigest(),
                                 "Runtime integrity digest mismatch")
            _require(request == historical_payload(context, transaction, overrides), "Historical request mismatch")
            validate_historical_header(context, response)
            if role == "control":
                baseline = validate_simulated_transaction(context, response)
                _require(previous.get("baseline_validation") == baseline, "Original receipt evidence changed")
            else:
                validate_patch_context(context, response)
            summary = execution_summary(response, reference, addresses, runtime_codes=(
                {address: item['code'] for address, item in overrides.items()} if overrides else None))
            if role == "control":
                summary.update(baseline_validation=baseline, control_validation="validated")
            pair[role] = summary
            artifact_hashes.append(reference["sha256"])
        pair["comparison"].update(
            attack_transaction_reverted=pair["control"]["status"] == "success" and pair["patched"]["status"] == "revert",
            logs_changed=pair["control"]["logs"]["ordered_logs_sha256"] != pair["patched"]["logs"]["ordered_logs_sha256"],
            gas_changed=pair["control"]["gas_used"] != pair["patched"]["gas_used"],
        )
    judge = {"verdict": original.get("judge_verdict")}
    verification = (adjudicate_patch_verification(judge, replay, revised["applied_patches"], cache_root=root / "cache")
                    if sequential else adjudicate_patch_verification(judge, replay, revised["applied_patches"]))
    verified = verification.get("status") == "verified" and verification.get("evidence_validated") is True
    _require(verified or (refresh_unverified and original.get("status") == "unverified"
                         and verification.get("status") == "unverified"),
             f"Offline evidence remains unverified: {verification.get('reason_code')}")
    if verified and not sequential:
        from .workflow import _validate_runtime_artifacts
        integrity = replay.get("runtime_integrity")
        _require(isinstance(integrity, dict) and isinstance(integrity.get("contracts"), dict),
                 "Missing runtime integrity evidence")
        _validate_runtime_artifacts(replay, integrity["contracts"], task_root=root)
    revised["verification"] = {**revised["verification"], **verification}
    old_prefix = (_legacy_verified_prefix(original) if legacy_verified else
                  render_verification_summary(report_evidence(
                      {**judge, "verification": original}, result["replay_evidence"])))
    warning, suffix = _stored_report_parts(result["report"], old_prefix,
                                          allow_warning=original.get("status") == "unverified")
    new_prefix = render_verification_summary(report_evidence({**judge, "verification": revised["verification"]}, replay))
    note = ("复核说明：已重新校验原始回执、已保存的对照与补丁回放记录，更新当前证据判定与缺口，"
            "未发起新模拟或模型调用。以下分析正文保留原始记录；其中涉及旧验证状态的表述，以本次复核状态为准。")
    archived_warning = "\n\n### 原始运行提示（历史记录）\n" + warning.rstrip("\n") if warning else ""
    revised["report"] = new_prefix + "\n\n> " + note + archived_warning + suffix
    revised["evidence_revision"] = {
        "method": "offline_immutable_replay_artifacts", "trace_policy_version": TRACE_SUMMARY_POLICY_VERSION,
        "previous_status": original["status"], "previous_reason_code": original["reason_code"],
        "diagnosis_only": not verified,
        "upgraded_legacy_binding": legacy_verified, "artifact_sha256": artifact_hashes,
        "source_result_canonical_sha256": _digest(result),
    }
    return revised


def review_task(task_id: str, *, apply: bool = False, refresh_unverified: bool = False) -> dict:
    """Preview one persisted task, or atomically apply an audited revision."""
    task_id = str(uuid.UUID(task_id))
    with closing(sqlite3.connect(settings.DATABASE_PATH.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    _require(row is not None and row["status"] == "completed" and not row["is_demo"], "Only completed non-demo tasks can be reviewed")
    old_result = json.loads(row["result"])
    _require(row["final_report"] == old_result.get("report"), "Stored report and result disagree")
    root = store.task_dir(task_id)
    revised = revalidate_result(old_result, root, refresh_unverified=refresh_unverified)
    preview = {"task_id": task_id, "applied": False, "verification": revised["verification"],
               "revision": revised["evidence_revision"]}
    if not apply:
        return preview
    raw = row["result"].encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    relative = Path("evidence-revisions") / f"{digest}.json"
    revised["evidence_revision"].update(original_result_sha256=digest,
                                        original_result_path=relative.as_posix(), reviewed_at=store.now())
    with closing(sqlite3.connect(settings.DATABASE_PATH.as_uri() + "?mode=rw", uri=True, timeout=15)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute(
            "UPDATE tasks SET result=?,final_report=? WHERE task_id=? AND status='completed' AND is_demo=0 "
            "AND result=? AND final_report IS ?",
            (json.dumps(revised, ensure_ascii=False, allow_nan=False), revised["report"], task_id, row["result"], row["final_report"]),
        )
        _require(changed.rowcount == 1, "Task changed during review; nothing applied")
        backup = root / relative
        _require(backup.resolve() == backup, "Audit backup must not follow symlinks")
        backup.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=backup.parent, prefix=".revision-", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, backup)
            except FileExistsError:
                _require(backup.read_bytes() == raw, "Existing audit backup does not match original result")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        directory_fd = os.open(backup.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        task = store._task(db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())
        store._event(db, task_id, {"type": "TASK_FINAL", **store.public_task(task)})
    return {**preview, "applied": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--apply", action="store_true", help="Apply the audited review and preserve the original result")
    parser.add_argument("--refresh-unverified", action="store_true",
                        help="Allow an already unverified task to retain that status with an updated evidence diagnosis")
    args = parser.parse_args()
    try:
        print(json.dumps(review_task(args.task_id, apply=args.apply,
                                     refresh_unverified=args.refresh_unverified), ensure_ascii=False, indent=2))
    except (ValueError, KeyError, TypeError, IndexError, OSError, sqlite3.Error, TenderlyAPIError, AgentContractError) as exc:
        parser.exit(1, f"Review rejected: {exc}\n")


if __name__ == "__main__":
    main()
