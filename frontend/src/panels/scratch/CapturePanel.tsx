import { useState } from "react";
import type { ReviewFields } from "./useScratchPanel";
import { useScratchPanel } from "./useScratchPanel";
import { ReviewQueue } from "./ReviewPanel";

const STATE_LABEL: Record<string, string> = {
  unrouted: "Unrouted",
  routed_task: "→ Task",
  kept_note: "Note",
  in_review: "In review",
  resolved: "Resolved",
};

// `onRouted` lets the (separately-owned) Tasks panel refresh when routing or a
// review confirmation created a Google task — the panels share no state.
export function CapturePanel({ onRouted }: { onRouted?: () => void }) {
  const scratch = useScratchPanel();
  const [text, setText] = useState("");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    scratch.capture(t).catch(() => {});
    setText("");
  };

  const routeNow = () => {
    scratch.routeNow().then((created) => {
      if (created) onRouted?.();
    });
  };

  const confirmItem = async (
    itemId: number,
    override?: { destination?: string; fields?: ReviewFields },
  ) => {
    const created = await scratch.confirmItem(itemId, override);
    if (created) onRouted?.();
    return created;
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Scratchpad</h2>
        <button
          className="panel-refresh"
          onClick={routeNow}
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
        onConfirm={confirmItem}
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
