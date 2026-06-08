import { useEffect, useState } from "react";
import { apiGet } from "../../api";

export interface CalendarEvent {
  id: string;
  title: string | null;
  start: string;
}

interface CalendarResponse {
  events: CalendarEvent[];
}

interface CalendarPanelState {
  events: CalendarEvent[];
  isLoading: boolean;
  error: string | null;
}

export function useCalendarPanel(limit = 10): CalendarPanelState {
  const [state, setState] = useState<CalendarPanelState>({
    events: [],
    isLoading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

    apiGet<CalendarResponse>(`/calendar/upcoming?limit=${limit}`)
      .then((data) => {
        if (!cancelled) setState({ events: data.events, isLoading: false, error: null });
      })
      .catch((err: Error) => {
        if (!cancelled) setState({ events: [], isLoading: false, error: err.message });
      });

    return () => {
      cancelled = true;
    };
  }, [limit]);

  return state;
}
