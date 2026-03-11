import { useState, useCallback } from "react";
import Card from "./Card";
import { usePolling } from "../hooks/usePolling";
import {
  getAdminStats,
  getConnections,
  testConnection,
  postReindex,
  postClearMemory,
  postSyncSource,
  postRunTriage,
  getAdminScannerStatus,
  getLLMBudget,
  getLLMUsage,
  getLLMUsageHistory,
  updateLLMBudget,
} from "../services/api";
import type {
  AdminStatsResponse,
  ConnectionsResponse,
  ConnectionStatus,
  AdminScannerStatusResponse,
  LLMBudgetStatus,
  LLMUsageResponse,
  LLMHourlyUsageResponse,
} from "../types";

export default function AdminCard(): React.ReactElement {
  const { data: stats, refresh: refreshStats } = usePolling<AdminStatsResponse>(
    useCallback(() => getAdminStats(), []),
    30000,
  );
  const { data: connections, refresh: refreshConnections } =
    usePolling<ConnectionsResponse>(
      useCallback(() => getConnections(), []),
      60000,
    );

  const [reindexing, setReindexing] = useState(false);
  const [reindexResult, setReindexResult] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const [clearResult, setClearResult] = useState<string | null>(null);
  const [testingSource, setTestingSource] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<{ label: string; action: () => Promise<void> } | null>(null);
  const [syncingSource, setSyncingSource] = useState<string | null>(null);
  const [syncResult, setSyncResult] = useState<string | null>(null);
  const [triagingSource, setTriagingSource] = useState<string | null>(null);
  const [triageResult, setTriageResult] = useState<string | null>(null);
  const { data: scannerStatus } = usePolling<AdminScannerStatusResponse>(
    useCallback(() => getAdminScannerStatus(), []),
    30000,
  );
  const { data: llmBudget } = usePolling<LLMBudgetStatus>(
    useCallback(() => getLLMBudget(), []),
    15000,
  );
  const { data: llmUsage } = usePolling<LLMUsageResponse>(
    useCallback(() => getLLMUsage(1), []),
    30000,
  );
  const { data: llmHistory } = usePolling<LLMHourlyUsageResponse>(
    useCallback(() => getLLMUsageHistory(24), []),
    60000,
  );
  const [editingBudget, setEditingBudget] = useState(false);
  const [budgetDraft, setBudgetDraft] = useState({ daily_budget: "", rate_limit_rpm: "", warning_pct: "" });
  const [budgetSaving, setBudgetSaving] = useState(false);
  const [budgetSaveResult, setBudgetSaveResult] = useState<string | null>(null);
  const [budgetError, setBudgetError] = useState<string | null>(null);

  const handleReindex = async () => {
    setReindexing(true);
    setReindexResult(null);
    try {
      const res = await postReindex();
      setReindexResult(
        "Re-indexed " + res.new_count + " items (was " + res.old_count + ")",
      );
      refreshStats();
    } catch (e) {
      setReindexResult("Failed: " + (e as Error).message);
    } finally {
      setReindexing(false);
    }
  };

  const confirmAndClear = (scope: string, label: string, category?: string, sourceType?: string) => {
    setConfirmAction({
      label,
      action: async () => {
        setClearing(true);
        setClearResult(null);
        setConfirmAction(null);
        try {
          const res = await postClearMemory(scope, category, sourceType);
          const parts: string[] = [];
          if (res.facts_cleared !== undefined) parts.push(res.facts_cleared + " facts");
          if (res.conversations_cleared !== undefined)
            parts.push(res.conversations_cleared + " conversations");
          if (res.source_items_cleared !== undefined)
            parts.push(res.source_items_cleared + " source items");
          setClearResult("Cleared: " + parts.join(", "));
          refreshStats();
        } catch (e) {
          setClearResult("Failed: " + (e as Error).message);
        } finally {
          setClearing(false);
        }
      },
    });
  };

  const handleSyncSource = async (source: string) => {
    setSyncingSource(source);
    setSyncResult(null);
    try {
      const res = await postSyncSource(source);
      setSyncResult(source + ": " + res.items_synced + " synced, " + res.items_changed + " changed, " + res.items_embedded + " embedded");
      refreshStats();
    } catch (e) {
      setSyncResult(source + " sync failed: " + (e as Error).message);
    } finally {
      setSyncingSource(null);
    }
  };

  const handleRunTriage = async (source: string) => {
    setTriagingSource(source);
    setTriageResult(null);
    try {
      const res = await postRunTriage(source);
      setTriageResult(source + ": " + res.triages_created + " items triaged");
    } catch (e) {
      setTriageResult(source + " triage failed: " + (e as Error).message);
    } finally {
      setTriagingSource(null);
    }
  };

  const handleTestConnection = async (source: string) => {
    setTestingSource(source);
    try {
      await testConnection(source);
      refreshConnections();
    } catch {
      refreshConnections();
    } finally {
      setTestingSource(null);
    }
  };

  const handleSaveBudget = async () => {
    setBudgetSaving(true);
    setBudgetSaveResult(null);
    setBudgetError(null);
    try {
      const errors: string[] = [];
      const updates: Record<string, number> = {};
      if (budgetDraft.daily_budget !== "") {
        const val = parseInt(budgetDraft.daily_budget, 10);
        if (isNaN(val)) {
          errors.push("Daily Budget must be a number");
        } else {
          updates.daily_budget = val;
        }
      }
      if (budgetDraft.rate_limit_rpm !== "") {
        const val = parseInt(budgetDraft.rate_limit_rpm, 10);
        if (isNaN(val)) {
          errors.push("RPM Limit must be a number");
        } else {
          updates.rate_limit_rpm = val;
        }
      }
      if (budgetDraft.warning_pct !== "") {
        const val = parseInt(budgetDraft.warning_pct, 10);
        if (isNaN(val)) {
          errors.push("Warning % must be a number");
        } else {
          updates.warning_pct = val;
        }
      }
      if (errors.length > 0) {
        setBudgetError(errors.join("; "));
        return;
      }
      await updateLLMBudget(updates);
      setBudgetSaveResult("Settings saved");
      setEditingBudget(false);
    } catch (e) {
      setBudgetSaveResult("Failed: " + (e as Error).message);
    } finally {
      setBudgetSaving(false);
    }
  };

  return (
    <Card title="Admin" className="lg:col-span-2 xl:col-span-3">
      {confirmAction && (
        <div className="mb-4 rounded border border-yellow-700 bg-yellow-900/30 p-3">
          <p className="mb-2 text-sm text-yellow-200">
            Are you sure you want to {confirmAction.label}? This cannot be undone.
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => void confirmAction.action()}
              className="rounded bg-red-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-600"
            >
              Confirm
            </button>
            <button
              onClick={() => setConfirmAction(null)}
              className="rounded border border-gray-700 px-3 py-1.5 text-xs font-medium text-gray-400 hover:text-gray-200"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      <div className="mb-6">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
          System Stats
        </h3>
        {stats && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <div className="rounded border border-gray-800 px-3 py-2">
              <p className="text-xs text-gray-500">Facts</p>
              <p className="text-lg font-semibold text-gray-200">
                {stats.facts}
              </p>
            </div>
            <div className="rounded border border-gray-800 px-3 py-2">
              <p className="text-xs text-gray-500">Conversations</p>
              <p className="text-lg font-semibold text-gray-200">
                {stats.conversations}
              </p>
            </div>
            <div className="rounded border border-gray-800 px-3 py-2">
              <p className="text-xs text-gray-500">Calendar</p>
              <p className="text-lg font-semibold text-gray-200">
                {stats.source_items.calendar ?? 0}
              </p>
            </div>
            <div className="rounded border border-gray-800 px-3 py-2">
              <p className="text-xs text-gray-500">Email</p>
              <p className="text-lg font-semibold text-gray-200">
                {stats.source_items.email ?? 0}
              </p>
            </div>
            <div className="rounded border border-gray-800 px-3 py-2">
              <p className="text-xs text-gray-500">Notes</p>
              <p className="text-lg font-semibold text-gray-200">
                {stats.source_items.notes ?? 0}
              </p>
            </div>
            <div className="rounded border border-gray-800 px-3 py-2">
              <p className="text-xs text-gray-500">Vectors</p>
              <p className="text-lg font-semibold text-gray-200">
                {stats.vector_documents}
              </p>
            </div>
          </div>
        )}
        <button
          onClick={handleReindex}
          disabled={reindexing}
          className="mt-3 rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50"
        >
          {reindexing ? "Re-indexing..." : "Re-index Vector Store"}
        </button>
        {reindexResult && (
          <p className="mt-2 text-xs text-gray-400">{reindexResult}</p>
        )}
      </div>

      <div className="mb-6">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
          Clear Memory
        </h3>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => confirmAndClear("facts", "clear all facts")}
            disabled={clearing}
            className="rounded bg-red-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-600 disabled:opacity-50"
          >
            Clear Facts
          </button>
          <button
            onClick={() => confirmAndClear("conversations", "clear all conversations")}
            disabled={clearing}
            className="rounded bg-red-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-600 disabled:opacity-50"
          >
            Clear Conversations
          </button>
          <button
            onClick={() => confirmAndClear("source_items", "clear all source items", undefined, "calendar")}
            disabled={clearing}
            className="rounded bg-red-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-600 disabled:opacity-50"
          >
            Clear Calendar
          </button>
          <button
            onClick={() => confirmAndClear("source_items", "clear all source items", undefined, "email")}
            disabled={clearing}
            className="rounded bg-red-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-600 disabled:opacity-50"
          >
            Clear Email
          </button>
          <button
            onClick={() => confirmAndClear("source_items", "clear all source items", undefined, "notes")}
            disabled={clearing}
            className="rounded bg-red-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-600 disabled:opacity-50"
          >
            Clear Notes
          </button>
          <button
            onClick={() => confirmAndClear("all", "clear ALL data (facts, conversations, and source items)")}
            disabled={clearing}
            className="rounded bg-red-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-800 disabled:opacity-50"
          >
            Clear All
          </button>
        </div>
        {clearResult && (
          <p className="mt-2 text-xs text-gray-400">{clearResult}</p>
        )}
      </div>

      <div className="mb-6">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
          Manual Sync
        </h3>
        <div className="flex flex-wrap gap-2">
          {(["calendar", "email", "notes"] as const).map((source) => (
            <button
              key={source}
              onClick={() => void handleSyncSource(source)}
              disabled={syncingSource !== null}
              className="rounded bg-indigo-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-600 disabled:opacity-50"
            >
              {syncingSource === source
                ? "Syncing " + source + "..."
                : "Sync " + source.charAt(0).toUpperCase() + source.slice(1)}
            </button>
          ))}
        </div>
        {syncResult && (
          <p className="mt-2 text-xs text-gray-400">{syncResult}</p>
        )}
      </div>

      <div className="mb-6">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
          Run Triage
        </h3>
        <div className="flex flex-wrap gap-2">
          {(["calendar", "notes"] as const).map((source) => (
            <button
              key={source}
              onClick={() => void handleRunTriage(source)}
              disabled={triagingSource !== null}
              className="rounded bg-teal-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-600 disabled:opacity-50"
            >
              {triagingSource === source
                ? "Triaging " + source + "..."
                : "Triage " + source.charAt(0).toUpperCase() + source.slice(1)}
            </button>
          ))}
        </div>
        {triageResult && (
          <p className="mt-2 text-xs text-gray-400">{triageResult}</p>
        )}
      </div>

      <div className="mb-6">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
          LLM Token Budget
        </h3>
        {llmBudget && (
          <div>
            <div className="mb-2 flex items-center gap-3">
              <div className="h-2 flex-1 rounded-full bg-gray-800">
                <div
                  className={
                    "h-2 rounded-full transition-all " +
                    (llmBudget.is_exhausted
                      ? "bg-red-500"
                      : llmBudget.pct_used >= llmBudget.warning_pct
                        ? "bg-yellow-500"
                        : "bg-green-500")
                  }
                  style={{ width: Math.min(100, llmBudget.pct_used) + "%" }}
                />
              </div>
              <span className="text-xs text-gray-400">
                {llmBudget.pct_used}%
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <div className="rounded border border-gray-800 px-3 py-2">
                <p className="text-xs text-gray-500">Used Today</p>
                <p className="text-lg font-semibold text-gray-200">
                  {(llmBudget.tokens_used / 1000).toFixed(1)}k
                </p>
              </div>
              <div className="rounded border border-gray-800 px-3 py-2">
                <p className="text-xs text-gray-500">Daily Budget</p>
                <p className="text-lg font-semibold text-gray-200">
                  {llmBudget.daily_budget === 0
                    ? "Unlimited"
                    : (llmBudget.daily_budget / 1000).toFixed(0) + "k"}
                </p>
              </div>
              <div className="rounded border border-gray-800 px-3 py-2">
                <p className="text-xs text-gray-500">Calls Today</p>
                <p className="text-lg font-semibold text-gray-200">
                  {llmBudget.calls_today}
                </p>
              </div>
              <div className="rounded border border-gray-800 px-3 py-2">
                <p className="text-xs text-gray-500">Rate Limit</p>
                <p className="text-lg font-semibold text-gray-200">
                  {llmBudget.rate_limit_rpm === 0
                    ? "None"
                    : llmBudget.rate_limit_rpm + "/min"}
                </p>
              </div>
            </div>
            {llmBudget.is_exhausted && (
              <p className="mt-2 text-xs font-medium text-red-400">
                Daily budget exhausted. Background LLM calls are paused until tomorrow.
              </p>
            )}
            {llmHistory && llmHistory.hourly.length > 0 && (
              <div className="mt-3">
                <p className="mb-1 text-xs text-gray-500">Usage Trend (24h)</p>
                <div className="flex h-12 items-end gap-px">
                  {llmHistory.hourly.map((h) => {
                    const maxTokens = Math.max(...llmHistory.hourly.map((x) => x.total_tokens), 1);
                    const heightPct = (h.total_tokens / maxTokens) * 100;
                    return (
                      <div
                        key={h.hour}
                        className="flex-1 rounded-t bg-blue-500/60"
                        style={{ height: Math.max(1, heightPct) + "%" }}
                        title={h.hour + ": " + (h.total_tokens / 1000).toFixed(1) + "k tokens, " + h.call_count + " calls"}
                      />
                    );
                  })}
                </div>
                <div className="mt-0.5 flex justify-between text-[10px] text-gray-600">
                  <span>{llmHistory.hourly[0]?.hour.slice(11, 16) ?? ""}</span>
                  <span>{llmHistory.hourly[llmHistory.hourly.length - 1]?.hour.slice(11, 16) ?? ""}</span>
                </div>
              </div>
            )}
          </div>
        )}
        {llmUsage && llmUsage.by_operation.length > 0 && (
          <div className="mt-3">
            <p className="mb-1 text-xs text-gray-500">Usage by Operation (today)</p>
            <div className="space-y-1">
              {llmUsage.by_operation.map((op) => (
                <div
                  key={op.operation}
                  className="flex items-center justify-between text-xs"
                >
                  <span className="text-gray-400">{op.operation}</span>
                  <span className="text-gray-500">
                    {(op.total_tokens / 1000).toFixed(1)}k tokens / {op.call_count} calls
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="mt-3">
          {!editingBudget ? (
            <button
              onClick={() => {
                setBudgetDraft({
                  daily_budget: llmBudget ? String(llmBudget.daily_budget) : "",
                  rate_limit_rpm: llmBudget ? String(llmBudget.rate_limit_rpm) : "",
                  warning_pct: llmBudget ? String(llmBudget.warning_pct) : "",
                });
                setEditingBudget(true);
                setBudgetSaveResult(null);
                setBudgetError(null);
              }}
              className="rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200"
            >
              Edit Settings
            </button>
          ) : (
            <div className="rounded border border-gray-700 p-3">
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="block text-xs text-gray-500">Daily Budget</label>
                  <input
                    type="number"
                    value={budgetDraft.daily_budget}
                    onChange={(e) => setBudgetDraft((d) => ({ ...d, daily_budget: e.target.value }))}
                    className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-200"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500">RPM Limit</label>
                  <input
                    type="number"
                    value={budgetDraft.rate_limit_rpm}
                    onChange={(e) => setBudgetDraft((d) => ({ ...d, rate_limit_rpm: e.target.value }))}
                    className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-200"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500">Warning %</label>
                  <input
                    type="number"
                    value={budgetDraft.warning_pct}
                    onChange={(e) => setBudgetDraft((d) => ({ ...d, warning_pct: e.target.value }))}
                    className="mt-1 w-full rounded border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-200"
                  />
                </div>
              </div>
              {budgetError && (
                <p className="mt-2 text-xs text-red-400">{budgetError}</p>
              )}
              <div className="mt-2 flex gap-2">
                <button
                  onClick={() => void handleSaveBudget()}
                  disabled={budgetSaving}
                  className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50"
                >
                  {budgetSaving ? "Saving..." : "Save"}
                </button>
                <button
                  onClick={() => setEditingBudget(false)}
                  className="rounded border border-gray-700 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
          {budgetSaveResult && (
            <p className="mt-1 text-xs text-gray-400">{budgetSaveResult}</p>
          )}
        </div>
      </div>

      <div className="mb-6">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
          Background Scanners
        </h3>
        {scannerStatus && scannerStatus.scanners.length > 0 ? (
          <div className="space-y-1">
            {scannerStatus.scanners.map((s) => (
              <div key={s.name} className="flex items-center gap-2">
                <span
                  className={
                    "inline-block h-2 w-2 rounded-full " +
                    (s.running ? "bg-green-500" : "bg-red-500")
                  }
                />
                <span className="text-xs text-gray-400">{s.name}</span>
                <span className="text-xs text-gray-600">
                  {s.running ? "running" : "stopped"}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-gray-500">No scanners active</p>
        )}
      </div>

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">
          Connections
        </h3>
        <div className="space-y-2">
          {(connections?.connections ?? []).map((conn: ConnectionStatus) => (
            <div
              key={conn.name}
              className="flex items-center justify-between rounded border border-gray-800 px-3 py-2"
            >
              <div className="flex items-center gap-2">
                <span
                  className={
                    "inline-block h-2 w-2 rounded-full " +
                    (conn.reachable
                      ? "bg-green-500"
                      : conn.configured
                        ? "bg-yellow-500"
                        : "bg-gray-500")
                  }
                />
                <span className="text-sm font-medium text-gray-300">
                  {conn.name.charAt(0).toUpperCase() + conn.name.slice(1)}
                </span>
                <span className="text-xs text-gray-500">
                  {conn.detail ?? conn.error ?? ""}
                </span>
              </div>
              <button
                onClick={() => handleTestConnection(conn.name)}
                disabled={testingSource === conn.name}
                className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-400 hover:text-gray-200 disabled:opacity-50"
              >
                {testingSource === conn.name ? "Testing..." : "Test"}
              </button>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
