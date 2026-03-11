import type {
  MemoryResponse,
  ScanStateResponse,
  UpcomingEventsResponse,
  EmailSummariesResponse,
  TriageResponse,
  ScannerStatusResponse,
  SourceHealthResponse,
  SourceItemsResponse,
  ChatResponse,
  ConnectionStatus,
  ConnectionsResponse,
  AdminStatsResponse,
  ReindexResponse,
  ClearMemoryResponse,
  SyncSourceResponse,
  AdminScannerStatusResponse,
  LLMBudgetStatus,
  LLMUsageResponse,
  LLMHourlyUsageResponse,
  UpdateBudgetRequest,
  UpdateBudgetResponse,
} from "../types";

export function getApiKey(): string | null {
  return localStorage.getItem("aiassistant_api_key");
}

export function setApiKey(key: string): void {
  localStorage.setItem("aiassistant_api_key", key);
}

export function clearApiKey(): void {
  localStorage.removeItem("aiassistant_api_key");
}

const DEFAULT_TIMEOUT_MS = 60_000;
const LLM_TIMEOUT_MS = 180_000;
const LLM_PATHS = ["/chat", "/admin/reindex", "/admin/sync/"];

async function fetchApi<T>(
  path: string,
  options?: RequestInit & { timeoutMs?: number },
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const apiKey = getApiKey();
  if (apiKey) {
    headers["Authorization"] = `Bearer ${apiKey}`;
  }

  const timeoutMs =
    options?.timeoutMs ??
    (LLM_PATHS.some((p) => path.startsWith(p))
      ? LLM_TIMEOUT_MS
      : DEFAULT_TIMEOUT_MS);

  const controller = new AbortController();
  if (options?.signal) {
    if (options.signal.aborted) {
      controller.abort(options.signal.reason);
    } else {
      options.signal.addEventListener(
        "abort",
        () => controller.abort(options.signal!.reason),
        { once: true },
      );
    }
  }
  const timeoutId = setTimeout(() => controller.abort("timeout"), timeoutMs);

  let response: Response;
  try {
    response = await fetch("/api" + path, {
      ...options,
      headers: { ...headers, ...options?.headers },
      signal: controller.signal,
    });
  } catch (err: unknown) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Request timed out");
    }
    throw err;
  }
  clearTimeout(timeoutId);

  if (!response.ok) {
    if (response.status === 401) {
      clearApiKey();
      window.dispatchEvent(new CustomEvent("auth-required"));
    }
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // non-JSON response body; fall back to status-only message
    }
    if (detail) {
      throw new Error(`${response.status} ${response.statusText}: ${detail}`);
    }
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function getHealth(): Promise<{ status: string }> {
  return fetchApi<{ status: string }>("/health");
}

export async function getMemoryFacts(
  category?: string,
): Promise<MemoryResponse> {
  const query = category
    ? "?category=" + encodeURIComponent(category)
    : "";
  return fetchApi<MemoryResponse>("/memory" + query);
}

export async function deleteMemoryFact(
  factId: number,
): Promise<{ status: string; fact_id: number }> {
  return fetchApi("/memory/" + factId, { method: "DELETE" });
}

export async function getScanState(): Promise<ScanStateResponse> {
  return fetchApi<ScanStateResponse>("/sources/scan-state");
}

export async function getUpcomingEvents(
  withinMinutes?: number,
): Promise<UpcomingEventsResponse> {
  const query = "?within_minutes=" + (withinMinutes ?? 1440);
  return fetchApi<UpcomingEventsResponse>(
    "/sources/calendar/upcoming" + query,
  );
}

export async function getRecentEmailSummaries(): Promise<EmailSummariesResponse> {
  return fetchApi<EmailSummariesResponse>("/sources/emails/summaries/recent");
}

export async function getRecentTriages(): Promise<TriageResponse> {
  return fetchApi<TriageResponse>("/sources/triage/recent");
}

export async function getSourceHealth(): Promise<SourceHealthResponse> {
  return fetchApi<SourceHealthResponse>("/sources/health");
}

export async function getScannerStatus(): Promise<ScannerStatusResponse> {
  return fetchApi<ScannerStatusResponse>("/sources/scanner/status");
}

export async function getSourceItems(
  sourceType?: string,
  limit?: number,
): Promise<SourceItemsResponse> {
  const params = new URLSearchParams();
  if (sourceType) params.set("source_type", sourceType);
  params.set("limit", String(limit ?? 20));
  return fetchApi<SourceItemsResponse>("/sources/items?" + params.toString());
}

export async function postChat(
  message: string,
  conversationId?: string,
): Promise<ChatResponse> {
  return fetchApi<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      conversation_id: conversationId ?? null,
    }),
  });
}

export async function getAdminStats(): Promise<AdminStatsResponse> {
  return fetchApi<AdminStatsResponse>("/admin/stats");
}

export async function getConnections(): Promise<ConnectionsResponse> {
  return fetchApi<ConnectionsResponse>("/admin/connections");
}

export async function testConnection(
  source: string,
): Promise<{ connection: ConnectionStatus }> {
  return fetchApi<{ connection: ConnectionStatus }>(
    "/admin/connections/" + encodeURIComponent(source) + "/test",
    { method: "POST" },
  );
}

export async function postReindex(): Promise<ReindexResponse> {
  return fetchApi<ReindexResponse>("/admin/reindex", { method: "POST" });
}

export async function postClearMemory(
  scope: string,
  category?: string,
  sourceType?: string,
): Promise<ClearMemoryResponse> {
  return fetchApi<ClearMemoryResponse>("/admin/memory/clear", {
    method: "POST",
    body: JSON.stringify({
      scope,
      category: category ?? null,
      source_type: sourceType ?? null,
    }),
  });
}

export async function postSyncSource(source: string): Promise<SyncSourceResponse> {
  return fetchApi<SyncSourceResponse>("/admin/sync/" + encodeURIComponent(source), { method: "POST" });
}

export async function postRunTriage(source: string): Promise<{ triages_created: number }> {
  return fetchApi<{ triages_created: number }>(
    "/sources/triage/run?source_type=" + encodeURIComponent(source),
    { method: "POST", timeoutMs: 300000 },
  );
}

export async function getLLMBudget(): Promise<LLMBudgetStatus> {
  return fetchApi<LLMBudgetStatus>("/admin/llm/budget");
}

export async function getLLMUsage(
  days?: number,
): Promise<LLMUsageResponse> {
  const query = days ? "?days=" + days : "";
  return fetchApi<LLMUsageResponse>("/admin/llm/usage" + query);
}

export async function getLLMUsageHistory(
  hours?: number,
): Promise<LLMHourlyUsageResponse> {
  const query = hours ? "?hours=" + hours : "";
  return fetchApi<LLMHourlyUsageResponse>("/admin/llm/usage/history" + query);
}

export async function updateLLMBudget(
  settings: UpdateBudgetRequest,
): Promise<UpdateBudgetResponse> {
  return fetchApi<UpdateBudgetResponse>("/admin/llm/budget", {
    method: "PUT",
    body: JSON.stringify(settings),
  });
}

export async function getAdminScannerStatus(): Promise<AdminScannerStatusResponse> {
  return fetchApi<AdminScannerStatusResponse>("/admin/scanner/status");
}
