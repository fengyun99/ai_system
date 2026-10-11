/**
 * 接口数据契约（与后端 fastapi-app/app/api/schemas.py 一一镜像）。
 *
 * 两端同步规则：改接口字段必须同时改 schemas.py（response_model 强制）与本文件，
 * 字段名/可空性保持一致。动态载荷（展示快照 sources、阶段 input/output、
 * 流程卡片 card/sections 等）显式标 unknown——结构由产生方决定、事后原样回放。
 */

// ============================== 通用 ==============================

/** 后端统一响应壳 {code, msg, data}——api.ts 已解包，业务代码只接触 data 泛型。 */
export interface ApiEnvelope<T> {
  code: number
  msg: string
  data: T | null
}

export interface LabelOption { code: string; label: string }
export interface DeptOption { dept_no: string; dept_name: string }
export interface IdData { id: number }

/** 分页载荷（total + rows，多数列表接口共用形态）。 */
export interface Page<T> { total: number; rows: T[] }

export type TurnPage = Page<TurnRow>
export type KnowledgePage = Page<KnowledgeRow>
export type RagTurnPage = Page<RagTurnRow>
export type InstancePage = Page<InstanceRow>

// ============================== auth ==============================

export interface LoginData { token: string }

export interface InfoUser {
  user_id: number
  user_name: string
  nick_name: string
  dept_id: number
  dept_no: string
  dept_name: string
  id_card_masked: string
  phone_masked: string
  identity_bound: boolean
}

export interface InfoData {
  user: InfoUser
  roles: string[]
  role_names: string[]
  permissions: string[]
  data_scope: number
}

export interface RouterNode {
  menu_id: number
  menu_name: string
  path: string
  component: string
  icon: string
  sort: number
  menu_type: string
  perms: string
  children?: RouterNode[]
}

// ============================== system ==============================

export interface DeptRow {
  id: number
  dept_no: string
  dept_name: string
  parent_id: number
  ancestors: string
  status: string
}

export interface UserRoleBrief { id: number; role_name: string }

export interface UserRow {
  user_id: number
  user_name: string
  nick_name: string
  phone: string
  status: string
  last_login_at: string | null
  created_at: string
  dept_no: string
  dept_name: string
  roles: UserRoleBrief[]
}

export interface RoleRow {
  id: number
  role_name: string
  role_key: string
  data_scope: number
  status: string
  remark: string
  menu_ids: number[]
}

export interface MenuRow {
  id: number
  menu_name: string
  parent_id: number
  path: string
  component: string
  perms: string
  menu_type: string
  icon: string
  sort: number
  visible: number
}

// ============================== audit ==============================

export interface TurnRow {
  id: number
  conversation_id: number
  user: string
  dept_no: string
  question: string
  intent: string
  intent_label: string
  region: string
  theme: string
  theme_label: string
  source_type: string
  status: string
  status_label: string
  tokens_in: number
  tokens_out: number
  ttft_ms: number
  total_ms: number
  trace_id: string
  cost: number
  created_at: string
}

export interface StageRow {
  stage_no: number
  stage_type: string
  name: string
  input: unknown
  output: unknown
  status: string
  model: string
  tokens_in: number
  tokens_out: number
  tokens_estimated: number
  cost: number
  duration_ms: number
  started_at: string
  finished_at: string
  error_detail: string
}

export interface TurnDetailData {
  id: number
  conversation_id: number
  question: string
  answer: string
  intent: string
  intent_label: string
  region: string
  theme: string
  theme_label: string
  snapshot_id: string
  status: string
  tokens_in: number
  tokens_out: number
  ttft_ms: number
  total_ms: number
  source_type: string
  trace_id: string
  cost: number
  error_detail: string
  created_at: string
  stages: StageRow[]
}

export interface LabelCount { code: string; label: string; count: number }

export interface DashboardData {
  conversation_count: number
  turn_count: number
  done_count: number
  tokens_in: number
  tokens_out: number
  avg_ttft_ms: number
  avg_total_ms: number
  cost_today: number
  cost_total: number
  ingest_cost_today: number
  ingest_cost_total: number
  intent_dist: LabelCount[]
  theme_dist: LabelCount[]
  daily: Record<string, number>
}

export interface IngestLogRow {
  id: number
  knowledge_id: number
  title: string
  dept_no: string
  chunk_count: number
  tokens_in: number
  tokens_out: number
  tokens_estimated: number
  cost: number
  duration_ms: number
  status: string
  error: string
  operator_user_id: number
  created_at: string
}

