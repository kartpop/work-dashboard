import { useCallback, useEffect, useState } from "react";
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
  attendees: Attendee[];
}

interface DayResponse {
  date: string;
  events: CalendarEvent[];
}

const REFRESH_MS = 5 * 60 * 1000; // calendar changes are rare — not the 45s task cadence

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
}

export function useCalendarStrip(): CalendarStripState {
  const [viewedDate, setViewedDate] = useState<string>(() =>
    toISODate(new Date()),
  );
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = () => {
      apiGet<DayResponse>(`/calendar/day?date=${viewedDate}`)
        .then((data) => {
          if (!cancelled) {
            setEvents(data.events);
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

    setIsLoading(true);
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [viewedDate]);

  const goToDate = useCallback((iso: string) => setViewedDate(iso), []);
  const shiftDay = useCallback(
    (days: number) => setViewedDate((d) => shiftISODate(d, days)),
    [],
  );
  const goToday = useCallback(() => setViewedDate(toISODate(new Date())), []);

  return {
    viewedDate,
    isToday: viewedDate === toISODate(new Date()),
    events,
    isLoading,
    error,
    goToDate,
    shiftDay,
    goToday,
  };
}
