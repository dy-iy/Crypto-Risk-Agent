import type { AssistantMessage, TxReviewRequest, VerificationPlan } from "../types";

const moduleOrder = ["attack_detection", "fault_localization", "rag_retrieval", "patch_generation", "patch_verification"];

export function normalizeAnalysisModules(modules: string[]) {
  if (modules.some(module => !moduleOrder.includes(module))) throw new Error("包含未知分析模块。");
  const selected = new Set(modules);
  selected.add("attack_detection");
  if (selected.has("patch_verification")) selected.add("patch_generation");
  if (selected.has("patch_generation")) selected.add("fault_localization");
  if (selected.has("fault_localization")) selected.add("rag_retrieval");
  return moduleOrder.filter(module => selected.has(module));
}

/** Recommendations never replace the transaction scope selected by the user. */
export function buildDeepAnalysisRequest(hashes: string[], chain: string, modules: string[], verificationPlan?: string): TxReviewRequest & { tx_hashes: string[] } {
  const txHashes = [...new Set(hashes.map(hash => hash.trim().toLowerCase()))];
  if (!txHashes.length || txHashes.length > 50 || txHashes.some(hash => !/^0x[0-9a-f]{64}$/.test(hash))) {
    throw new Error("请提交 1 至 50 笔有效交易 Hash。");
  }
  if (chain !== "ethereum" && chain !== "bnbchain") throw new Error("当前仅支持 Ethereum 和 BNB Chain。");
  const plan = parseVerificationPlan(verificationPlan, txHashes, chain);
  return { tx_hash: txHashes[0], tx_hashes: txHashes, chain, modules: normalizeAnalysisModules(modules),
    ...(plan ? { verification_plan: plan } : {}) };
}

/** Preserve exact integer strings; the API validates assertion semantics. */
export function parseVerificationPlan(text: string | undefined, hashes: string[], chain: string): VerificationPlan | undefined {
  if (!text?.trim()) return undefined;
  if (text.length > 100_000) throw new Error("验证计划过大，请减少断言或精简条件描述。");
  let value: unknown;
  try { value = JSON.parse(text); } catch { throw new Error("验证计划必须是有效 JSON。"); }
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("验证计划必须是 JSON 对象。");
  const plan = value as VerificationPlan;
  if (plan.schema_version !== 1 || String(plan.network_id) !== (chain === "bnbchain" ? "56" : "1")) {
    throw new Error("验证计划的版本或网络与当前输入不一致。");
  }
  if (!Array.isArray(plan.attack_transaction_hashes)
    || plan.attack_transaction_hashes.length !== hashes.length
    || plan.attack_transaction_hashes.some((hash, index) => typeof hash !== "string" || hash.toLowerCase() !== hashes[index])) {
    throw new Error("验证计划须按输入顺序包含本次全部攻击交易。");
  }
  const normalCases = plan.normal_regression_cases === undefined ? [] : plan.normal_regression_cases;
  if (!Array.isArray(plan.security_properties) || !Array.isArray(normalCases)) {
    throw new Error("验证计划须包含安全条件列表，且各计划列表字段须符合格式要求。");
  }
  return { ...plan, normal_regression_cases: normalCases };
}

export function assistantRequestHistory(messages: AssistantMessage[]): AssistantMessage[] {
  return messages.filter(message => (message.role === "user" || message.role === "assistant")
    && typeof message.content === "string" && message.content.trim())
    .slice(-6).map(({ role, content }) => ({ role, content: content.slice(0, 4000) }));
}
