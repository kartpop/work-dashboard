import { useState } from "react";
import type { ReviewFields, ReviewItem } from "./useScratchPanel";

// The user resolves a review item as a task or a note only (goal 7c). `event`
// stays a valid classifier output — it just lands here for the user to pick one
// of these two (calendar is read-only).
const DESTINATIONS = ["task", "note"] as const;

interface Props {
  items: ReviewItem[];
  onConfirm: (
    id: number,
    override?: { destination?: string; fields?: ReviewFields },
  ) => Promise<boolean>;
  onDismiss: (id: number) => Promise<void>;
}

export function ReviewQueue({ items, onConfirm, onDismiss }: Props) {
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
  onConfirm,
  onDismiss,
}: {
  item: ReviewItem;
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
  const [listHint, setListHint] = useState(item.fields.list_hint ?? "");
  // Note fields: the raw body (fall back to the captured text) + the one-liner.
  const [noteText, setNoteText] = useState(
    item.fields.note_text ?? item.entry_text ?? "",
  );
  const [summary, setSummary] = useState(item.fields.summary ?? "");
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
          }
        : {
            ...item.fields,
            title: title || null,
            notes: notes || null,
            due_date: dueDate || null,
            list_hint: listHint || null,
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
            <input
              className="review-hint"
              value={listHint}
              placeholder="list (optional)"
              onChange={(e) => setListHint(e.target.value)}
            />
          </>
        ) : (
          <>
            <input
              className="review-summary"
              value={summary}
              placeholder="one-liner (optional)"
              onChange={(e) => setSummary(e.target.value)}
            />
            <textarea
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
