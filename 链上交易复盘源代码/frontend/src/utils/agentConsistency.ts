import { LogMessage, MacroAnalysisResponse, Task, TaskEvent } from "../types";

export type ConsistencyStatus = "pass" | "warning" | "risk";

export interface AgentSignalSummary {
  agent: string;
  events: number;
  transactions: string[];
  functions: string[];
  mentionsPatch: boolean;
  mentionsVerification: boolean;
  mentionsRootCause: boolean;
}

export interface ConsistencyCheck {
  id: string;
  title: string;
  description: string;
  status: ConsistencyStatus;
  score: number;
  evidence: string[];
  recommendation?: string;
}

export interface AgentConsistencySummary {
  score: number;
  status: ConsistencyStatus;
  checks: ConsistencyCheck[];
  agentSignals: AgentSignalSummary[];
  sharedTransactions: Array<{ value: string; agents: string[] }>;
  sharedFunctions: Array<{ value: string; agents: string[] }>;
}

const TX_HASH_RE = /0x[a-fA-F0-9]{64}/g;
const FUNCTION_RE = /\b([A-Za-z_][A-Za-z0-9_]{2,})\s*\(/g;
const NOISE_FUNCTIONS = new Set([
  "if",
  "for",
  "while",
  "require",
  "assert",
  "revert",
  "return",
  "emit",
  "address",
  "uint256",
  "balanceOf",
]);

function isLogEvent(event: TaskEvent): event is LogMessage {
  return event.type === "LOG";
}

function unique<T>(values: T[]) {
  return Array.from(new Set(values));
}

function shortHash(value: string) {
  return value.length > 18 ? `${value.slice(0, 10)}...${value.slice(-8)}` : value;
}

function extractTransactions(text: string) {
  return unique(Array.from(text.matchAll(TX_HASH_RE)).map((item) => item[0].toLowerCase()));
}

function extractFunctions(text: string) {
  const functions = Array.from(text.matchAll(FUNCTION_RE))
    .map((item) => item[1])
    .filter((name) => !NOISE_FUNCTIONS.has(name))
    .filter((name) => name.length <= 48);
  return unique(functions).slice(0, 24);
}

function hasAny(text: string, keywords: string[]) {
  const normalized = text.toLowerCase();
  return keywords.some((keyword) => normalized.includes(keyword));
}

function buildAgentSignals(events: TaskEvent[], task: Task | null): AgentSignalSummary[] {
  const map = new Map<string, { events: LogMessage[]; text: string }>();
  events.filter(isLogEvent).forEach((event) => {
    const current = map.get(event.agent) ?? { events: [], text: "" };
    current.events.push(event);
    current.text += `\n${event.message}`;
    map.set(event.agent, current);
  });

  return Array.from(map.entries())
    .map(([agent, payload]) => {
      const text = payload.text;
      return {
        agent,
        events: payload.events.length,
        transactions: extractTransactions(text),
        functions: extractFunctions(text),
        mentionsPatch: hasAny(text, ["patch", "fix", "mitigation", "补丁", "修复"]),
        mentionsVerification: hasAny(text, ["verify", "verification", "validation", "replay", "success", "failure", "验证", "回放"]),
        mentionsRootCause: hasAny(text, ["root cause", "fault", "vulnerab", "faulty function", "漏洞", "根因"]),
      };
    })
    .concat(
      task?.final_report
        ? [
            {
              agent: "Final Report",
              events: 1,
              transactions: extractTransactions(task.final_report),
              functions: extractFunctions(task.final_report),
              mentionsPatch: hasAny(task.final_report, ["patch", "fix", "mitigation", "补丁", "修复"]),
              mentionsVerification: hasAny(task.final_report, ["verify", "verification", "validation", "replay", "success", "failure", "验证", "回放"]),
              mentionsRootCause: hasAny(task.final_report, ["root cause", "fault", "vulnerab", "faulty function", "漏洞", "根因"]),
            },
          ]
        : [],
    );
}

function sharedValues(signals: AgentSignalSummary[], field: "transactions" | "functions") {
  const map = new Map<string, Set<string>>();
  signals.forEach((signal) => {
    signal[field].forEach((value) => {
      const current = map.get(value) ?? new Set<string>();
      current.add(signal.agent);
      map.set(value, current);
    });
  });
  return Array.from(map.entries())
    .map(([value, agents]) => ({ value, agents: Array.from(agents) }))
    .filter((item) => item.agents.length >= 2)
    .sort((a, b) => b.agents.length - a.agents.length || a.value.localeCompare(b.value))
    .slice(0, 12);
}

function makeCheck(
  id: string,
  title: string,
  description: string,
  score: number,
  evidence: string[],
  recommendation?: string,
): ConsistencyCheck {
  const status: ConsistencyStatus = score >= 75 ? "pass" : score >= 45 ? "warning" : "risk";
  return { id, title, description, status, score, evidence, recommendation };
}

function containsAnyTransaction(signals: AgentSignalSummary[], agents: string[], txs: string[]) {
  const normalized = new Set(txs.map((tx) => tx.toLowerCase()));
  return signals
    .filter((signal) => agents.includes(signal.agent))
    .some((signal) => signal.transactions.some((tx) => normalized.has(tx)));
}

function functionsForAgents(signals: AgentSignalSummary[], agents: string[]) {
  return unique(signals.filter((signal) => agents.includes(signal.agent)).flatMap((signal) => signal.functions));
}

export function analyzeAgentConsistency(
  task: Task | null,
  events: TaskEvent[],
  macro: MacroAnalysisResponse | null,
): AgentConsistencySummary {
  const agentSignals = buildAgentSignals(events, task);
  const sharedTransactions = sharedValues(agentSignals, "transactions");
  const sharedFunctions = sharedValues(agentSignals, "functions");
  const debugTargets = (macro?.transactions_need_analyze?.length ? macro.transactions_need_analyze : macro?.attack_transactions) ?? [];
  const macroAttackTxs = macro?.attack_transactions ?? [];
  const debugAgents = ["Transaction Debugger", "GlobalMemory Administrator", "Final Report"];
  const patchAgents = ["Code Patcher", "Transaction Judge", "Final Report"];
  const rootAgents = ["TxFaultAgent", "Task Organizer", "Transaction Debugger", "GlobalMemory Administrator", "Final Report"];

  const macroTxCovered = debugTargets.length
    ? containsAnyTransaction(agentSignals, debugAgents, debugTargets)
    : sharedTransactions.length > 0;
  const macroCoverageRatio = debugTargets.length
    ? debugTargets.filter((tx) => containsAnyTransaction(agentSignals, debugAgents, [tx])).length / debugTargets.length
    : sharedTransactions.length > 0
      ? 1
      : 0;

  const rootFunctions = functionsForAgents(agentSignals, rootAgents);
  const patchFunctions = functionsForAgents(agentSignals, patchAgents);
  const overlappingFunctions = rootFunctions.filter((name) => patchFunctions.includes(name));

  const patchMentionAgents = agentSignals.filter((signal) => signal.mentionsPatch).map((signal) => signal.agent);
  const verificationMentionAgents = agentSignals.filter((signal) => signal.mentionsVerification).map((signal) => signal.agent);
  const rootCauseAgents = agentSignals.filter((signal) => signal.mentionsRootCause).map((signal) => signal.agent);

  const checks: ConsistencyCheck[] = [
    makeCheck(
      "macro-to-debug",
      "Macro transaction selection -> Trace debugging",
      "Checks whether attack/debug target transactions selected in the macro stage are reused by Trace Debugger or the final report.",
      macroTxCovered ? Math.max(70, Math.round(macroCoverageRatio * 100)) : 25,
      debugTargets.length
        ? [
            `${debugTargets.length} macro debug target(s): ${debugTargets.slice(0, 4).map(shortHash).join(", ")}`,
            macroTxCovered ? "Trace/debug stage references at least one macro target." : "No macro target was found in Trace/debug outputs.",
          ]
        : ["No macro debug target is available; fallback uses shared transaction mentions."],
      macroTxCovered ? undefined : "Make sure Transaction Debugger and final report explicitly cite macro-selected attack transactions.",
    ),
    makeCheck(
      "attack-classification-overlap",
      "Attack transaction agreement",
      "Checks whether multiple agents cite the same attack transaction instead of drifting to unrelated transactions.",
      sharedTransactions.length >= 2 ? 88 : sharedTransactions.length === 1 ? 62 : macroAttackTxs.length ? 35 : 50,
      sharedTransactions.length
        ? sharedTransactions
            .slice(0, 4)
            .map((item) => `${shortHash(item.value)} shared by ${item.agents.join(", ")}`)
        : ["No transaction hash is shared by two or more agents."],
      sharedTransactions.length ? undefined : "Promote transaction hashes into structured outputs so cross-agent agreement can be verified.",
    ),
    makeCheck(
      "root-to-patch",
      "Root cause function -> Patch continuity",
      "Checks whether functions mentioned by fault localization/debugging are also referenced by patch or verification outputs.",
      overlappingFunctions.length >= 2 ? 88 : overlappingFunctions.length === 1 ? 68 : rootFunctions.length && patchFunctions.length ? 42 : 25,
      overlappingFunctions.length
        ? overlappingFunctions.slice(0, 6).map((name) => `${name} appears in both localization/debug and patch stages.`)
        : [
            rootFunctions.length ? `Root/debug functions: ${rootFunctions.slice(0, 6).join(", ")}` : "No root/debug function candidates extracted.",
            patchFunctions.length ? `Patch functions: ${patchFunctions.slice(0, 6).join(", ")}` : "No patch-stage function candidates extracted.",
          ],
      overlappingFunctions.length ? undefined : "Require patch reports to cite the same faulty functions and trace indices found by debugging.",
    ),
    makeCheck(
      "verification-loop",
      "Patch verification loop",
      "Checks whether patch/fix discussion is followed by verification, replay, success/failure, or judge signals.",
      patchMentionAgents.length && verificationMentionAgents.length ? 86 : patchMentionAgents.length ? 55 : 25,
      [
        patchMentionAgents.length ? `Patch mentioned by: ${patchMentionAgents.join(", ")}` : "No patch/fix signal detected.",
        verificationMentionAgents.length
          ? `Verification mentioned by: ${verificationMentionAgents.join(", ")}`
          : "No verification/replay signal detected.",
      ],
      patchMentionAgents.length && verificationMentionAgents.length
        ? undefined
        : "Expose patch replay results and success/failure signals in the final report.",
    ),
    makeCheck(
      "root-cause-quorum",
      "Root cause quorum",
      "Checks whether root-cause language appears across multiple agents instead of only in the final report.",
      rootCauseAgents.length >= 3 ? 90 : rootCauseAgents.length === 2 ? 68 : rootCauseAgents.length === 1 ? 42 : 20,
      rootCauseAgents.length ? [`Root-cause signals found in: ${rootCauseAgents.join(", ")}`] : ["No root-cause signal detected."],
      rootCauseAgents.length >= 2 ? undefined : "Ask each major stage to emit a structured root-cause field for easier consistency checking.",
    ),
  ];

  const score = Math.round(checks.reduce((sum, check) => sum + check.score, 0) / checks.length);
  const status: ConsistencyStatus = score >= 75 ? "pass" : score >= 45 ? "warning" : "risk";

  return {
    score,
    status,
    checks,
    agentSignals,
    sharedTransactions,
    sharedFunctions,
  };
}
