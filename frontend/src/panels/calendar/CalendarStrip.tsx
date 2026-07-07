import { useEffect, useMemo, useState } from "react";
import { layoutBlocks, type StripEvent } from "./layoutStrip";
import {
  shiftISODate,
  useCalendarStrip,
  type CalendarEvent,
} from "./useCalendarStrip";

const DEFAULT_START = 9 * 60; // 09:00
const DEFAULT_END = 18 * 60; // 18:00
const STEP = 60; // chevrons shift the window by 1h

/** Minutes-from-midnight for a timed ISO string (local == IST on the owner's box). */
function istMinutes(iso: string): number {
  const d = new Date(iso);
  return d.getHours() * 60 + d.getMinutes();
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

function fmtPill(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString([], {
    weekday: "short",
    day: "numeric",
  });
}

function fmtViewed(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString([], {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

function fmtNow(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function CalendarStrip() {
  const cal = useCalendarStrip();
  const [windowStart, setWindowStart] = useState(DEFAULT_START);
  const [windowEnd, setWindowEnd] = useState(DEFAULT_END);
  const [toast, setToast] = useState<string | null>(null);
  const [nowMin, setNowMin] = useState(() =>
    istMinutes(new Date().toISOString()),
  );

  // The now-marker recomputes every minute without a reload.
  useEffect(() => {
    const tick = () => setNowMin(istMinutes(new Date().toISOString()));
    tick();
    const timer = window.setInterval(tick, 60 * 1000);
    return () => window.clearInterval(timer);
  }, []);

  // Auto-dismiss the copy toast.
  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 2000);
    return () => window.clearTimeout(t);
  }, [toast]);

  const byId = useMemo(() => {
    const m = new Map<string, CalendarEvent>();
    for (const e of cal.events) m.set(e.id, e);
    return m;
  }, [cal.events]);

  const layout = useMemo(() => {
    const stripEvents: StripEvent[] = cal.events.map((e) => ({
      id: e.id,
      title: e.title,
      startMin: e.all_day ? 0 : istMinutes(e.start),
      endMin: e.all_day ? 0 : istMinutes(e.end),
      allDay: e.all_day,
    }));
    return layoutBlocks(stripEvents, windowStart, windowEnd);
  }, [cal.events, windowStart, windowEnd]);

  const span = windowEnd - windowStart;
  const nowPct = ((nowMin - windowStart) / span) * 100;
  const showNow = cal.isToday && nowMin >= windowStart && nowMin <= windowEnd;

  // Hour ticks across the window (whole hours only).
  const hourTicks: number[] = [];
  for (
    let h = Math.ceil(windowStart / 60);
    h <= Math.floor(windowEnd / 60);
    h++
  ) {
    hourTicks.push(h);
  }

  const shiftWindow = (delta: number) => {
    setWindowStart((s) => Math.max(0, Math.min(24 * 60 - STEP, s + delta)));
    setWindowEnd((e) => Math.min(24 * 60, Math.max(STEP, e + delta)));
  };

  const onBlockClick = (event: CalendarEvent, e: React.MouseEvent) => {
    // Alt+click = secondary open-in-new-tab path; plain click copies the link.
    if (e.altKey) {
      if (event.meet_link) window.open(event.meet_link, "_blank", "noopener");
      return;
    }
    if (!event.meet_link) {
      setToast("No Meet link for this event");
      return;
    }
    void navigator.clipboard
      .writeText(event.meet_link)
      .then(() => setToast("Meet link copied"))
      .catch(() => setToast("Couldn’t copy — try the tooltip’s open link"));
  };

  return (
    <div className="calendar-strip">
      <div className="strip-body">
        <button
          className="strip-chevron"
          onClick={() => shiftWindow(-STEP)}
          disabled={windowStart <= 0}
          title="Earlier"
          aria-label="Show earlier hours"
        >
          ‹{layout.beforeCount > 0 ? <span className="strip-hint-dot" /> : null}
        </button>

        <div className="strip-axis">
          {/* Meeting blocks above the axis line, in ≤2 lanes. */}
          <div className="strip-blocks">
            {layout.blocks.map((b) => {
              const event = byId.get(b.id);
              if (!event) return null;
              return (
                <div
                  key={b.id}
                  className="strip-block"
                  style={{
                    left: `${b.leftPct}%`,
                    width: `${b.widthPct}%`,
                    top: b.lane === 0 ? "2px" : "22px",
                  }}
                  role="button"
                  tabIndex={0}
                  onClick={(e) => onBlockClick(event, e)}
                >
                  <span className="strip-block-title">
                    {event.title ?? "(untitled)"}
                  </span>
                  <div className="strip-tooltip" role="tooltip">
                    <div className="tt-title">
                      {event.title ?? "(untitled)"}
                    </div>
                    <div className="tt-time">
                      {fmtTime(event.start)} – {fmtTime(event.end)}
                    </div>
                    {event.location && (
                      <div className="tt-loc">{event.location}</div>
                    )}
                    {event.attendees.length > 0 && (
                      <div className="tt-att">
                        {event.attendees
                          .map((a) => a.name ?? a.email)
                          .filter(Boolean)
                          .join(", ")}
                      </div>
                    )}
                    {event.meet_link && (
                      <a
                        className="tt-open"
                        href={event.meet_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                      >
                        Open in new tab ↗
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Axis line with hour ticks + labels. */}
          <div className="strip-line" />
          {hourTicks.map((h) => {
            const pct = ((h * 60 - windowStart) / span) * 100;
            return (
              <div key={h} className="strip-tick" style={{ left: `${pct}%` }}>
                <span className="strip-tick-label">{h % 12 || 12}</span>
              </div>
            );
          })}

          {showNow && (
            <div className="strip-now" style={{ left: `${nowPct}%` }}>
              <span className="strip-now-label">{fmtNow(nowMin)}</span>
            </div>
          )}

          {cal.error && (
            <span className="strip-status strip-error">{cal.error}</span>
          )}
        </div>

        <button
          className="strip-chevron"
          onClick={() => shiftWindow(STEP)}
          disabled={windowEnd >= 24 * 60}
          title="Later"
          aria-label="Show later hours"
        >
          {layout.afterCount > 0 ? <span className="strip-hint-dot" /> : null}›
        </button>
      </div>

      {/* Day-navigation row: prev pill · viewed date (+Today) · next pill. */}
      <div className="strip-daynav">
        <button className="strip-daypill" onClick={() => cal.shiftDay(-1)}>
          « {fmtPill(shiftISODate(cal.viewedDate, -1))}
        </button>
        <span className="strip-viewed">
          {fmtViewed(cal.viewedDate)}
          {!cal.isToday && (
            <button className="strip-today" onClick={cal.goToday}>
              Today
            </button>
          )}
        </span>
        <button className="strip-daypill" onClick={() => cal.shiftDay(1)}>
          {fmtPill(shiftISODate(cal.viewedDate, 1))} »
        </button>
      </div>

      {toast && <div className="strip-toast">{toast}</div>}
    </div>
  );
}
