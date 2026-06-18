import { useState } from "react";
import { useScratchPanel } from "./useScratchPanel";
import { ReviewQueue } from "./ReviewPanel";

const STATE_LABEL: Record<string, string> = {
  unrouted: "Unrouted",
  routed_task: "→ Task",
  kept_note: "Note",
  in_review: "In review",
  resolved: "Resolved",
};

export function CapturePanel() {
  const scratch = useScratchPanel();
  const [text, setText] = useState("");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    scratch.capture(t).catch(() => {});
    setText("");
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Scratchpad</h2>
        <button
          className="panel-refresh"
          onClick={scratch.routeNow}
          disabled={scratch.busy}
          title="Route all unrouted entries now"
        >
          {scratch.busy ? "Routing…" : "Route now"}
        </button>
      </div>

      <form className="capture-form" onSubmit={submit}>
        <textarea
          className="capture-input"
          value={text}
          placeholder="Dump a thought — it files itself…"
          rows={2}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
          }}
        />
        <button
          type="submit"
          className="capture-submit"
          disabled={!text.trim()}
        >
          Capture
        </button>
      </form>

      {scratch.error && <p className="panel-error">{scratch.error}</p>}

      <ReviewQueue
        items={scratch.reviewItems}
        onConfirm={scratch.confirmItem}
        onDismiss={scratch.dismissItem}
      />

      <h3>Recent</h3>
      {scratch.isLoading ? (
        <p className="panel-status">Loading…</p>
      ) : scratch.entries.length === 0 ? (
        <p className="panel-status">Nothing captured yet.</p>
      ) : (
        <ul className="scratch-entries">
          {scratch.entries.map((e) => (
            <li key={e.id}>
              <span className="scratch-text">{e.text}</span>
              <span className={`scratch-badge state-${e.routing_state}`}>
                {STATE_LABEL[e.routing_state] ?? e.routing_state}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
