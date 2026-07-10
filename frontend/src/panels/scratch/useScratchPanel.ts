import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../../api";

export interface ScratchEntry {
  id: number;
  text: string;
  routing_state: string;
  created_at: string;
  routed_at: string | null;
  // Where a kept note landed (goal 9): the hierarchy path (null = default Doc) for
  // the chip's hover, and a direct link to the destination Doc.
  routed_doc_path: string | null;
  routed_doc_url: string | null;
}

export interface ReviewFields {
  title?: string | null;
  target_list?: string | null;
  due_date?: string | null;
  notes?: string | null;
  note_text?: string | null;
  summary?: string | null;
  target_doc_path?: string | null;
  keywords?: string[] | null;
  event_datetime?: string | null;
  attendees?: string | null;
}

export interface ReviewItem {
  id: number;
  entry_id: number;
  entry_text: string | null;
  destination: string;
  fields: ReviewFields; // parsed from the server's JSON string
  confidence: number;
  reason: string | null;
  status: string;
}

interface EntriesResponse {
  entries: ScratchEntry[];
}
interface ReviewResponse {
  items: Array<Omit<ReviewItem, "fields"> & { fields: string }>;
}

// The notes hierarchy (goal 9) — only the leaf Doc paths are needed here, to fill
// the review queue's destination-Doc dropdown.
interface NotesIndexNode {
  name: string;
  kind: "folder" | "doc";
  children: NotesIndexNode[];
}
function leafPaths(nodes: NotesIndexNode[], prefix: string[] = []): string[] {
  const out: string[] = [];
  for (const n of nodes) {
    const path = [...prefix, n.name];
    if (n.kind === "doc") out.push(path.join("/"));
    out.push(...leafPaths(n.children, path));
  }
  return out;
}

// The backend router scheduler routes unrouted captures on its own (~5 min).
// Poll so those state changes surface without a manual page refresh.
const POLL_MS = 45_000;

export function useScratchPanel() {
  const [entries, setEntries] = useState<ScratchEntry[]>([]);
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [docPaths, setDocPaths] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // The notes-hierarchy leaf paths for the review dropdown — fetched once (the tree
  // changes only from the settings page, not from routing), never on the poll.
  useEffect(() => {
    apiGet<{ nodes: NotesIndexNode[] }>("/settings/notes-index")
      .then((r) => setDocPaths(leafPaths(r.nodes)))
      .catch(() => setDocPaths([]));
  }, []);

  const load = useCallback(async () => {
    try {
      const [e, r] = await Promise.all([
        apiGet<EntriesResponse>("/scratch"),
        apiGet<ReviewResponse>("/review"),
      ]);
      setEntries(e.entries);
      setReviewItems(
        r.items.map((it) => ({
          ...it,
          fields: safeParse(it.fields),
        })),
      );
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    load().then(() => {
      if (cancelled) return;
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  // Poll so the backend scheduler's routing is reflected without a manual refresh.
  useEffect(() => {
    const id = window.setInterval(() => {
      load().catch(() => {});
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [load]);

  // Append a capture. The POST now routes inline (goal 7c), so the response
  // carries the routed state — prepend it as-is (RECENT shows it filed). Returns
  // the created entry so the caller can refresh the Tasks panel on a routed task.
  const capture = useCallback(
    async (text: string): Promise<ScratchEntry | null> => {
      const trimmed = text.trim();
      if (!trimmed) return null;
      const created = await apiPost<ScratchEntry>("/scratch", {
        text: trimmed,
      });
      setEntries((prev) => [created, ...prev]);
      // When the router sends the capture to review, RECENT shows it "In review"
      // immediately (from `created`) but the Review queue only knows on the next
      // poll — refetch so both surfaces update together (no 45s lag).
      if (created.routing_state === "in_review") await load();
      return created;
    },
    [load],
  );

  // Manual "route now" — same code path as the scheduled job. Reload after.
  // Returns whether any entry was routed to a Google task, so the caller can
  // refresh the (separately-owned) Tasks panel only when there's something new.
  const routeNow = useCallback(async (): Promise<boolean> => {
    setBusy(true);
    try {
      const { tally } = await apiPost<{ tally: Record<string, number> }>(
        "/scratch/route-now",
        {},
      );
      await load();
      return (tally.routed_task ?? 0) > 0;
    } catch (err) {
      setError(`Route failed: ${(err as Error).message}`);
      return false;
    } finally {
      setBusy(false);
    }
  }, [load]);

  // Confirm a review item; returns true when the confirmation created a Google
  // task (entry_state "routed_task"), so the caller can refresh the Tasks panel.
  const confirmItem = useCallback(
    async (
      itemId: number,
      override?: { destination?: string; fields?: ReviewFields },
    ): Promise<boolean> => {
      const { entry_state } = await apiPost<{ entry_state: string }>(
        `/review/${itemId}/confirm`,
        override ?? {},
      );
      await load();
      return entry_state === "routed_task";
    },
    [load],
  );

  const dismissItem = useCallback(
    async (itemId: number) => {
      await apiPost(`/review/${itemId}/dismiss`, {});
      await load();
    },
    [load],
  );

  return {
    entries,
    reviewItems,
    docPaths,
    isLoading,
    error,
    busy,
    capture,
    routeNow,
    confirmItem,
    dismissItem,
    refresh: load,
  };
}

function safeParse(s: string): ReviewFields {
  try {
    return JSON.parse(s) as ReviewFields;
  } catch {
    return {};
  }
}
