import { useCallback } from "react";
import Card from "./Card";
import { usePolling } from "../hooks/usePolling";
import { getSourceItems } from "../services/api";
import type { SourceItemsResponse } from "../types";

export default function RecentNotesCard(): React.ReactElement {
  const fetcher = useCallback(() => getSourceItems("notes", 10), []);
  const { data, loading, error } = usePolling<SourceItemsResponse>(fetcher, 300000);

  if (loading && data === null) {
    return <Card title="Recent Notes"><p className="text-sm text-gray-500">Loading...</p></Card>;
  }

  if (error) {
    return <Card title="Recent Notes"><p className="text-sm text-red-400">{error}</p></Card>;
  }

  if (!data || data.items.length === 0) {
    return <Card title="Recent Notes"><p className="text-sm text-gray-500">No notes synced yet.</p></Card>;
  }

  return (
    <Card title="Recent Notes">
      <ul className="space-y-3">
        {data.items.map((note) => (
          <li key={note.id} className="rounded border border-gray-800 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <p className="truncate text-sm font-medium text-gray-200">{note.title || "(untitled)"}</p>
              {!!note.raw_metadata?.folder && (
                <span className="shrink-0 rounded-full bg-gray-800 px-2 py-0.5 text-xs text-gray-400">
                  {String(note.raw_metadata.folder)}
                </span>
              )}
            </div>
            {note.content && (
              <p className="mt-1 text-xs text-gray-400 line-clamp-2">{note.content}</p>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
