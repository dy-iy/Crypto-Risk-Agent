import { VERIFICATION_POLICY_VERSION, type Task } from "../types";

export type PatchVerificationStatus =
  | "not_run"
  | "skipped"
  | "blocked"
  | "error"
  | "unverified"
  | "failed"
  | "verified"
  | "archived";

export interface PatchVerificationPresentation {
  status: PatchVerificationStatus;
  label: string;
  headerLabel: string;
  title: string;
  description: string;
  nextStep?: string;
  color: "success" | "error" | "warning" | "default";
}

export interface PatchVerificationDimension {
  key: "attack_interception" | "normal_regression" | "profit";
  label: string;
  value: string;
}

export interface PatchCompileDiagnostic {
  target: string;
  compilerVersion?: string;
  description: string;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function replayCoverage(value: unknown) {
  const coverage = asRecord(value);
  if (coverage?.mode !== "independent_historical_transaction_pairs" || coverage.sequence_replay_verified !== false) return null;
  const hashes = ["intercepted_transaction_hashes", "unaffected_transaction_hashes", "unresolved_transaction_hashes"] as const;
  const groups = hashes.map(key => coverage[key]);
  if (groups.some(group => !Array.isArray(group) || group.some(hash => typeof hash !== "string" || !/^0x[0-9a-f]{64}$/i.test(hash)))) return null;
  const addresses = coverage.modified_addresses;
  if (!Array.isArray(addresses) || !addresses.length
    || addresses.some(address => typeof address !== "string" || !/^0x[0-9a-f]{40}$/i.test(address))) return null;
  const all = (groups as string[][]).flat().map(hash => hash.toLowerCase());
  if (new Set(all).size !== all.length) return null;
  return {
    intercepted: (groups[0] as string[]).length,
    unaffected: (groups[1] as string[]).length,
    unresolved: (groups[2] as string[]).length,
  };
}

const reasonDescriptions: Record<string, string> = {
  missing_source: "缺少可用源码，已停止补丁生成与回放。",
  source_fetch_failed: "源码获取失败，请检查区块浏览器连接或稍后重试。",
  source_not_verified: "目标合约尚未提供已验证源码，无法生成可验证补丁。",
  no_patch_targets: "没有可修改的源码目标，无法执行补丁回放。",
  invalid_fix_report: "修复信息不完整，无法执行补丁回放。",
  analysis_report_invalid: "报告缺失或与输入交易、结构化证据不一致，本次分析未通过结果检查。",
  unmapped_source: "无法将修复目标对应到源码，已停止补丁生成。",
  unmappable_patch_target: "无法将修复目标对应到源码，已停止补丁生成。",
  original_compile_failed: "原始源码编译失败，无法建立验证基准。",
  compiler_unavailable: "缺少匹配的 Solidity 编译器，尚未开始补丁回放。",
  original_runtime_mismatch: "原始源码编译产物与历史链上代码不匹配，无法建立可信的补丁验证基准。",
  storage_layout_unavailable: "无法取得原始合约存储布局，尚不能确认补丁替换代码与历史状态兼容。",
  storage_layout_changed: "补丁改变了合约存储布局，不能将状态不兼容引起的回滚认定为攻击被拦截。",
  immutable_layout_mismatch: "补丁与原合约的不可变变量布局不兼容，不能确认回滚由补丁校验触发。",
  constructor_or_immutable_changed: "补丁改变了构造器或不可变变量声明，初始化条件与历史合约不一致，无法据此确认拦截效果。",
  patch_runtime_unchanged: "源码改动未改变实际执行代码，不能将注释或元数据变化视为有效补丁。",
  missing_runtime_bytecode: "缺少原始合约字节码，无法执行补丁回放。",
  patch_source_lookup_error: "源码读取异常，尚未执行补丁回放。",
  patch_preparation_error: "补丁准备过程异常，尚未执行回放。",
  patch_generation_pending: "正在生成补丁，尚未执行回放。",
  patch_generation_error: "补丁生成异常，尚未执行回放。",
  patch_application_failed: "补丁未能应用到源码，尚未执行回放。",
  patch_compile_error: "补丁编译过程异常，尚未执行回放。",
  patch_compile_failed: "补丁编译未通过，尚未执行回放。",
  runtime_generation_error: "补丁字节码生成异常，尚未执行回放。",
  runtime_generation_failed: "未生成完整补丁字节码，尚未执行回放。",
  runtime_generation_request_limit: "补丁字节码生成已达到请求上限，未继续执行验证。",
  duplicate_patch: "补丁与此前尝试重复，已停止重复生成与回放。",
  historical_runtime_conflict: "同一合约在相关历史交易中的代码版本不一致，已停止混用不同版本。",
  historical_runtime_unavailable: "缺少可用的历史合约字节码，未使用最新字节码代替。",
  historical_runtime_context_mismatch: "历史字节码来源与交易、网络或回执基准不匹配，已停止验证。",
  no_attack_evidence: "未筛出需要复盘的攻击证据，未执行补丁验证；不能据此认定交易安全。",
  no_attack_hypothesis: "分析证据不足，尚未形成可验证的攻击假设，未执行补丁验证。",
  replay_preparation_error: "交易回放准备异常，尚未确认补丁效果。",
  no_replay_transactions: "缺少可回放的原始攻击交易，无法执行验证。",
  invalid_replay_response: "回放服务未返回有效执行证据，尚未确认补丁效果。",
  replay_pending: "正在执行补丁回放，尚未确认验证结果。",
  replay_completed_pending_review: "补丁回放已完成，正在判定补丁效果。",
  baseline_unavailable: "缺少原始交易校验数据，无法确认回放基准。",
  baseline_inconsistent: "模拟结果与真实交易不一致，已停止后续验证。",
  replay_service_error: "回放服务异常，尚未得到有效验证结果。",
  replay_timeout: "补丁回放超时，尚未得到完整验证结果。",
  judge_error: "验证结果判定异常，尚未确认补丁效果。",
  judge_unresolved: "现有回放证据不足以确认补丁效果。",
  ineffective_patch: "回放结果表明补丁未能阻止本次攻击。",
  wrong_root_cause: "回放结果未能支持当前根因与修复方案。",
  broken_logic: "回放发现补丁影响了正常业务逻辑。",
  turn_limit_reached: "已达到修复尝试上限，尚未确认有效补丁。",
  replay_evidence_missing: "缺少完整回放记录，无法确认补丁效果。",
  module_disabled: "本次任务未启用补丁验证。",
  verification_disabled: "本次任务未启用补丁验证。",
  execution_evidence_invalid: "回放执行证据不完整或存在冲突，无法确认补丁效果。",
  replay_evidence_invalid: "回放执行证据不完整或存在冲突，无法确认补丁效果。原始报告中的验证表述不代表当前已核实状态。",
  replay_request_limit: "本任务已达到补丁回放请求上限，尚未确认有效补丁。",
  replay_transaction_limit: "本任务攻击交易超过配对回放数量上限，尚未执行验证。",
  structured_replay_evidence_missing: "缺少结构化对照回放证据，尚未确认补丁效果。",
  paired_replay_incomplete: "原版对照或补丁回放尚未完整完成。",
  applied_patch_evidence_mismatch: "实际补丁与回放证据不匹配，无法确认结果。原始报告中的验证表述不代表当前已核实状态。",
  patch_target_missing: "实际源码修改地址与回放替换地址不匹配，无法确认补丁效果。",
  unaffected_execution_mismatch: "未触及修改代码的独立回放仍有无法解释的结果差异，无法确认补丁效果。",
  control_evidence_mismatch: "原版对照与真实回执不一致，无法确认验证基准。",
  patch_interception_not_established: "现有证据无法确认攻击已被阻止。",
  required_trigger_replay_missing: "缺少应验证的源码触发交易回放；其他交易的回放不能代替该项验证。",
  modified_code_not_reached: "本轮回放未观察到实际修改代码，需要重新定位或补选触发交易；不能据此判断补丁有效或失效。",
  duplicate_replay_transaction: "回放记录包含重复交易，无法确认实际验证范围。",
  patch_artifact_missing: "缺少可追溯的独立补丁回放响应记录，无法核对执行结果。",
  patched_events_unresolved: "补丁回放的回滚事件记录缺失或不一致，无法确认实际拦截结果。",
  patched_trace_unavailable: "缺少完整补丁执行轨迹，无法确认回滚位置。",
  patched_trace_format_unsupported: "回放轨迹使用了当前尚未支持的格式，暂时无法核实补丁效果。",
  patched_trace_invalid: "回放轨迹的结构或执行状态存在矛盾，暂时无法核实补丁效果。",
  patch_revert_not_matched: "回滚原因尚未与实际修改的校验对应。",
  patch_guard_location_unproven: "缺少执行位置与实际修改校验的对应证据，无法确认回滚由补丁触发；错误文案相同不能证明执行了新增校验。",
  revert_propagation_unproven: "缺少子调用失败导致上层回滚的因果证据，无法确认最终回滚由补丁校验触发。",
  modified_guard_missing: "实际补丁缺少可直接核实的回滚校验。",
  judge_negative_unsubstantiated: "模型判断缺少可核实的反证，尚未确认补丁效果。",
  interception_unconfirmed: "回放证据尚不能确认攻击路径被补丁阻止。",
};

function describeReason(code: string): string | undefined {
  if (Object.hasOwn(reasonDescriptions, code)) return reasonDescriptions[code];
  if (/^tenderly_(unauthorized|unauthenticated|authentication_failed|invalid_access_key|invalid_api_key)$/.test(code)) {
    return "Tenderly 认证失败，尚未得到有效验证结果。";
  }
  if (/^tenderly_(quota_exceeded|insufficient_quota|monthly_limit_exceeded|limit_exceeded|payment_required|simulation_limit_exceeded)$/.test(code)) {
    return "Tenderly 可用额度不足，尚未得到有效验证结果。";
  }
  if (/^tenderly_(insufficient_permissions|forbidden)$/.test(code)) {
    return "Tenderly 访问权限不足，尚未得到有效验证结果。";
  }
  if (/^tenderly_(too_many_requests|rate_limit_exceeded)$/.test(code)) {
    return "Tenderly 请求受到限流，尚未得到有效验证结果。";
  }
  if (/^(tenderly|preconditions|compile|patch_generation|runtime_generation|replay_preparation|replay)_timeout$/.test(code)) {
    return "验证过程超时，尚未得到完整验证结果。";
  }
  return undefined;
}

const unverifiedReasons = {
  evidence: [
    "no_attack_evidence", "no_attack_hypothesis", "no_replay_transactions", "baseline_unavailable",
    "baseline_inconsistent", "replay_evidence_missing", "structured_replay_evidence_missing",
    "paired_replay_incomplete", "applied_patch_evidence_mismatch", "patch_target_missing",
    "unaffected_execution_mismatch", "control_evidence_mismatch", "patch_interception_not_established",
    "required_trigger_replay_missing", "modified_code_not_reached", "patch_artifact_missing",
    "patched_events_unresolved", "patched_trace_unavailable", "patch_revert_not_matched",
    "patch_guard_location_unproven", "revert_propagation_unproven",
    "historical_runtime_context_mismatch", "interception_unconfirmed",
    "original_runtime_mismatch", "storage_layout_changed", "immutable_layout_mismatch", "constructor_or_immutable_changed", "patch_runtime_unchanged",
  ],
  capability: [
    "missing_source", "source_not_verified", "no_patch_targets", "unmapped_source", "unmappable_patch_target",
    "missing_runtime_bytecode", "historical_runtime_unavailable", "historical_runtime_conflict",
    "modified_guard_missing", "runtime_generation_request_limit", "replay_request_limit",
    "replay_transaction_limit", "turn_limit_reached", "duplicate_patch",
    "compiler_unavailable",
    "storage_layout_unavailable",
  ],
  error: [
    "invalid_fix_report", "analysis_report_invalid", "original_compile_failed", "source_fetch_failed", "patch_source_lookup_error", "patch_preparation_error",
    "patch_generation_error", "patch_application_failed", "patch_compile_error", "patch_compile_failed",
    "runtime_generation_error", "runtime_generation_failed", "replay_preparation_error",
    "invalid_replay_response", "replay_service_error", "replay_timeout", "judge_error",
    "execution_evidence_invalid", "replay_evidence_invalid", "duplicate_replay_transaction",
    "patched_trace_format_unsupported", "patched_trace_invalid",
  ],
  review: ["judge_unresolved", "judge_negative_unsubstantiated", "ineffective_patch", "wrong_root_cause", "broken_logic"],
};

const reasonNextSteps: Record<string, string> = {
  compiler_unavailable: "补齐合约所需的准确 Solidity 编译器版本后，再运行补丁验证。",
  original_compile_failed: "核对原始源码、依赖和编译设置，修复编译问题后再运行验证。",
  analysis_report_invalid: "核对输入交易与分析记录，修复报告不一致后重新运行分析。",
  original_runtime_mismatch: "核对交易发生时的合约源码、编译设置及部署参数，匹配历史链上代码后再验证。",
  storage_layout_unavailable: "补齐对应编译器的存储布局信息，确认历史状态兼容后再验证。",
  storage_layout_changed: "修订补丁以保留原有状态变量的槽位、类型和布局，再运行回放。",
  immutable_layout_mismatch: "保留原有不可变变量布局及部署值，再生成补丁代码进行回放。",
  constructor_or_immutable_changed: "保留历史合约的构造器及不可变变量声明，只修改目标业务校验后再验证。",
  patch_runtime_unchanged: "修订补丁使目标业务校验实际改变执行代码，再进行编译和回放验证。",
  patched_trace_unavailable: "补齐完整执行轨迹后，重新核对补丁触发与回滚位置。",
  patched_trace_format_unsupported: "适配执行轨迹格式后，用已有回放记录重新核验。",
  patched_trace_invalid: "复核原始执行轨迹，确认结构和执行状态一致后再核验。",
  required_trigger_replay_missing: "根据源码定位补齐触发交易，再运行补丁验证。",
  modified_code_not_reached: "重新定位触发交易，确认回放执行到实际修改的代码。",
  missing_source: "补齐对应历史版本的合约源码后，再生成并验证补丁。",
  source_fetch_failed: "恢复区块浏览器连接或稍后重试源码获取，再运行补丁验证。",
  source_not_verified: "补齐并核对对应历史版本的已验证源码后，再生成并验证补丁。",
  historical_runtime_unavailable: "补齐交易发生时的合约代码后，再运行验证。",
  patch_revert_not_matched: "核对回滚位置是否对应补丁校验，再判断拦截效果。",
  patch_guard_location_unproven: "补齐实际补丁的源码映射与回滚指令位置，确认执行到新增或修改的校验后再核验。",
  revert_propagation_unproven: "补齐子调用返回与上层回滚之间的执行证据，核实错误包装的因果关系后再核验。",
};

function presentUnverified(reasonCode: string, reason: string | undefined): PatchVerificationPresentation {
  let presentation: PatchVerificationPresentation = {
    status: "unverified", label: "尚未确认", headerLabel: "验证尚未确认", color: "default",
    title: "补丁效果尚未确认",
    description: reason ?? "尚无足够回放证据确认补丁效果。",
  };
  if (unverifiedReasons.evidence.includes(reasonCode)) {
    presentation = { ...presentation, label: "证据不足", headerLabel: "验证证据不足", title: "补丁验证证据不足",
      nextStep: "补齐缺失的执行记录或原始交易对照后，再确认补丁效果。" };
  } else if (unverifiedReasons.capability.includes(reasonCode)) {
    presentation = { ...presentation, label: "无法验证", headerLabel: "暂时无法验证", title: "补丁暂时无法验证",
      nextStep: "补齐验证所需的源码、历史数据或执行条件后，再运行验证。" };
  } else if (unverifiedReasons.error.includes(reasonCode)
    || (reason !== undefined && /^(tenderly_|.*_timeout$)/.test(reasonCode))) {
    presentation = { ...presentation, label: "验证异常", headerLabel: "验证异常", title: "补丁验证异常", color: "warning",
      nextStep: "修复验证服务或执行记录的问题后，再重试验证。" };
  } else if (unverifiedReasons.review.includes(reasonCode)) {
    presentation = { ...presentation, label: "判定待复核", headerLabel: "验证判定待复核", title: "补丁验证判定待复核",
      description: "现有判定缺少足够的执行证据支持，尚不能确认补丁效果或推翻根因。",
      nextStep: "对照原始与补丁回放记录复核判定，补充可直接核实的证据。" };
  }
  if (Object.hasOwn(reasonNextSteps, reasonCode)) presentation.nextStep = reasonNextSteps[reasonCode];
  return presentation;
}

export function getPatchVerificationPresentation(task: Task | null): PatchVerificationPresentation {
  if (task?.is_demo) {
    return {
      status: "archived", label: "历史记录", headerLabel: "历史验证记录", color: "default",
      title: "历史补丁验证记录",
      description: "以下证据来自原项目归档，当前环境尚未重新执行补丁回放。",
    };
  }

  const result = asRecord(task?.result);
  const verification = asRecord(result?.verification);
  const replay = asRecord(result?.replay_evidence);
  const status = verification?.status;
  const reasonCode = typeof verification?.reason_code === "string" ? verification.reason_code : "";
  let reason = describeReason(reasonCode);
  const nextStep = Object.hasOwn(reasonNextSteps, reasonCode) ? reasonNextSteps[reasonCode] : undefined;
  const hasCompletedReplay = verification?.schema_version === 2 && verification?.replay_completed === true;
  const dimensions = asRecord(verification?.dimensions);
  const interception = asRecord(dimensions?.attack_interception);
  const coverage = replayCoverage(verification?.coverage);
  if (reasonCode === "patch_interception_not_established" && coverage
    && coverage.intercepted === 0 && coverage.unaffected > 0 && coverage.unresolved === 0
    && verification?.replay_completed === true) {
    reason = `本轮已记录 ${coverage.unaffected} 笔未触及实际修改代码的独立历史回放，尚未验证真正触发补丁校验的交易；不能据此判断补丁有效或失效。`;
  }
  if (reasonCode === "required_trigger_replay_missing") {
    const rawCoverage = asRecord(verification?.coverage);
    const required = rawCoverage?.required_trigger_transaction_hashes;
    const pairs = replay?.schema_version === 1 && Array.isArray(replay.transactions) ? replay.transactions : [];
    const recorded = new Set(pairs.map(pair => asRecord(pair)?.original_transaction_hash)
      .filter((hash): hash is string => typeof hash === "string").map(hash => hash.toLowerCase()));
    if (Array.isArray(required) && required.length > 0 && required.every(hash => typeof hash === "string" && /^0x[0-9a-f]{64}$/i.test(hash))) {
      const missing = [...new Set((required as string[]).map(hash => hash.toLowerCase()))].filter(hash => !recorded.has(hash));
      if (missing.length > 0) reason = `缺少 ${missing.length} 笔应验证的源码触发交易回放（${missing.map(hash => `${hash.slice(0, 10)}…${hash.slice(-6)}`).join("、")}）；已回放的其他交易即使执行成功，也不能代替该项验证。`;
    }
  }
  const validCoverage = coverage !== null && coverage.intercepted > 0 && coverage.unresolved === 0;
  // The API recomputes the canonical replay digest before publishing
  // evidence_validated. Reject old or incomplete envelopes here as well;
  // the browser must not reimplement Python's canonical JSON encoding.
  const boundReplay = replay?.schema_version === 1 && replay.status === "completed"
    && typeof verification?.replay_evidence_sha256 === "string" && /^[0-9a-f]{64}$/.test(verification.replay_evidence_sha256)
    && typeof verification?.applied_patch_sha256 === "string" && /^[0-9a-f]{64}$/.test(verification.applied_patch_sha256)
    && verification.applied_patch_sha256 === replay.applied_patch_sha256;
  const hasValidatedEvidence = hasCompletedReplay && verification?.replay_attempted === true
    && verification?.evidence_version === 1 && verification?.evidence_validated === true
    && verification?.verification_policy_version === VERIFICATION_POLICY_VERSION
    && verification?.scope === "attack_path_only" && validCoverage && boundReplay
    && verification?.judge_verdict === "VERIFIED";

  if (status === "verified" && hasValidatedEvidence && interception?.status === "passed" && coverage) {
    return {
      status, label: "触发交易拦截通过", headerLabel: "触发交易拦截通过", color: "success",
      title: "触发交易拦截通过",
      description: `已确认拦截 ${coverage.intercepted} 笔触发交易；另有 ${coverage.unaffected} 笔独立历史回放未触及修改代码。各笔回放不传递状态，不能据此确认整条攻击链或正常功能通过。`,
    };
  }
  if ((status === "verified" || status === "failed") && hasCompletedReplay && verification?.evidence_version === undefined) {
    return {
      status: "unverified", label: "历史结果待核实", headerLabel: "历史回放待核实", color: "default",
      title: "历史回放结果待核实",
      description: "此记录尚未经过新版执行证据校验，正常功能未验证。",
    };
  }

  // Earlier reports used "failed" before any replay and cannot establish an outcome.
  if (status === "verified" || status === "failed") {
    return {
      status: "unverified", label: "未完成验证", headerLabel: "未完成验证", color: "default",
      title: "补丁验证尚未完成",
      description: unverifiedReasons.review.includes(reasonCode)
        ? "缺少已核实的回放证据，不能据此确认补丁效果或推翻根因。"
        : reason ?? "缺少已核实的回放证据，无法确认补丁效果。",
    };
  }
  if (status === "blocked") {
    return {
      status, label: "无法验证", headerLabel: "暂时无法验证", color: "warning",
      title: "补丁暂时无法验证",
      description: reason ?? "验证条件尚未满足，未形成补丁效果结论。",
      nextStep,
    };
  }
  if (status === "error") {
    return {
      status, label: "验证异常", headerLabel: "验证异常", color: "warning",
      title: "补丁验证异常",
      description: reason ?? "验证过程发生异常，未形成补丁效果结论。",
      nextStep,
    };
  }
  if (status === "skipped") {
    return {
      status, label: "已跳过", headerLabel: "验证已跳过", color: "default",
      title: "本次任务已跳过补丁验证",
      description: reason ?? "本次分析跳过了补丁验证阶段。",
    };
  }
  if (status === "unverified" || (status !== undefined && status !== "not_run")) {
    // Only this structured backend branch records successful execution of modified code.
    // It still does not establish attack success, root-cause rejection or a failed verdict.
    if (status === "unverified" && reasonCode === "patch_interception_not_established"
      && hasCompletedReplay && verification?.replay_attempted === true
      && verification?.evidence_version === 1 && verification?.scope === "attack_path_only"
      && verification?.next_action === "revise_patch" && coverage && coverage.unresolved > 0) {
      return {
        status: "unverified", label: "未建立拦截", headerLabel: "尚未建立拦截", color: "default",
        title: "补丁尚未建立拦截",
        description: "回放记录显示，执行修改代码的交易仍然成功；尚未确认补丁拦截，也不能据此判定攻击成功或根因错误。",
        nextStep: "根据本次执行反馈修订补丁，再回放相同的触发交易。",
      };
    }
    const presentation = presentUnverified(reasonCode, reason);
    if (reasonCode === "patch_interception_not_established" && coverage
      && coverage.intercepted === 0 && coverage.unaffected > 0 && coverage.unresolved === 0) {
      presentation.nextStep = reasonNextSteps.modified_code_not_reached;
    }
    return presentation;
  }
  return {
    status: "not_run", label: "未执行", headerLabel: "验证未执行", color: "default",
    title: task?.status === "running" ? "等待补丁验证" : "补丁验证未执行",
    description: reason ?? "尚未执行补丁回放。",
  };
}

/** Show public compiler requirements, not raw compiler output or host configuration. */
export function getPatchCompileDiagnostics(task: Task | null): PatchCompileDiagnostic[] {
  const verification = asRecord(asRecord(task?.result)?.verification);
  const diagnostics = verification?.compile_diagnostics;
  if (!Array.isArray(diagnostics)) return [];
  const seen = new Set<string>();
  return diagnostics.flatMap((value): PatchCompileDiagnostic[] => {
    const diagnostic = asRecord(value);
    if (!diagnostic) return [];
    const name = diagnostic.contract_name;
    const address = diagnostic.address;
    const version = diagnostic.compiler_version;
    const target = typeof name === "string" && /^[A-Za-z_$][\w$]{0,79}$/.test(name)
      ? name : typeof address === "string" && /^0x[0-9a-f]{40}$/i.test(address)
        ? `${address.slice(0, 8)}…${address.slice(-6)}` : "目标合约";
    const compilerVersion = typeof version === "string" && /^v?\d+\.\d+\.\d+(?:\+commit\.[0-9a-f]{8})?$/i.test(version)
      ? version : undefined;
    const description = diagnostic.reason_code === "compiler_unavailable"
      ? "未找到匹配的编译器。" : "源码未通过编译。";
    const key = `${target}:${compilerVersion ?? ""}:${description}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [{ target, compilerVersion, description }];
  }).slice(0, 3);
}

/** A replay verdict covers the submitted attack path, not all business flows. */
export function getPatchVerificationDimensions(task: Task | null): PatchVerificationDimension[] {
  if (task?.is_demo) return [];
  const verification = asRecord(asRecord(task?.result)?.verification);
  if (!verification || (verification.replay_completed !== true && !asRecord(verification.dimensions))) return [];
  const presentation = getPatchVerificationPresentation(task);
  const coverage = replayCoverage(verification.coverage);
  // The current attack_path_only protocol records no normal-business
  // experiment or complete profit measurement. Dimension flags cannot
  // manufacture either measurement, even in an otherwise verified replay.
  return [
    { key: "attack_interception", label: coverage ? "触发交易拦截" : "攻击拦截", value: presentation.status === "verified" ? "已通过"
      : presentation.status === "failed" ? "未通过" : "待核实" },
    { key: "normal_regression", label: "正常功能", value: "未验证" },
    { key: "profit", label: "回放利润", value: "无法确认" },
  ];
}

/** The structured report and its export share the same evidence-gated verdict as the panel. */
export function buildPatchVerificationMarkdown(task: Task | null): string {
  const summary = getPatchVerificationPresentation(task);
  const dimensions = getPatchVerificationDimensions(task);
  return [
    `**${summary.title}**`, "", summary.description,
    ...(dimensions.length ? ["", ...dimensions.map(item => `- ${item.label}：${item.value}`)] : []),
    ...(summary.nextStep ? ["", `下一步：${summary.nextStep}`] : []),
  ].join("\n");
}