// ============================== knowledge ==============================

export interface KnowledgeRow {
  id: number
  dept_no: string
  biz_type: string
  title: string
  question: string
  theme: string
  is_public: number
  sync_status: number
  sync_error: string
  created_at: string
}

/** 新增/编辑知识表单体（KnowledgeBody 请求 + 列表行编辑态共用）。 */
export interface KnowledgeForm {
  id?: number
  dept_no: string
  biz_type: string
  title: string
  question: string
  answer: string
  content: string
  theme: string
  is_public: number
}

export interface KnowledgeSaveData { id: number; sync_status: number; sync_error: string }
export interface SyncAllData { ok: number; fail: number }
export interface ReconcileData { pushed: number; dropped: number }

// ============================== tools ==============================

export interface ToolRow {
  id: number
  dept_no: string
  name: string
  description: string
  parameters: string       // JSON Schema 字符串（按需 parse）
  shared: number
  status: number
}

// ============================== flow（门户侧） ==============================

export interface FlowSummary {
  flow_key: string
  name: string
  description: string
  dept_no: string
  mode: string
  url: string
}

export interface FlowField {
  name: string
  label: string
  type?: string
  options?: string[]
  required?: boolean
  placeholder?: string
}

export interface FlowFileSlot {
  name: string
  label: string
  required: boolean
  accept: string
  uploaded: { filename: string; size: number; at: string } | null
}

/** 流程交互卡片（flow_engine._node_card 产出：form/upload/confirm/end 四型）。 */
export interface FlowCard {
  instance_id: number
  node_key: string
  node_type: string
  title: string
  progress?: string
  fields?: FlowField[]
  files?: FlowFileSlot[]
  summary?: string
  text?: string
  [k: string]: unknown
}

export interface FlowCurrentData {
  running: boolean
  instance_id?: number
  flow_key?: string
  flow_name?: string
  card?: FlowCard | null
}

export interface UploadData { slot: string; filename: string; size: number }

// ============================== flow-admin ==============================

export interface ActionOption { key: string; doc: string }

export interface FlowAdminMeta {
  node_types: string[]
  actions: ActionOption[]
  validate_rules: string[]
  field_types: string[]
  upload_exts: string[]
}

export interface FlowDefRow {
  id: number
  flow_key: string
  name: string
  description: string
  dept_no: string
  keywords: string
  mode: string
  url: string
  status: number
  published: boolean
  dirty: boolean
  draft_nodes: number
  published_nodes: number
  draft_invalid: boolean
}

export interface FlowDefDetail {
  id: number
  flow_key: string
  name: string
  description: string
  dept_no: string
  keywords: string
  mode: string
  url: string
  status: number
  nodes: string                 // 草稿 JSON 字符串
  published_nodes: string
}

export interface InstanceRow {
  id: number
  flow_key: string
  flow_name: string
  user: string
  dept_no: string
  dept_name: string
  status: string
  status_label: string
  current: string
  steps: number
  receipt_no: string
  created_at: string
  finished_at: string
}

/** 步进历史行（node_key/result 摘要，动态字段宽松）。 */
export interface InstanceStep {
  node_key: string
  node_type?: string
  at?: string
  actor?: string
  result?: string
  errors?: Record<string, string>
  data?: unknown
  [k: string]: unknown
}

export interface FlowSection {
  type: string
  title?: string
  fields?: { label: string; value: string }[]
  summary?: string
  text?: string
  [k: string]: unknown
}

export interface FlowDisplay {
  instance_id: number
  flow_key: string
  flow_name: string
  status: string
  steps_count: number
  sections: FlowSection[]
  created_at: string
}

export interface InstanceDetail {
  id: number
  status: string
  steps: InstanceStep[]
  display: FlowDisplay
  vars_public: Record<string, unknown>
}

// ============================== rag-audit ==============================

export interface RagTurnRow {
  id: number
  user: string
  dept_no: string
  question: string
  intent: string
  intent_label: string
  theme: string
  theme_label: string
  status: string
  rag_flag: string
  rag_flag_label: string
  rag_note: string
  rag_flag_by: number
  rag_flag_by_name: string
  rag_flag_at: string
  fb_rating: string
  fb_comment: string
  fb_at: string
  recall_count: number
  kept_count: number
  created_at: string
}

