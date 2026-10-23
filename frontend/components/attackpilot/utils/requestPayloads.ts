import type { AssistantMessage, TxReviewRequest } from "../types";

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
export function buildDeepAnalysisRequest(hashes: string[], chain: string, modules: string[]): TxReviewRequest & { tx_hashes: string[] } {
  const txHashes = [...new Set(hashes.map(hash => hash.trim().toLowerCase()))];
  if (!txHashes.length || txHashes.length > 50 || txHashes.some(hash => !/^0x[0-9a-f]{64}$/.test(hash))) {
    throw new Error("请提交 1 至 50 笔有效交易 Hash。");
  }
  if (chain !== "ethereum" && chain !== "bnbchain") throw new Error("当前仅支持 Ethereum 和 BNB Chain。");
  return { tx_hash: txHashes[0], tx_hashes: txHashes, chain, modules: normalizeAnalysisModules(modules) };
}

export function assistantRequestHistory(messages: AssistantMessage[]): AssistantMessage[] {
  return messages.filter(message => (message.role === "user" || message.role === "assistant")
    && typeof message.content === "string" && message.content.trim())
    .slice(-6).map(({ role, content }) => ({ role, content: content.slice(0, 4000) }));
}
