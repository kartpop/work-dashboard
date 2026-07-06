import { useState } from "react";
import type { ReviewFields, ReviewItem } from "./useScratchPanel";

const DESTINATIONS = ["task", "note", "event", "unknown"];

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
      <h3>Review queue</h3>
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
  const [destination, setDestination] = useState(item.destination);
  const [title, setTitle] = useState(item.fields.title ?? "");
  const [dueDate, setDueDate] = useState(item.fields.due_date ?? "");
  const [listHint, setListHint] = useState(item.fields.list_hint ?? "");
  const [pending, setPending] = useState(false);

  const confirm = () => {
    setPending(true);
    // Send the (possibly edited) destination + fields. The backend fires a
    // create_task only for a `task`; other destinations are acknowledged, no write.
    onConfirm(item.id, {
      destination,
      fields: {
        ...item.fields,
        title: title || null,
        due_date: dueDate || null,
        list_hint: listHint || null,
      },
    }).catch(() => setPending(false));
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
      <div className="review-fields">
        <label>
          Type
          <select
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
          >
            {DESTINATIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        {destination === "task" && (
          <>
            <input
              className="review-title"
              value={title}
              placeholder="task title"
              onChange={(e) => setTitle(e.target.value)}
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