export interface FeedbackBrief { rating: string; comment: string; at: string }

export interface RecallRow {
  fused_rank: number
  knowledge_id: number
  title: string
  fused_score: number
  kept: number
}

/** 展示快照里的来源条目（切块级材料，动态形态）。 */
export interface DisplaySource {
  title?: string
  dept_code?: string
  is_public?: number | boolean
  score?: number | null
  [k: string]: unknown
}

export interface RagTurnDetailData {
  id: number
  question: string
  answer: string
  intent: string
  intent_label: string
  theme: string
  theme_label: string
  region: string
  dept_no: string
  source_type: string
  status: string
  rag_flag: string
  rag_note: string
  rag_flag_by: number
  rag_flag_at: string
  feedback: FeedbackBrief | null
  sources: DisplaySource[]
  recalls: RecallRow[]
  created_at: string
}

export interface KnowledgeReportRow {
  id: number
  title: string
  dept_no: string
  dept_name: string
  biz_type: string
  biz_type_label: string
  theme: string
  theme_label: string
  sync_status: number
  recall_turns: number
  avg_rank: number | null
  avg_score: number | null
  kept_count: number
  kept_rate: number | null
  flagged_count: number
  user_down: number
  flag_rate: number | null
  last_recalled_at: string
}

export interface KnowledgeReportSummary {
  kb_total: number
  recalled: number
  never_recalled: number
  flagged_linked: number
}

export interface KnowledgeReportPage {
  total: number
  summary: KnowledgeReportSummary
  rows: KnowledgeReportRow[]
}

// ============================== chat ==============================

export interface ChatProgressData { running: boolean; status: string }
export interface StopData { accepted: boolean }
export interface FeedbackData { turn_id: number; rating: string; comment: string }
export interface HandoffData { text: string }

export interface ConversationItem {
  id: number
  title: string
  turn_count: number
  updated_at: string
}

export interface FeedbackMini { rating: string; comment: string }

export interface HistoryStage {
  stage_type: string
  name: string
  status: string
  summary: unknown
}

export interface HistoryTool {
  name: string
  arguments: Record<string, unknown>
  result: string
}

export interface HistoryTurn {
  id: number
  question: string
  answer: string
  intent: string
  status: string
  feedback: FeedbackMini | null
  sources: DisplaySource[]
  questions: unknown[]
  recommend_flows: unknown[]
  stages: HistoryStage[]
  tools: HistoryTool[]
  created_at: string
}

export interface ConversationDetailData {
  id: number
  title: string
  turns: HistoryTurn[]
  flows: FlowDisplay[]
}

// ============================== SSE 事件（chat + flow 共用协议） ==============================

export interface SourceMaterial {
  title?: string
  dept_code?: string
  is_public?: number | boolean
  score?: number
  [k: string]: unknown
}

export type StageProgress = 'understanding' | 'searching' | 'web_searching' | 'generating'

/** SSE 帧联合：按 type 判别，字段与 graph.py/flow_engine.py 的 emit 一一对应。 */
export type StreamEvent =
  | { type: 'meta'; conversation_id: number; turn_id: number | null; title?: string; instance_id?: number; trace_id?: string }
  | { type: 'progress'; stage: StageProgress }
  | { type: 'stage'; stage_type: string; name: string; status?: string; duration_ms?: number; summary?: unknown; [k: string]: unknown }
  | { type: 'text'; content: string }
  | { type: 'sources'; materials: SourceMaterial[] }
  | { type: 'question'; questions: unknown[] }
  | { type: 'questions'; questions: unknown[] }
  | { type: 'recommend'; flows: unknown[] }
  | { type: 'tool'; name: string; arguments: Record<string, unknown> }
  | { type: 'tool_result'; name: string; result?: string; [k: string]: unknown }
  | { type: 'error'; message: string }
  | { type: 'done'; turn_id?: number; instance_id?: number; flow_display?: FlowDisplay }
  | { type: 'flow_start'; instance_id: number; flow_key: string; flow_name: string; card?: FlowCard }
  | { type: 'flow_auto'; node_key: string; title?: string; result?: string }
  | { type: 'flow_complete'; instance_id: number; flow_name?: string; text?: string }
  | { type: 'flow_cancelled'; instance_id: number; text: string }
  | { type: 'card'; card: FlowCard }
  | { type: 'form_error'; instance_id: number; node_key: string; errors: Record<string, string> }
