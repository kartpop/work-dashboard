import { useLayoutEffect, useRef, useState } from "react";
import type { ReviewFields, ReviewItem } from "./useScratchPanel";

// The note-body box grows with its content (a pasted MOM is reviewable, not a
// keyhole) up to a sensible max, then scrolls. Newlines are preserved by the
// textarea itself. Kept local — it's the only auto-sizing box in the panel.
const NOTE_TEXTAREA_MAX_PX = 320;

function useAutoSize(value: string) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, NOTE_TEXTAREA_MAX_PX)}px`;
    el.style.overflowY =
      el.scrollHeight > NOTE_TEXTAREA_MAX_PX ? "auto" : "hidden";
  }, [value]);
  return ref;
}

// The user resolves a review item as a task or a note only (goal 7c). `event`
// stays a valid classifier output — it just lands here for the user to pick one
// of these two (calendar is read-only).
const DESTINATIONS = ["task", "note"] as const;

// The router files a task into exactly one of these two lists (never a third) —
// keep in sync with the backend `schema.TargetList` / `PINNED_LIST_TITLES`.
const TARGET_LISTS = ["My Tasks", "Follow-ups"] as const;

// The default Doc sentinel in the destination dropdown — an empty target_doc_path
// (null) routes to the app's default "Dashboard — Notes" Doc.
const DEFAULT_DOC_LABEL = "Dashboard — Notes (default)";

interface Props {
  items: ReviewItem[];
  docPaths: string[];
  onConfirm: (
    id: number,
    override?: { destination?: string; fields?: ReviewFields },
  ) => Promise<boolean>;
  onDismiss: (id: number) => Promise<void>;
}

export function ReviewQueue({ items, docPaths, onConfirm, onDismiss }: Props) {
  if (items.length === 0) return null;
  return (
    <>
      <div className="review-queue-head">
        <h3>Review queue</h3>
      </div>
      <ul className="review-list">
        {items.map((item) => (
          <ReviewRow
            key={item.id}
            item={item}
            docPaths={docPaths}
            onConfirm={onConfirm}
            onDismiss={onDismiss}
          />
        ))}
      </ul>
    </>
  );
}

function ReviewRow({
  item,
  docPaths,
  onConfirm,
  onDismiss,
}: {
  item: ReviewItem;
  docPaths: string[];
  onConfirm: Props["onConfirm"];
  onDismiss: Props["onDismiss"];
}) {
  // Type defaults to the classifier's proposal when it's already task/note; an
  // event/unknown proposal defaults to `task` (the user picks the real one).
  const initialDest =
    item.destination === "note"
      ? "note"
      : ("task" as (typeof DESTINATIONS)[number]);
  const [destination, setDestination] =
    useState<(typeof DESTINATIONS)[number]>(initialDest);
  const [title, setTitle] = useState(item.fields.title ?? "");
  const [notes, setNotes] = useState(item.fields.notes ?? "");
  const [dueDate, setDueDate] = useState(item.fields.due_date ?? "");
  // Default to the classifier's choice when it's one of the two lists, else "My Tasks".
  const [targetList, setTargetList] = useState<(typeof TARGET_LISTS)[number]>(
    (TARGET_LISTS as readonly string[]).includes(item.fields.target_list ?? "")
      ? (item.fields.target_list as (typeof TARGET_LISTS)[number])
      : "My Tasks",
  );
  // Note fields: the raw body (fall back to the captured text) + the one-liner.
  const [noteText, setNoteText] = useState(
    item.fields.note_text ?? item.entry_text ?? "",
  );
  const [summary, setSummary] = useState(item.fields.summary ?? "");
  const noteTextRef = useAutoSize(noteText);
  // Destination Doc: prefill the classifier's proposed path when it's a real leaf,
  // else the default Doc ("" sentinel). The dropdown only offers real leaves.
  const [docPath, setDocPath] = useState(
    item.fields.target_doc_path &&
      docPaths.includes(item.fields.target_doc_path)
      ? item.fields.target_doc_path
      : "",
  );
  const [pending, setPending] = useState(false);

  const confirm = () => {
    setPending(true);
    // Send the (possibly edited) destination + fields. Deterministic code does the
    // write with whatever the user confirmed: a `task` fires create_task (+date),
    // a `note` appends the edited body + one-liner to the Doc.
    const fields: ReviewFields =
      destination === "note"
        ? {
            ...item.fields,
            note_text: noteText || null,
            summary: summary || null,
            target_doc_path: docPath || null,
          }
        : {
            ...item.fields,
            title: title || null,
            notes: notes || null,
            due_date: dueDate || null,
            target_list: targetList,
          };
    onConfirm(item.id, { destination, fields }).catch(() => setPending(false));
  };

  return (
    <li className="review-item">
      <div className="review-head">
        <span className="review-entry-text">{item.entry_text}</span>
        <span className="review-conf">
          {Math.round(item.confidence * 100)}%
        </span>
      </div>
      {item.reason && <p className="review-reason">{item.reason}</p>}
      {destination === "note" && (
        <p className="review-note-hint">
          Confirming as a note appends it to your notes Doc.
        </p>
      )}
      <div className="review-fields">
        <label>
          Type
          <select
            value={destination}
            onChange={(e) =>
              setDestination(e.target.value as (typeof DESTINATIONS)[number])
            }
          >
            {DESTINATIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        {destination === "task" ? (
          <>
            <input
              className="review-title"
              value={title}
              placeholder="task title"
              onChange={(e) => setTitle(e.target.value)}
            />
            <textarea
              className="review-notes"
              value={notes}
              placeholder="notes (optional)"
              rows={2}
              onChange={(e) => setNotes(e.target.value)}
            />
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
            />
            <label className="review-list-label">
              List
              <select
                className="review-list"
                value={targetList}
                onChange={(e) =>
                  setTargetList(e.target.value as (typeof TARGET_LISTS)[number])
                }
              >
                {TARGET_LISTS.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : (
          <>
            <label className="review-list-label">
              Doc
              <select
                className="review-doc"
                value={docPath}
                onChange={(e) => setDocPath(e.target.value)}
              >
                <option value="">{DEFAULT_DOC_LABEL}</option>
                {docPaths.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <input
              className="review-summary"
              value={summary}
              placeholder="one-liner (optional)"
              onChange={(e) => setSummary(e.target.value)}
            />
            <textarea
              ref={noteTextRef}
              className="review-note-text"
              value={noteText}
              placeholder="note text"
              rows={3}
              onChange={(e) => setNoteText(e.target.value)}
            />
          </>
        )}
      </div>
      <div className="review-actions">
        <button onClick={confirm} disabled={pending}>
          Confirm
        </button>
        <button
          className="review-dismiss"
          onClick={() => {
            setPending(true);
            onDismiss(item.id).catch(() => setPending(false));
          }}
          disabled={pending}
        >
          Dismiss
        </button>
      </div>
    </li>
  );
}
