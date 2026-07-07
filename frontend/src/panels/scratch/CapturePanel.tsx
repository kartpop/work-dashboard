import { useLayoutEffect, useRef, useState } from "react";
import type { ReviewFields } from "./useScratchPanel";
import { useScratchPanel } from "./useScratchPanel";
import { ReviewQueue } from "./ReviewPanel";
import {
  handleEnter,
  indentLine,
  outdentLine,
  type EditorState,
} from "./bulletEditor";

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
  const [captureError, setCaptureError] = useState<string | null>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  // A bullet keystroke sets both value and caret; the textarea is controlled, so
  // stash the desired selection and re-apply it once React has flushed the value.
  const pendingSel = useRef<{ start: number; end: number } | null>(null);

  useLayoutEffect(() => {
    if (pendingSel.current && taRef.current) {
      taRef.current.selectionStart = pendingSel.current.start;
      taRef.current.selectionEnd = pendingSel.current.end;
      pendingSel.current = null;
    }
  }, [text]);

  const apply = (next: EditorState) => {
    pendingSel.current = { start: next.selectionStart, end: next.selectionEnd };
    setText(next.value);
  };

  // Capture the WHOLE editor as one entry, verbatim. Clear only on success; on
  // failure leave the text in place with the error shown.
  const submit = async () => {
    if (!text.trim()) return;
    try {
      await scratch.capture(text);
      setText("");
      setCaptureError(null);
    } catch (err) {
      setCaptureError((err as Error).message);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const ta = e.currentTarget;
    const snap: EditorState = {
      value: text,
      selectionStart: ta.selectionStart,
      selectionEnd: ta.selectionEnd,
    };
    // Shift+Enter (primary) / Cmd|Ctrl+Enter (secondary) = capture. Plain Enter never submits.
    if (e.key === "Enter" && (e.shiftKey || e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void submit();
      return;
    }
    if (e.key === "Enter") {
      const next = handleEnter(snap);
      if (next) {
        e.preventDefault(); // bullet continue/exit; else fall through to a plain newline
        apply(next);
      }
      return;
    }
    if (e.key === "Tab") {
      e.preventDefault(); // Tab is captive inside the editor
      apply(e.shiftKey ? outdentLine(snap) : indentLine(snap));
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault(); // blur so keyboard users can tab away past the captive editor
      ta.blur();
    }
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

      <form
        className="capture-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <textarea
          ref={taRef}
          className="capture-input"
          value={text}
          placeholder="Dump a thought — `- ` starts a bullet, Shift+Enter files it…"
          rows={4}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <button
          type="submit"
          className="capture-submit"
          disabled={!text.trim()}
        >
          Capture
        </button>
      </form>

      {captureError && (
        <p className="panel-error">Capture failed: {captureError}</p>
      )}
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
