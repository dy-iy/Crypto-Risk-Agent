export enum TaskStatus {
  PENDING = "pending",
  RUNNING = "running",
  COMPLETED = "completed",
  FAILED = "failed",
}

export enum LogLevel {
  INFO = "info",
  WARNING = "warning",
  ERROR = "error",
  DEBUG = "debug",
}

export enum MsgType {
  TEXT = "text",
  MARKDOWN = "markdown",
  TOOL_CALL = "tool",
  RESULT = "result",
}

export interface LogMessage {
  type: "LOG";
  task_id?: string;
  agent: string;
  level: LogLevel;
  message: string;
  message_type: MsgType;
  is_truncated: boolean;
  timestamp: string;
  log_id?: string;
  persisted_id?: number;
}

export interface TaskCreateRequest {
  dapp_name: string;
}

export interface DappReference {
  time?: string | null;
  link?: string | null;
}

export interface DappCatalogItem {
  name: string;
  cause?: string | null;
  platform?: string | null;
  time?: string | null;
  root_cause?: string | null;
  report?: string | null;
  detection?: DappReference | null;
  disclosure?: DappReference | null;
  report_link?: string | null;
  transaction_hash: string[];
  transaction_count: number;
  raw_file: string;
  processed_file?: string | null;
  has_processed_analysis: boolean;
  demo_ready: boolean;
}

export interface DappCatalogResponse {
  total: number;
  demo_ready_count: number;
  items: DappCatalogItem[];
}

export interface Task {
  task_id: string;
  dapp_name: string;
  status: TaskStatus;
  created_at: string;
  completed_at?: string | null;
  duration?: number | null;
  final_report?: string | null;
  result?: unknown;
  error?: string | null;
  archived?: boolean;
}

export interface ConnectedEvent {
  type: "CONNECTED";
  task_id: string;
  message: string;
  timestamp: string;
}

export interface PingEvent {
  type: "PING";
  task_id?: string;
  timestamp: string;
}

export interface PongEvent {
  type: "PONG";
  task_id?: string;
  timestamp: string;
}

export interface TaskStatusEvent {
  type: "TASK_STATUS";
  task_id: string;
  dapp_name: string;
  status: TaskStatus;
  created_at?: string;
  completed_at?: string | null;
  duration?: number | null;
  error?: string | null;
  archived?: boolean;
}

export interface TaskFinalEvent {
  type: "TASK_FINAL";
  task_id: string;
  dapp_name: string;
  status: TaskStatus;
  completed_at?: string | null;
  duration?: number | null;
  final_report?: string | null;
  error?: string | null;
  archived?: boolean;
}

export interface LogDroppedEvent {
  type: "LOG_DROPPED";
  task_id: string;
  count: number;
  message: string;
  timestamp: string;
}

export interface HeartbeatTimeoutEvent {
  type: "HEARTBEAT_TIMEOUT";
  task_id: string;
  message: string;
  timestamp: string;
}

export type TaskEvent =
  | ConnectedEvent
  | PingEvent
  | PongEvent
  | TaskStatusEvent
  | TaskFinalEvent
  | LogDroppedEvent
  | HeartbeatTimeoutEvent
  | LogMessage;

export interface FullLogResponse {
  content: string;
  source: "cache" | "database";
}

export interface TaskLogPageResponse {
  events: LogMessage[];
  next_before_id?: number | null;
  has_more: boolean;
  total: number;
}

export interface AgentLogFileMeta {
  id: string;
  name: string;
  agent: string;
  size: number;
  modified_at: string;
}

export interface AgentLogFilesResponse {
  task_id: string;
  dapp_name: string;
  log_dir: string | null;
  files: AgentLogFileMeta[];
}

export interface AgentLogFileResponse extends AgentLogFileMeta {
  task_id: string;
  dapp_name: string;
  content: string;
  truncated: boolean;
}

export type ProductViewMode = "report" | "learn" | "auditor" | "raw";

export type LanguageMode = "en" | "zh";

