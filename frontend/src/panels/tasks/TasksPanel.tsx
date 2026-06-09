import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { type Task, type TaskList, useTasksPanel } from "./useTasksPanel";

const PRIORITY_LABELS = ["", "Low", "Med", "High"];
const PRIORITY_NEXT: Record<number, number> = { 0: 1, 1: 2, 2: 3, 3: 0 };

function effectiveRank(task: Task, index: number): number {
  return task.rank ?? (index + 1) * 1000;
}

function computeMidpointRank(tasks: Task[], toIndex: number): number {
  // tasks[toIndex] is the moved item; use its actual neighbors
  const prev = toIndex > 0 ? tasks[toIndex - 1] : null;
  const next = toIndex < tasks.length - 1 ? tasks[toIndex + 1] : null;
  const prevRank = prev
    ? effectiveRank(prev, toIndex - 1)
    : (next ? effectiveRank(next, toIndex + 1) - 2000 : 1000);
  const nextRank = next ? effectiveRank(next, toIndex + 1) : prevRank + 2000;
  return (prevRank + nextRank) / 2;
}

interface SortableTaskProps {
  task: Task;
  tasklistId: string;
  onPriorityClick: (tasklistId: string, taskId: string, next: number) => void;
}

function SortableTask({ task, tasklistId, onPriorityClick }: SortableTaskProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: task.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  };

  const priority = task.priority ?? 0;
  const nextPriority = PRIORITY_NEXT[priority];

  return (
    <li ref={setNodeRef} style={style} className="task-item">
      <span className="drag-handle" {...attributes} {...listeners} aria-label="drag to reorder">
        ⠿
      </span>
      <button
        className={`priority-badge priority-${priority}`}
        onClick={() => onPriorityClick(tasklistId, task.id, nextPriority)}
        title={priority === 0 ? "Set priority" : `Priority: ${PRIORITY_LABELS[priority]} — click to change`}
      >
        {PRIORITY_LABELS[priority] || "·"}
      </button>
      <span className="task-title">{task.title}</span>
    </li>
  );
}

interface TaskListSectionProps {
  list: TaskList;
  onPriorityClick: (tasklistId: string, taskId: string, next: number) => void;
  onReorder: (
    tasklistId: string,
    taskId: string,
    groupLabel: string,
    fromIndex: number,
    toIndex: number,
    newRank: number,
  ) => void;
}

function TaskListSection({ list, onPriorityClick, onReorder }: TaskListSectionProps) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  return (
    <div className="task-list-section">
      <h3>{list.title}</h3>
      {list.groups.map((group) => {
        const taskIds = group.tasks.map((t) => t.id);

        function handleDragEnd(event: DragEndEvent) {
          const { active, over } = event;
          if (!over || active.id === over.id) return;
          const fromIndex = group.tasks.findIndex((t) => t.id === active.id);
          const toIndex = group.tasks.findIndex((t) => t.id === over.id);
          if (fromIndex === -1 || toIndex === -1) return;

          // compute rank against neighbors in the reordered list
          const reordered = [...group.tasks];
          const [moved] = reordered.splice(fromIndex, 1);
          reordered.splice(toIndex, 0, moved);
          const newRank = computeMidpointRank(reordered, toIndex);
          onReorder(list.id, String(active.id), group.label, fromIndex, toIndex, newRank);
        }

        return (
          <div key={group.label} className="date-group">
            <span className="date-group-label">{group.label}</span>
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
              <SortableContext items={taskIds} strategy={verticalListSortingStrategy}>
                <ul>
                  {group.tasks.map((task) => (
                    <SortableTask
                      key={task.id}
                      task={task}
                      tasklistId={list.id}
                      onPriorityClick={onPriorityClick}
                    />
                  ))}
                </ul>
              </SortableContext>
            </DndContext>
          </div>
        );
      })}
    </div>
  );
}

export function TasksPanel() {
  const { taskLists, isLoading, error, setPriority, reorderTask } = useTasksPanel();

  return (
    <section className="panel">
      <h2>Tasks</h2>
      {isLoading && <p className="panel-status">Loading…</p>}
      {error && <p className="panel-status panel-error">{error}</p>}
      {!isLoading &&
        !error &&
        taskLists.map((list) => (
          <TaskListSection
            key={list.id}
            list={list}
            onPriorityClick={setPriority}
            onReorder={reorderTask}
          />
        ))}
    </section>
  );
}
