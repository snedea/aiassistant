import { useCallback } from "react";
import Card from "./Card";
import { usePolling } from "../hooks/usePolling";
import { getRecentEmailSummaries } from "../services/api";
import type { EmailSummariesResponse } from "../types";

function importanceBadgeClass(importance: string): string {
  if (importance === "urgent") return "bg-red-900 text-red-300";
  if (importance === "important") return "bg-yellow-900 text-yellow-300";
  return "bg-gray-800 text-gray-400";
}

export default function EmailSummariesCard(): React.ReactElement {
  const fetcher = useCallback(() => getRecentEmailSummaries(), []);
  const { data, loading, error } = usePolling<EmailSummariesResponse>(fetcher, 300000);

  if (loading && data === null) {
    return <Card title="Recent Emails"><p className="text-sm text-gray-500">Loading...</p></Card>;
  }

  if (error) {
    return <Card title="Recent Emails"><p className="text-sm text-red-400">{error}</p></Card>;
  }

  if (!data || data.summaries.length === 0) {
    return <Card title="Recent Emails"><p className="text-sm text-gray-500">No email summaries yet.</p></Card>;
  }

  return (
    <Card title="Recent Emails">
      <ul className="space-y-3">
        {data.summaries.map((summary) => (
          <li key={summary.external_id} className="rounded border border-gray-800 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <p className="truncate text-sm font-medium text-gray-200">{summary.subject}</p>
              <span className={"shrink-0 rounded-full px-2 py-0.5 text-xs font-medium " + importanceBadgeClass(summary.importance)}>
                {summary.importance}
              </span>
            </div>
            <p className="text-xs text-gray-500">From: {summary.from}</p>
            {summary.summary && (
              <p className="mt-1 text-xs text-gray-400">{summary.summary}</p>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
