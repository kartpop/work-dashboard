import { formatDate } from "../../formatDate";
import { useCalendarPanel } from "./useCalendarPanel";

export function CalendarPanel() {
  const { events, isLoading, error } = useCalendarPanel(10);

  return (
    <section className="panel">
      <h2>Calendar</h2>
      {isLoading && <p className="panel-status">Loading…</p>}
      {error && <p className="panel-status panel-error">{error}</p>}
      {!isLoading && !error && (
        <ul className="event-list">
          {events.map((event) => (
            <li key={event.id}>
              <span className="event-title">{event.title ?? "(untitled)"}</span>
              <span className="event-start">{formatDate(event.start)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
