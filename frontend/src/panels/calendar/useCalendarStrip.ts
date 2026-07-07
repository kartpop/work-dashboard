import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "../../api";

export interface Attendee {
  name: string | null;
  email: string | null;
  response_status: string | null;
}

export interface CalendarEvent {
  id: string;
  title: string | null;
  start: string;
  end: string;
  all_day: boolean;
  meet_link: string | null;
  location: string | null;
  organizer: string | null;
  /** Owner's RSVP (`accepted`/`declined`/`tentative`/`needsAction`); null when
   * the event has no attendee entry for the owner (solo/own events). */
  my_response: string | null;
  attendees: Attendee[];
}

interface DayResponse {
  date: string;
  events: CalendarEvent[];
}

const REFRESH_MS = 3 * 60 * 1000; // keep the read-only strip in sync with the work calendar
const PREFETCH_DAYS = 6; // warm today+6 so near-term day navigation is instant

/** Local `YYYY-MM-DD` (the owner's machine is IST, so local date == IST date). */
export function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function shiftISODate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return toISODate(d);
}

export interface CalendarStripState {
  viewedDate: string;
  isToday: boolean;
  events: CalendarEvent[];
  isLoading: boolean;
  error: string | null;
  goToDate: (iso: string) => void;
  shiftDay: (days: number) => void;
  goToday: () => void;
  refresh: () => void;
}

export function useCalendarStrip(): CalendarStripState {
  const [viewedDate, setViewedDate] = useState<string>(() =>
    toISODate(new Date()),
  );
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  // Per-day cache (stale-while-revalidate): a cached day renders instantly on
  // navigation while the network refetch updates it in the background.
  const cacheRef = useRef<Map<string, CalendarEvent[]>>(new Map());

  const fetchDay = useCallback(
    async (iso: string): Promise<CalendarEvent[]> => {
      const data = await apiGet<DayResponse>(`/calendar/day?date=${iso}`);
      cacheRef.current.set(iso, data.events);
      return data.events;
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;

    const load = () => {
      const cached = cacheRef.current.get(viewedDate);
      if (cached) {
        // Show the cached day immediately; the fetch below revalidates it.
        setEvents(cached);
        setIsLoading(false);
        setError(null);
      } else {
        setIsLoading(true);
      }
      fetchDay(viewedDate)
        .then((fresh) => {
          if (!cancelled) {
            setEvents(fresh);
            setIsLoading(false);
            setError(null);
          }
        })
        .catch((err: Error) => {
          if (!cancelled) {
            setError(err.message);
            setIsLoading(false);
          }
        });
    };

    // Warm today+N in the background (best-effort). `force` refetches days that
    // are already cached — used by the interval so the warm week stays fresh.
    const prefetchWeek = (force: boolean) => {
      const today = toISODate(new Date());
      for (let i = 0; i <= PREFETCH_DAYS; i++) {
        const iso = shiftISODate(today, i);
        if (iso === viewedDate) continue; // load() owns the viewed day
        if (!force && cacheRef.current.has(iso)) continue;
        fetchDay(iso).catch(() => {});
      }
    };

    load();
    prefetchWeek(false);
    const timer = window.setInterval(() => {
      load();
      prefetchWeek(true);
    }, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [viewedDate, refreshTick, fetchDay]);

  const goToDate = useCallback((iso: string) => setViewedDate(iso), []);
  const shiftDay = useCallback(
    (days: number) => setViewedDate((d) => shiftISODate(d, days)),
    [],
  );
  const goToday = useCallback(() => setViewedDate(toISODate(new Date())), []);
  // Manual refresh: bumping the tick re-runs the fetch effect (and resets the
  // 3-min interval so the next auto-refresh counts from now).
  const refresh = useCallback(() => setRefreshTick((t) => t + 1), []);

  return {
    viewedDate,
    isToday: viewedDate === toISODate(new Date()),
    events,
    isLoading,
    error,
    goToDate,
    shiftDay,
    goToday,
    refresh,
  };
}
