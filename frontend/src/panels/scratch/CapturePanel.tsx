import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { ReviewFields, ScratchEntry } from "./useScratchPanel";
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

// A capture is "unresolved" until the router files it — those stay at the top of
// RECENT; everything else is a routed/resolved confirmation tail (dimmed, capped).
const UNRESOLVED_STATES = new Set(["unrouted", "in_review"]);
const ROUTED_TAIL_MAX = 5;

// Shift+Enter files the whole editor, but the POST is HELD this long so an
// accidental capture is recoverable with one click (undo-by-never-sending — a
// mirror of the g4a deferred-delete). Undo fires zero backend writes.
const CAPTURE_UNDO_MS = 5000;

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

  // ── Deferred-capture undo toast (goal 7a) ─────────────────────────────────
  // Shift+Enter clears the editor immediately but HOLDS the POST for ~5s behind
  // an "Undo" toast. The held text lives in a ref (survives re-renders); the
  // capture fn is read through a ref so the commit/flush closures stay stable and
  // an unmount can flush without re-firing on every render.
  const [showUndo, setShowUndo] = useState(false);
  const pendingRef = useRef<string | null>(null);
  const timerRef = useRef<number | null>(null);
  const captureFnRef = useRef(scratch.capture);
  useEffect(() => {
    captureFnRef.current = scratch.capture;
  });

  // Restore held text into the editor: prepend above anything the user typed
  // during the window (blank line between), else just set it. Zero writes.
  const restoreHeld = useCallback((held: string) => {
    setText((cur) => (cur.trim() ? `${held}\n\n${cur}` : held));
  }, []);

  // Send the still-held capture (window lapsed, or a new capture supersedes it —
  // one toast at a time). A POST failure surfaces the error and restores the text.
  const commitPending = useCallback(async () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    const held = pendingRef.current;
    pendingRef.current = null;
    setShowUndo(false);
    if (held === null) return;
    try {
      await captureFnRef.current(held);
      setCaptureError(null);
    } catch (err) {
      setCaptureError((err as Error).message);
      restoreHeld(held);
    }
  }, [restoreHeld]);

  // Capture the WHOLE editor as one entry, verbatim — but defer the write. Clear
  // the editor now; the POST fires only once the undo window closes.
  const submit = () => {
    if (!text.trim()) return;
    void commitPending(); // flush any previous still-held capture first
    pendingRef.current = text;
    setText("");
    setCaptureError(null);
    setShowUndo(true);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      void commitPending();
    }, CAPTURE_UNDO_MS);
  };

  // Undo: cancel the held POST and restore the text — never sends anything.
  const undoCapture = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    const held = pendingRef.current;
    pendingRef.current = null;
    setShowUndo(false);
    if (held !== null) restoreHeld(held);
  };

  // On unmount, flush a still-held capture so it is never silently lost (fire the
  // POST directly, no state updates on a gone component).
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      const held = pendingRef.current;
      pendingRef.current = null;
      if (held && held.trim()) void captureFnRef.current(held).catch(() => {});
    };
  }, []);

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

  // RECENT shows unresolved captures (unrouted + in-review) first, then only the
  // ~5 most-recent routed/resolved as a dimmed confirmation tail — nothing older.
  // `entries` is already newest-first (server orders by desc id).
  const unresolved = scratch.entries.filter((e) =>
    UNRESOLVED_STATES.has(e.routing_state),
  );
  const routedTail = scratch.entries
    .filter((e) => !UNRESOLVED_STATES.has(e.routing_state))
    .slice(0, ROUTED_TAIL_MAX);
  const recent: Array<ScratchEntry & { dimmed?: boolean }> = [
    ...unresolved,
    ...routedTail.map((e) => ({ ...e, dimmed: true })),
  ];

  return (
    <section className="panel capture-panel">
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
          submit();
        }}
      >
        <textarea
          ref={taRef}
          className="capture-input"
          value={text}
          placeholder="Dump a thought — `- ` starts a bullet, Shift+Enter files it…"
          rows={12}
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

      <div className="scratch-recent">
        <h3>Recent</h3>
        {scratch.isLoading ? (
          <p className="panel-status">Loading…</p>
        ) : recent.length === 0 ? (
          <p className="panel-status">Nothing captured yet.</p>
        ) : (
          <ul className="scratch-entries">
            {recent.map((e) => (
              <li key={e.id} className={e.dimmed ? "scratch-entry--dim" : ""}>
                <span className="scratch-text">{e.text}</span>
                <span className={`scratch-badge state-${e.routing_state}`}>
                  {STATE_LABEL[e.routing_state] ?? e.routing_state}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {showUndo && (
        <div className="toast toast--action toast--capture" role="status">
          <span>Captured — filing in a moment…</span>
          <button className="toast-undo" onClick={undoCapture}>
            Undo
          </button>
        </div>
      )}
    </section>
  );
}
