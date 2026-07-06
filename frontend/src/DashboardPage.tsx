import { CalendarPanel } from "./panels/calendar/CalendarPanel";
import { CapturePanel } from "./panels/scratch/CapturePanel";
import { TasksPanel } from "./panels/tasks/TasksPanel";
import { useTasksPanel } from "./panels/tasks/useTasksPanel";

export function DashboardPage() {
  // Lifted here (not owned inside TasksPanel) so the scratchpad can refresh the
  // task list after routing/confirming creates a Google task — the two panels
  // otherwise share no state (see frontend.md: lift state to the page).
  const tasks = useTasksPanel();

  return (
    <main className="dashboard">
      <h1>Work Dashboard</h1>
      <div className="panel-grid">
        <CapturePanel onRouted={tasks.refresh} />
        <TasksPanel tasks={tasks} />
        <CalendarPanel />
      </div>
    </main>
  );
}