export type ReportSectionKey =
  | "root_cause"
  | "attack_path"
  | "key_transactions"
  | "patch_suggestions"
  | "verification_results";

export interface EvidenceItem {
  id: string;
  title: string;
  source: "report" | "agent_log" | "tool" | "transaction" | "system";
  evidence_tier?: "verified" | "tool_backed" | "agent_derived" | "report_derived";
  agent?: string;
  level?: LogLevel;
  message_type?: MsgType;
  timestamp?: string;
  log_id?: string;
  content: string;
  full_content?: string;
  confidence: "high" | "medium" | "low";
  score?: number;
  score_label?: "strong" | "supporting" | "weak";
  score_reasons?: string[];
}

export interface ProductModeConfig {
  mode: ProductViewMode;
  showRawLogs: boolean;
  showTeachingHints: boolean;
  showEvidenceByDefault: boolean;
}

export interface AddressRole {
  role?: string;
  description?: string;
}

export interface TransactionRoleEvidence extends AddressRole {
  address: string;
}

export interface TokenBalanceChange {
  token?: string;
  name?: string;
  amount?: number | string | null;
  usd_value?: number | null;
  contract?: string | null;
}

export interface BalanceParticipantSummary {
  address: string;
  usd_delta: number;
  tokens: TokenBalanceChange[];
}

export interface TransactionBalanceSummary {
  participant_count: number;
  total_usd_delta: number;
  top_participants: BalanceParticipantSummary[];
}

export interface MacroTransactionSummary {
  hash: string;
  display_hash: string;
  type: "attack" | "auxiliary" | "candidate";
  is_debug_target: boolean;
  order: number;
  from?: string | null;
  to?: string | null;
  from_role?: string | null;
  to_role?: string | null;
  involved_roles: TransactionRoleEvidence[];
  block_number?: number | null;
  timestamp?: number | null;
  function_signature?: string | null;
  status?: string | null;
  success?: boolean | null;
  value_eth?: number | null;
  gas_used?: number | null;
  cost_eth?: number | null;
  interacted_addresses: string[];
  event_logs: string[];
  balance_summary: TransactionBalanceSummary;
}

export interface MacroAnalysisResponse {
  task_id: string;
  dapp_name: string;
  processed_file: string;
  dapp?: Record<string, unknown>;
  transaction_hash_list: string[];
  transaction_roles: Record<string, AddressRole>;
  attack_transactions: string[];
  auxiliary_transactions: string[];
  transactions_need_analyze: string[];
  bug_summary: string;
  time_used: Record<string, unknown>;
  token_used: Record<string, unknown>;
  transactions: MacroTransactionSummary[];
  balance_change: Record<string, unknown>;
  transaction_to_property: Record<string, unknown>;
}

export type ConsistencyStatus = "pass" | "warning" | "risk";

export interface AgentSignalSummary {
  agent: string;
  events: number;
  transactions: string[];
  functions: string[];
  mentions_patch?: boolean;
  mentions_verification?: boolean;
  mentions_root_cause?: boolean;
  mentionsPatch?: boolean;
  mentionsVerification?: boolean;
  mentionsRootCause?: boolean;
}

export interface ConsistencyCheck {
  id: string;
  title: string;
  description: string;
  status: ConsistencyStatus;
  score: number;
  evidence: string[];
  recommendation?: string | null;
}

export interface AutomatedReviewResponse {
  task_id: string;
  dapp_name: string;
  generated_at: string;
  review_type: string;
  status: ConsistencyStatus;
  score: number;
  checks: ConsistencyCheck[];
  agent_signals: AgentSignalSummary[];
  shared_transactions: Array<{ value: string; agents: string[] }>;
  shared_functions: Array<{ value: string; agents: string[] }>;
  next_actions: string[];
  llm_review_agent_used: boolean;
}

export interface KnowledgePracticeSource {
  name: string;
  url: string;
  hint?: string;
}

