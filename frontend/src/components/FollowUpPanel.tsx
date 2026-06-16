/**
 * FollowUpPanel — after-meeting capture (Stage 5, functional).
 *
 * Advisor types meeting notes → POST /api/followup/{clientId} persists them as
 * client context and triggers a background brief regeneration, so the notes
 * feed into the next brief (consumed by the Client-Insights agent).
 */
import { useState } from "react";
import { postFollowUp } from "../api";

type Status = "idle" | "saving" | "saved" | "error";

export default function FollowUpPanel({ clientId }: { clientId: string }) {
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState("");

  async function save() {
    const text = notes.trim();
    if (!text) return;
    setStatus("saving");
    setMessage("");
    try {
      const res = await postFollowUp(clientId, text);
      setStatus("saved");
      setMessage(
        `Captured (${res.saved}). It will feed into the next brief — regenerating now.`
      );
      setNotes("");
    } catch (err) {
      setStatus("error");
      setMessage(err instanceof Error ? err.message : "Failed to save notes");
    }
  }

  return (
    <div className="bg-paper border border-gray-300 rounded-[14px] p-6">
      <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-clay mb-1">
        After-meeting capture
      </p>
      <p className="text-xs font-mono text-gray-500 mb-4">
        Notes logged here feed back into the next brief.
      </p>

      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Enter meeting notes, client decisions, action items…"
        rows={5}
        className="w-full rounded-lg border border-gray-300 bg-white px-4 py-3 text-sm font-serif text-gray-800 placeholder:text-gray-400 resize-none focus:outline-none focus:border-clay"
      />

      <div className="mt-3 flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={save}
          disabled={status === "saving" || !notes.trim()}
          className="rounded-lg bg-clay px-4 py-2 text-sm font-mono text-white transition-opacity hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {status === "saving" ? "Saving…" : "Save & feed into next brief"}
        </button>
        {status === "saved" && (
          <span className="text-xs font-mono text-green-700">{message}</span>
        )}
        {status === "error" && (
          <span className="text-xs font-mono text-red-600">{message}</span>
        )}
      </div>
    </div>
  );
}
