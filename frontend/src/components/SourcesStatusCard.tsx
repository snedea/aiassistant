import { useCallback } from "react";
import Card from "./Card";
import { usePolling } from "../hooks/usePolling";
import { getScanState, getSourceHealth } from "../services/api";
import type { ScanStateResponse, SourceHealthResponse } from "../types";

function statusDotClass(status: string): string {
  if (status === "idle") return "bg-green-500";
  if (status === "syncing") return "bg-blue-500 animate-pulse";
  if (status === "error") return "bg-red-500";
  return "bg-gray-500";
}

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString + (isoString.includes("Z") ? "" : "Z"));
  const diff = Math.floor((Date.now() - date.getTime()) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return Math.floor(diff / 60) + "m ago";
  if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
  return Math.floor(diff / 86400) + "d ago";
}

function staleIndicator(isStale: boolean): React.ReactElement | null {
  if (!isStale) return null;
  return (
    <span className="ml-2 rounded bg-yellow-900 px-1.5 py-0.5 text-xs font-medium text-yellow-300">
      STALE
    </span>
  );
}

export default function SourcesStatusCard(): React.ReactElement {
  const scanFetcher = useCallback(() => getScanState(), []);
  const { data: scanData, loading: scanLoading, error: scanError } = usePolling<ScanStateResponse>(scanFetcher, 30000);
  const healthFetcher = useCallback(() => getSourceHealth(), []);
  const { data: healthData } = usePolling<SourceHealthResponse>(healthFetcher, 30000);

  if (scanLoading && scanData === null) {
    return <Card title="Sources"><p className="text-sm text-gray-500">Loading...</p></Card>;
  }

  if (scanError) {
    return <Card title="Sources"><p className="text-sm text-red-400">{scanError}</p></Card>;
  }

  return (
    <Card title="Sources">
      <div className="space-y-3">
        {scanData?.scan_states.map((state) => (
          <div key={state.id} className="flex items-center justify-between rounded border border-gray-800 px-3 py-2">
            <div>
              <p className="text-sm font-medium text-gray-200 capitalize">
                {state.source_type}
                {healthData?.sources.find((h) => h.source_type === state.source_type)?.is_stale
                  ? staleIndicator(true)
                  : null}
              </p>
              <p className="text-xs text-gray-500">
                {state.last_synced_at ? "Last synced: " + formatRelativeTime(state.last_synced_at) : "Never synced"}
              </p>
              {state.error_message && (
                <p className="text-xs text-red-400">{state.error_message}</p>
              )}
            </div>
            <div className="flex items-center gap-2">
              <div className={"h-2 w-2 rounded-full " + statusDotClass(state.status)}></div>
              <span className="text-xs text-gray-500">{state.items_synced} items</span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
