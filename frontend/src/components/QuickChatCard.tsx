import { useState, useRef } from "react";
import Card from "./Card";
import { postChat } from "../services/api";
import type { ChatResponse } from "../types";

export default function QuickChatCard(): React.ReactElement {
  const [input, setInput] = useState("");
  const [reply, setReply] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || sending) return;
    setSending(true);
    try {
      const result: ChatResponse = await postChat(input.trim(), conversationId ?? undefined);
      setReply(result.reply);
      setConversationId(result.conversation_id);
      setInput("");
    } catch (err) {
      setReply("Error: " + (err as Error).message);
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  };

  return (
    <Card title="Quick Chat" className="lg:col-span-2 xl:col-span-2">
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask your assistant..."
          disabled={sending}
          className="flex-1 rounded border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:border-gray-600 focus:outline-none disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={sending}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
        >
          {sending ? "..." : "Ask"}
        </button>
      </form>
      {reply !== null && (
        <div className="mt-3 rounded border border-gray-800 bg-gray-800/50 p-3 text-sm text-gray-300 whitespace-pre-wrap">
          {reply}
        </div>
      )}
    </Card>
  );
}
