import { useCallback } from "react";
import Card from "./Card";
import { usePolling } from "../hooks/usePolling";
import { getRecentTriages } from "../services/api";
import type { TriageResponse } from "../types";

function priorityBadgeClass(priority: string): string {
  if (priority === "urgent") return "bg-red-900 text-red-300";
  if (priority === "important") return "bg-yellow-900 text-yellow-300";
  if (priority === "fyi") return "bg-blue-900 text-blue-300";
  if (priority === "ignore") return "bg-gray-800 text-gray-500";
  return "bg-gray-800 text-gray-400";
}

export default function TriageCard(): React.ReactElement {
  const fetcher = useCallback(() => getRecentTriages(), []);
  const { data, loading, error } = usePolling<TriageResponse>(fetcher, 60000);

  if (loading && data === null) {
    return <Card title="Triaged Items"><p className="text-sm text-gray-500">Loading...</p></Card>;
  }

  if (error) {
    return <Card title="Triaged Items"><p className="text-sm text-red-400">{error}</p></Card>;
  }

  if (!data || data.triages.length === 0) {
    return <Card title="Triaged Items"><p className="text-sm text-gray-500">No triaged items.</p></Card>;
  }

  return (
    <Card title="Triaged Items">
      <ul className="space-y-2">
        {data.triages.map((triage) => (
          <li key={triage.external_id} className="rounded border border-gray-800 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <p className="truncate text-sm font-medium text-gray-200">{triage.title}</p>
              <span className={"shrink-0 rounded-full px-2 py-0.5 text-xs font-medium " + priorityBadgeClass(triage.priority)}>
                {triage.priority}
              </span>
            </div>
            <p className="text-xs text-gray-500 capitalize">{triage.source_type}</p>
            {triage.summary && (
              <p className="mt-1 text-xs text-gray-400">{triage.summary}</p>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
