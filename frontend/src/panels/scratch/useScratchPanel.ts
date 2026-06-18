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

  // Append a capture. Optimistic prepend, then reconcile from the server response.
  const capture = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const created = await apiPost<ScratchEntry>("/scratch", { text: trimmed });
    setEntries((prev) => [created, ...prev]);
  }, []);

  // Manual "route now" — same code path as the scheduled job. Reload after.
  const routeNow = useCallback(async () => {
    setBusy(true);
    try {
      await apiPost("/scratch/route-now", {});
      await load();
    } catch (err) {
      setError(`Route failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }, [load]);

  const confirmItem = useCallback(
    async (
      itemId: number,
      override?: { destination?: string; fields?: ReviewFields },
    ) => {
      await apiPost(`/review/${itemId}/confirm`, override ?? {});
      await load();
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
