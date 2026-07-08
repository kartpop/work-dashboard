import { useState } from "react";
import type { Me } from "./auth/useAuth";
import { CalendarStrip } from "./panels/calendar/CalendarStrip";
import { CapturePanel } from "./panels/scratch/CapturePanel";
import { PinnedTasksRow, TasksToasts } from "./panels/tasks/TasksPanel";
import { useTasksPanel } from "./panels/tasks/useTasksPanel";
import { SettingsPage } from "./settings/SettingsPage";

export function DashboardPage({
  user,
  onSignOut,
}: {
  user: Me;
  onSignOut: () => void;
}) {
  // Lifted here (not owned inside a single TasksPanel) so the scratchpad can
  // refresh the task columns after routing/confirming creates a Google task, and
  // so the pinned pair + toasts read one shared state.
  const tasks = useTasksPanel();
  const [showSettings, setShowSettings] = useState(false);

  return (
    <main className="dashboard">
      {/* Header row: title + today's calendar strip (goal 7b); account controls right. */}
      <header className="dashboard-header">
        <h1>Dashboard</h1>
        <CalendarStrip />
        <div className="account-controls">
          <button
            className="account-btn"
            onClick={() => setShowSettings(true)}
            title="Settings"
            aria-label="Settings"
          >
            ⚙
          </button>
          {user.picture ? (
            <img
              className="account-avatar"
              src={user.picture}
              alt={user.email}
            />
          ) : (
            <span className="account-avatar account-avatar--fallback">
              {(user.name ?? user.email).charAt(0).toUpperCase()}
            </span>
          )}
          <button className="account-signout" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </header>
      {/* Full-width, resizable top row: My Tasks | Follow-ups | Scratchpad (goal
          6). The pinned pair shares one DndContext (cross-list drag); the
          scratchpad is passed in as the third column so no panel imports another. */}
      <PinnedTasksRow
        tasks={tasks}
        scratchpad={<CapturePanel onRouted={tasks.refresh} />}
      />
      <TasksToasts tasks={tasks} />
      {showSettings && (
        <SettingsPage user={user} onClose={() => setShowSettings(false)} />
      )}
    </main>
  );
}