export interface VulnerabilityTypeKnowledge {
  id: string;
  name_zh: string;
  name_en: string;
  category?: string;
  one_liner?: string;
  mental_model?: string;
  why_it_happens?: string[];
  attack_steps?: string[];
  trace_signals?: string[];
  repair_hints?: string[];
  practice_sources?: KnowledgePracticeSource[];
  tracepilot_usage?: string;
}

export interface TxReviewRequest {
  tx_hash: string;
  chain?: string;
  tx_hashes?: string[];
  modules?: string[];
}

export interface TxReviewEvidence {
  type: string;
  title: string;
  content: string;
  source: string;
}

export interface TxReviewSignal {
  id: string;
  name: string;
  level: "high" | "medium" | "low" | string;
  summary: string;
  evidence: string;
  confidence: "high" | "medium" | "low" | string;
}

export interface TxReviewMatchedCase {
  name: string;
  case_id?: string | null;
  dataset_file?: string | null;
  source?: string | null;
  matched_hash: string;
  platform?: string | null;
  time?: string | null;
  cause?: string | null;
  root_cause?: string | null;
  loss?: string | null;
  report_link?: string | null;
  vulnerability_type_ids: string[];
  transaction_count?: number | null;
}

export interface TxReviewResponse {
  tx_hash: string;
  chain: string;
  risk_level: "high" | "medium" | "low" | "unknown" | string;
  tx_type: "known_attack_case" | "unreviewed_transaction" | string;
  summary: string;
  signals: string[];
  signal_details: TxReviewSignal[];
  evidence: TxReviewEvidence[];
  metrics: Record<string, unknown>;
  live_observation_status: "ok" | "partial" | "unavailable" | "not_started" | string;
  matched_cases: TxReviewMatchedCase[];
  recommend_deep_analysis: boolean;
  deep_analysis_ready: boolean;
}

export interface TxDetectRequest {
  tx_hashes: string[];
  chain?: string;
  modules?: string[];
}

export interface TxDetectItem {
  tx_hash: string;
  risk_level: "high" | "medium" | "low" | "unknown" | string;
  classification: string;
  summary: string;
  signals: string[];
  signal_details: TxReviewSignal[];
  metrics: Record<string, unknown>;
  matched_cases: TxReviewMatchedCase[];
  live_observation_status: "ok" | "partial" | "unavailable" | "not_started" | string;
}

export interface TxDetectResponse {
  chain: string;
  input_count: number;
  analyzed_count: number;
  risk_level: "high" | "medium" | "low" | "unknown" | string;
  summary: string;
  modules: string[];
  recommended_tx_hashes: string[];
  attack_candidates: TxDetectItem[];
  auxiliary_candidates: TxDetectItem[];
  unrelated_candidates: TxDetectItem[];
  invalid_hashes: string[];
  deep_analysis_ready: boolean;
}

export interface VulnerabilityKnowledgeResponse {
  total: number;
  items: VulnerabilityTypeKnowledge[];
}

export interface AssistantMessage {
  role: "user" | "assistant";
  content: string;
}

export interface AssistantChatRequest {
  scope: "general" | "tx_review" | "task" | "knowledge";
  question: string;
  task_id?: string;
  tx_hash?: string;
  chain?: string;
  history?: AssistantMessage[];
}

export interface AssistantSource {
  type: string;
  title: string;
  source: string;
  content?: string | null;
}

export interface AssistantChatResponse {
  answer: string;
  scope: string;
  model: string;
  sources: AssistantSource[];
  suggested_questions: string[];
  used_fallback: boolean;
}

export interface RagSearchRequest {
  query: string;
  top_k?: number;
  filters?: Record<string, unknown>;
}

export interface RagSearchItem {
  id: string;
  source: string;
  title: string;
  content: string;
  tags: string[];
  metadata: Record<string, unknown>;
  score: number;
  vector_score: number;
  keyword_score: number;
}

export interface RagSearchResponse {
  query: string;
  total: number;
  items: RagSearchItem[];
  index?: {
    exists?: boolean;
    chunk_count?: number;
    updated_at?: string | null;
    mode?: string;
    path?: string;
  };
}
