import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../../api";

export interface ScratchEntry {
  id: number;
  text: string;
  routing_state: string;
  created_at: string;
  routed_at: string | null;
}

export interface ReviewFields {
  title?: string | null;
  list_hint?: string | null;
  due_date?: string | null;
  notes?: string | null;
  note_text?: string | null;
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

// The backend router scheduler routes unrouted captures on its own (~5 min).
// Poll so those state changes surface without a manual page refresh.
const POLL_MS = 45_000;

export function useScratchPanel() {
  const [entries, setEntries] = useState<ScratchEntry[]>([]);
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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

  // Append a capture. Optimistic prepend, then reconcile from the server response.
  const capture = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const created = await apiPost<ScratchEntry>("/scratch", { text: trimmed });
    setEntries((prev) => [created, ...prev]);
  }, []);

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
