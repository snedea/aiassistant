import { useCallback } from "react";
import Card from "./Card";
import { usePolling } from "../hooks/usePolling";
import { getMemoryFacts, deleteMemoryFact } from "../services/api";
import type { MemoryResponse, Fact } from "../types";

export default function MemoryCard(): React.ReactElement {
  const fetcher = useCallback(() => getMemoryFacts(), []);
  const { data, loading, error, refresh } = usePolling<MemoryResponse>(fetcher, 60000);

  const handleDelete = async (factId: number) => {
    try {
      await deleteMemoryFact(factId);
      refresh();
    } catch {
      // Refresh to show current state even on failure
      refresh();
    }
  };

  if (loading && data === null) {
    return <Card title="Memory" className="lg:col-span-2 xl:col-span-3"><p className="text-sm text-gray-500">Loading...</p></Card>;
  }

  if (error) {
    return <Card title="Memory" className="lg:col-span-2 xl:col-span-3"><p className="text-sm text-red-400">{error}</p></Card>;
  }

  if (!data || data.facts.length === 0) {
    return <Card title="Memory" className="lg:col-span-2 xl:col-span-3"><p className="text-sm text-gray-500">No memories stored yet.</p></Card>;
  }

  const grouped = new Map<string, Fact[]>();
  for (const fact of data.facts) {
    const existing = grouped.get(fact.category);
    if (existing) {
      existing.push(fact);
    } else {
      grouped.set(fact.category, [fact]);
    }
  }

  return (
    <Card title="Memory" className="lg:col-span-2 xl:col-span-3">
      {Array.from(grouped.entries()).map(([category, facts]) => (
        <div key={category} className="mb-4 last:mb-0">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-500">{category}</h3>
          <ul className="space-y-1">
            {facts.map((fact) => (
              <li key={fact.id}>
                <div className="flex items-start justify-between gap-2 rounded px-2 py-1 hover:bg-gray-800">
                  <span className="text-sm">
                    <span className="font-medium text-gray-200">{fact.subject}:</span>{" "}
                    <span className="text-gray-400">{fact.content}</span>
                  </span>
                  <button
                    onClick={() => handleDelete(fact.id)}
                    className="shrink-0 text-xs text-gray-600 hover:text-red-400"
                    title="Remove"
                  >
                    x
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </Card>
  );
}
