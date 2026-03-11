import { useCallback } from "react";
import Card from "./Card";
import { usePolling } from "../hooks/usePolling";
import { getUpcomingEvents } from "../services/api";
import type { UpcomingEventsResponse, CalendarEvent } from "../types";

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] ?? s[v] ?? s[0]);
}

function formatEventDate(dateStr: string): string {
  const toUtc = (s: string) => s.includes("Z") || s.includes("+") || s.match(/-\d{2}:\d{2}$/) ? s : s + "Z";
  const d = new Date(toUtc(dateStr));
  const now = new Date();
  const dayName = d.toLocaleDateString([], { weekday: "long" });
  const month = d.toLocaleDateString([], { month: "short" });
  const day = ordinal(d.getDate());
  if (d.getFullYear() !== now.getFullYear()) {
    return `${dayName}, ${month} ${day}, ${d.getFullYear()}`;
  }
  return `${dayName}, ${month} ${day}`;
}

function formatEventTime(event: CalendarEvent): string {
  const meta = event.raw_metadata;
  const start = (meta.dtstart ?? meta.start) as string | undefined;
  const end = (meta.dtend ?? meta.end) as string | undefined;

  if (!start) return "Time not available";

  const toUtc = (s: string) => s.includes("Z") || s.includes("+") || s.match(/-\d{2}:\d{2}$/) ? s : s + "Z";
  const startTime = new Date(toUtc(start)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  if (end) {
    const endTime = new Date(toUtc(end)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return startTime + " - " + endTime;
  }

  return startTime;
}

export default function UpcomingEventsCard(): React.ReactElement {
  const fetcher = useCallback(() => getUpcomingEvents(10080), []);
  const { data, loading, error } = usePolling<UpcomingEventsResponse>(fetcher, 300000);

  if (loading && data === null) {
    return <Card title="Upcoming Events"><p className="text-sm text-gray-500">Loading...</p></Card>;
  }

  if (error) {
    return <Card title="Upcoming Events"><p className="text-sm text-red-400">{error}</p></Card>;
  }

  if (!data || data.events.length === 0) {
    return <Card title="Upcoming Events"><p className="text-sm text-gray-500">No upcoming events.</p></Card>;
  }

  return (
    <Card title="Upcoming Events">
      <ul className="space-y-3">
        {data.events.map((event) => (
          <li key={event.id} className="rounded border border-gray-800 px-3 py-2">
            <p className="text-sm font-medium text-gray-200">{event.title}</p>
            <p className="text-xs text-gray-400">
              {(event.raw_metadata.dtstart ?? event.raw_metadata.start) ? formatEventDate(String(event.raw_metadata.dtstart ?? event.raw_metadata.start)) : ""}
            </p>
            <p className="text-xs text-gray-500">{formatEventTime(event)}</p>
            {event.content && (
              <p className="mt-1 text-xs text-gray-400">
                {event.content.slice(0, 120)}{event.content.length > 120 ? "..." : ""}
              </p>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
