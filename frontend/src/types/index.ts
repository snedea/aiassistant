export interface Fact {
  id: number;
  category: string;
  subject: string;
  content: string;
  source_type: string | null;
  source_ref: string | null;
  confidence: number;
  created_at: string;
  updated_at: string;
}

export interface MemoryResponse {
  facts: Fact[];
}

export interface ScanStateItem {
  id: number;
  source_type: string;
  last_synced_at: string | null;
  last_cursor: string | null;
  status: string;
  error_message: string | null;
  items_synced: number;
}

export interface ScanStateResponse {
  scan_states: ScanStateItem[];
}

export interface CalendarEvent {
  id: number;
  title: string;
  content: string;
  raw_metadata: Record<string, unknown>;
  ingested_at: string;
  updated_at: string;
}

export interface UpcomingEventsResponse {
  events: CalendarEvent[];
  count: number;
}

export interface EmailSummary {
  source_item_id: number;
  external_id: string;
  importance: string;
  summary: string;
  from: string;
  subject: string;
  summarized_at: string;
}

export interface EmailSummariesResponse {
  summaries: EmailSummary[];
  count: number;
}

export interface TriageItem {
  source_item_id: number;
  source_type: string;
  external_id: string;
  priority: string;
  summary: string;
  title: string;
  triaged_at: string;
}

export interface TriageResponse {
  triages: TriageItem[];
  count: number;
}

export interface ScannerInfo {
  name: string;
  running: boolean;
}

export interface SourceHealthItem {
  source_type: string;
  is_stale: boolean;
  last_synced_at: string | null;
  elapsed_seconds: number | null;
  expected_interval_min: number;
  status: string;
  error_message: string | null;
  last_health_alert_at: string | null;
}

export interface SourceHealthResponse {
  sources: SourceHealthItem[];
  count: number;
}

export interface ScannerStatusResponse {
  scanners: ScannerInfo[];
  count: number;
}

export interface SourceItem {
  id: number;
  source_type: string;
  external_id: string;
  title: string;
  content: string;
  raw_metadata: Record<string, unknown>;
  ingested_at: string;
  updated_at: string;
}

export interface SourceItemsResponse {
  items: SourceItem[];
  count: number;
}

export interface ConnectionStatus {
  name: string;
  configured: boolean;
  reachable: boolean;
  detail?: string;
  error?: string;
}

export interface ConnectionsResponse {
  connections: ConnectionStatus[];
  count: number;
}

export interface LLMBudgetStatus {
  daily_budget: number;
  tokens_used: number;
  tokens_remaining: number;
  pct_used: number;
  is_exhausted: boolean;
  calls_today: number;
  rate_limit_rpm: number;
  warning_pct: number;
}

export interface LLMUsageByOperation {
  operation: string;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  call_count: number;
}

export interface LLMUsageResponse {
  days: number;
  by_operation: LLMUsageByOperation[];
}

export interface LLMHourlyUsage {
  hour: string;
  total_tokens: number;
  call_count: number;
}

export interface LLMHourlyUsageResponse {
  hours: number;
  hourly: LLMHourlyUsage[];
}

export interface UpdateBudgetRequest {
  daily_budget?: number;
  rate_limit_rpm?: number;
  warning_pct?: number;
}

export interface UpdateBudgetResponse {
  status: string;
  settings: {
    daily_budget: number;
    rate_limit_rpm: number;
    warning_pct: number;
  };
}

export interface AdminStatsResponse {
  facts: number;
  conversations: number;
  source_items: Record<string, number>;
  source_items_total: number;
  vector_documents: number;
  llm_budget: LLMBudgetStatus;
}

export interface ReindexResponse {
  status: string;
  old_count: number;
  new_count: number;
}

export interface ClearMemoryResponse {
  status: string;
  facts_cleared?: number;
  conversations_cleared?: number;
  source_items_cleared?: number;
}

export interface SyncSourceResponse {
  status: string;
  source: string;
  items_synced: number;
  items_changed: number;
  items_embedded: number;
}

export interface AdminScannerInfo {
  name: string;
  running: boolean;
}

export interface AdminScannerStatusResponse {
  scanners: AdminScannerInfo[];
  count: number;
}

export interface ChatResponse {
  conversation_id: string;
  reply: string;
  action: {
    action_type: string;
    success: boolean;
    summary: string;
  } | null;
}
