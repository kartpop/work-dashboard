import { CalendarPanel } from "./panels/calendar/CalendarPanel";
import { CapturePanel } from "./panels/scratch/CapturePanel";
import { TasksPanel } from "./panels/tasks/TasksPanel";

export function DashboardPage() {
  return (
    <main className="dashboard">
      <h1>Work Dashboard</h1>
      <div className="panel-grid">
        <CapturePanel />
        <TasksPanel />
        <CalendarPanel />
      </div>
    </main>
  );
}
