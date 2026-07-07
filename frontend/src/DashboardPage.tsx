import { CalendarPanel } from "./panels/calendar/CalendarPanel";
import { CapturePanel } from "./panels/scratch/CapturePanel";
import {
  OtherTasksSection,
  PinnedTasksRow,
  TasksToasts,
} from "./panels/tasks/TasksPanel";
import { useTasksPanel } from "./panels/tasks/useTasksPanel";

export function DashboardPage() {
  // Lifted here (not owned inside a single TasksPanel) so the scratchpad can
  // refresh the task columns after routing/confirming creates a Google task, and
  // so the pinned pair + "Other tasks" + toasts all read one shared state.
  const tasks = useTasksPanel();

  return (
    <main className="dashboard">
      <h1>Dashboard</h1>
      {/* Full-width, resizable top row: My Tasks | Follow-ups | Scratchpad (goal
          6). The pinned pair shares one DndContext (cross-list drag); the
          scratchpad is passed in as the third column so no panel imports another. */}
      <PinnedTasksRow
        tasks={tasks}
        scratchpad={<CapturePanel onRouted={tasks.refresh} />}
      />
      <OtherTasksSection tasks={tasks} />
      <CalendarPanel />
      <TasksToasts tasks={tasks} />
    </main>
  );
}
