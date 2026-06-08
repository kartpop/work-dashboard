import { formatDate } from "../../formatDate";
import { useTasksPanel } from "./useTasksPanel";

export function TasksPanel() {
  const { taskLists, isLoading, error } = useTasksPanel();

  return (
    <section className="panel">
      <h2>Tasks</h2>
      {isLoading && <p className="panel-status">Loading…</p>}
      {error && <p className="panel-status panel-error">{error}</p>}
      {!isLoading &&
        !error &&
        taskLists.map((list) => (
          <div className="task-list" key={list.id}>
            <h3>{list.title}</h3>
            <ul>
              {list.tasks.map((task) => (
                <li key={task.id} className={task.status === "completed" ? "is-done" : undefined}>
                  <span className="task-title">{task.title}</span>
                  {/* Tasks `due` is always midnight UTC representing a date, not a time. */}
                  {task.due && <span className="task-due">{formatDate(task.due.slice(0, 10))}</span>}
                </li>
              ))}
            </ul>
          </div>
        ))}
    </section>
  );
}
