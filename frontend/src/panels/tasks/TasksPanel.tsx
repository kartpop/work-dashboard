import {
  DndContext,
  type DragEndEvent,
  type CollisionDetection,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  pointerWithin,
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
import { useRef, useState } from "react";

import {
  type Bucket,
  type BucketItem,
  type Group,
  type Task,
  type TaskList,
  useTasksPanel,
} from "./useTasksPanel";

// ── Rank helpers ──────────────────────────────────────────────────────────────

function effectiveRank(item: BucketItem, index: number): number {
  return item.rank ?? (index + 1) * 1000;
}

function computeMidpointRank(items: BucketItem[], toIndex: number): number {
  const prev = toIndex > 0 ? items[toIndex - 1] : null;
  const next = toIndex < items.length - 1 ? items[toIndex + 1] : null;
  const prevRank = prev
    ? effectiveRank(prev, toIndex - 1)
    : next
      ? effectiveRank(next, toIndex + 1) - 2000
      : 1000;
  const nextRank = next ? effectiveRank(next, toIndex + 1) : prevRank + 2000;
  return (prevRank + nextRank) / 2;
}

function computeGroupTaskRank(tasks: Task[], toIndex: number): number {
  const prevRank =
    toIndex > 0
      ? (tasks[toIndex - 1].rank ?? toIndex * 1000)
      : toIndex < tasks.length - 1
        ? (tasks[toIndex + 1].rank ?? (toIndex + 1) * 1000) - 2000
        : 1000;
  const nextRank =
    toIndex < tasks.length - 1
      ? (tasks[toIndex + 1].rank ?? (toIndex + 1) * 1000)
      : prevRank + 2000;
  return (prevRank + nextRank) / 2;
}

// ── Data model helpers ────────────────────────────────────────────────────────

/** Flat list of IDs for the SortableContext (group header + its task IDs in order). */
function flatItemIds(items: BucketItem[]): string[] {
  const ids: string[] = [];
  for (const item of items) {
    if (item.type === "task") {
      ids.push(item.id);
    } else {
      ids.push(`group-${item.id}`);
      for (const t of item.items) ids.push(t.id);
    }
  }
  return ids;
}

type ContainerRef = { type: "bucket" } | { type: "group"; groupId: number };

function findContainer(id: string, items: BucketItem[]): ContainerRef | null {
  for (const item of items) {
    if (item.type === "task" && item.id === id) return { type: "bucket" };
    if (item.type === "group") {
      for (const t of item.items) {
        if (t.id === id) return { type: "group", groupId: item.id };
      }
    }
  }
  return null;
}

function findBucketItemIndex(id: string, items: BucketItem[]): number {
  return items.findIndex(
    (it) =>
      (it.type === "task" && it.id === id) ||
      (it.type === "group" && `group-${it.id}` === id),
  );
}

// ── Draggable task ────────────────────────────────────────────────────────────

interface SortableTaskProps {
  task: Task;
  compact?: boolean;
}

function SortableTask({ task, compact }: SortableTaskProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: task.id,
    data: { type: "task" },
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  };

  return (
    <li
      ref={setNodeRef}
      style={style}
      className={`task-item${compact ? " task-item--compact" : ""}`}
    >
      <span
        className="drag-handle"
        {...attributes}
        {...listeners}
        aria-label="drag to reorder"
      >
        ⠿
      </span>
      <span className="task-title">{task.title}</span>
    </li>
  );
}

// ── Group container ───────────────────────────────────────────────────────────

interface GroupContainerProps {
  group: Group;
  onRename: (groupId: number, name: string) => void;
  onDelete: (groupId: number) => void;
}

function GroupContainer({ group, onRename, onDelete }: GroupContainerProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: `group-${group.id}`,
    data: { type: "group" },
  });

  const [editing, setEditing] = useState(false);
  const [nameInput, setNameInput] = useState(group.name);

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  };

  function commitRename() {
    setEditing(false);
    const trimmed = nameInput.trim();
    if (trimmed && trimmed !== group.name) {
      onRename(group.id, trimmed);
    } else {
      setNameInput(group.name);
    }
  }

  return (
    <div ref={setNodeRef} style={style} className="group-container">
      <div className="group-header">
        <span
          className="drag-handle group-drag-handle"
          {...attributes}
          {...listeners}
          aria-label="drag group to reorder"
        >
          ⠿
        </span>
        {editing ? (
          <input
            className="group-name-input"
            value={nameInput}
            autoFocus
            onChange={(e) => setNameInput(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") {
                setEditing(false);
                setNameInput(group.name);
              }
            }}
          />
        ) : (
          <button
            className="group-name"
            onClick={() => setEditing(true)}
            title="Click to rename"
          >
            {group.name}
          </button>
        )}
        <button
          className="group-delete"
          onClick={() => onDelete(group.id)}
          title="Delete group (tasks become standalone)"
          aria-label="delete group"
        >
          ×
        </button>
      </div>
      <ul className="group-tasks">
        {group.items.map((task) => (
          <SortableTask key={task.id} task={task} compact />
        ))}
      </ul>
    </div>
  );
}

// ── Collision detection ───────────────────────────────────────────────────────
// pointerWithin first: when the pointer is physically inside a sortable element's
// rect we use that hit (critical for drag-into-group). Fall back to closestCenter
// for inter-item gaps where nothing contains the pointer.
const collisionDetection: CollisionDetection = (args) => {
  const hits = pointerWithin(args);
  return hits.length > 0 ? hits : closestCenter(args);
};

// ── Bucket section ────────────────────────────────────────────────────────────

interface BucketSectionProps {
  bucket: Bucket;
  list: TaskList;
  onReorderTask: (
    tasklistId: string,
    taskId: string,
    bucketKey: string,
    groupId: number | null,
    fromIndex: number,
    toIndex: number,
    newRank: number,
  ) => void;
  onMoveTask: (
    tasklistId: string,
    taskId: string,
    bucketKey: string,
    destGroupId: number | null,
    destIndex: number,
    newRank: number,
  ) => void;
  onReorderGroup: (
    tasklistId: string,
    groupId: number,
    bucketKey: string,
    fromIndex: number,
    toIndex: number,
    newRank: number,
  ) => void;
  onRenameGroup: (
    tasklistId: string,
    groupId: number,
    bucketKey: string,
    name: string,
  ) => void;
  onDeleteGroup: (
    tasklistId: string,
    groupId: number,
    bucketKey: string,
  ) => void;
  onCreateGroup: (tasklistId: string, bucketKey: string, name: string) => void;
}

function BucketSection({
  bucket,
  list,
  onReorderTask,
  onMoveTask,
  onReorderGroup,
  onRenameGroup,
  onDeleteGroup,
  onCreateGroup,
}: BucketSectionProps) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const [addingGroup, setAddingGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");

  // Keep a ref to latest items for use inside handleDragEnd
  const itemsRef = useRef(bucket.items);
  itemsRef.current = bucket.items;

  const ids = flatItemIds(bucket.items);

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const items = itemsRef.current;
    const activeId = String(active.id);
    const overId = String(over.id);

    // ── Group reorder ────────────────────────────────────────────────────────
    if (activeId.startsWith("group-")) {
      const groupId = parseInt(activeId.slice(6), 10);
      const fromIndex = findBucketItemIndex(activeId, items);
      if (fromIndex === -1) return;

      // overId may be a task inside a group (flat SortableContext) — resolve to its group
      let resolvedOverId = overId;
      if (!overId.startsWith("group-")) {
        const overContainer = findContainer(overId, items);
        if (overContainer?.type === "group")
          resolvedOverId = `group-${overContainer.groupId}`;
      }
      const toIndex = findBucketItemIndex(resolvedOverId, items);
      if (toIndex === -1 || fromIndex === toIndex) return;

      const reordered = [...items];
      const [moved] = reordered.splice(fromIndex, 1);
      reordered.splice(toIndex, 0, moved);
      const newRank = computeMidpointRank(reordered, toIndex);
      onReorderGroup(list.id, groupId, bucket.key, fromIndex, toIndex, newRank);
      return;
    }

    // ── Task drag ────────────────────────────────────────────────────────────
    const srcContainer = findContainer(activeId, items);
    if (!srcContainer) return;

    // Determine destination container
    let destContainer: ContainerRef;
    let destIndexInContainer: number;

    if (overId.startsWith("group-")) {
      // Dropped on a group header → append to that group
      const groupId = parseInt(overId.slice(6), 10);
      const grp = items.find(
        (it): it is Group => it.type === "group" && it.id === groupId,
      );
      if (!grp) return;
      destContainer = { type: "group", groupId };
      destIndexInContainer = grp.items.length;
    } else {
      const overContainer = findContainer(overId, items);
      if (!overContainer) return;
      destContainer = overContainer;

      if (overContainer.type === "bucket") {
        // dropping on a standalone task at bucket level
        destIndexInContainer = items.findIndex(
          (it) => it.type === "task" && it.id === overId,
        );
      } else {
        const grp = items.find(
          (it): it is Group =>
            it.type === "group" && it.id === overContainer.groupId,
        );
        if (!grp) return;
        destIndexInContainer = grp.items.findIndex((t) => t.id === overId);
      }
    }

    const sameType =
      srcContainer.type === destContainer.type &&
      (srcContainer.type === "bucket" ||
        (srcContainer as { type: "group"; groupId: number }).groupId ===
          (destContainer as { type: "group"; groupId: number }).groupId);

    if (sameType) {
      // ── Same container: reorder ──────────────────────────────────────────
      if (srcContainer.type === "bucket") {
        const fromIdx = items.findIndex(
          (it) => it.type === "task" && it.id === activeId,
        );
        if (fromIdx === -1) return;
        const toIdx = destIndexInContainer;
        const reordered = [...items];
        const [moved] = reordered.splice(fromIdx, 1);
        reordered.splice(toIdx, 0, moved);
        const newRank = computeMidpointRank(reordered, toIdx);
        onReorderTask(
          list.id,
          activeId,
          bucket.key,
          null,
          fromIdx,
          toIdx,
          newRank,
        );
      } else {
        const groupId = (srcContainer as { type: "group"; groupId: number })
          .groupId;
        const grp = items.find(
          (it): it is Group => it.type === "group" && it.id === groupId,
        )!;
        const fromIdx = grp.items.findIndex((t) => t.id === activeId);
        if (fromIdx === -1) return;
        const toIdx = destIndexInContainer;
        const reordered = [...grp.items];
        const [moved] = reordered.splice(fromIdx, 1);
        reordered.splice(toIdx, 0, moved);
        const newRank = computeGroupTaskRank(reordered, toIdx);
        onReorderTask(
          list.id,
          activeId,
          bucket.key,
          groupId,
          fromIdx,
          toIdx,
          newRank,
        );
      }
    } else {
      // ── Cross-container move ─────────────────────────────────────────────
      if (destContainer.type === "bucket") {
        // task leaving a group → standalone
        const grp = items.find(
          (it): it is Group =>
            it.type === "group" &&
            it.id ===
              (srcContainer as { type: "group"; groupId: number }).groupId,
        )!;
        const taskBeingMoved = grp.items.find((t) => t.id === activeId)!;

        // Compute rank relative to bucket-level items minus the source task
        const bucketLevelItems = items.filter(
          (it) => it.type === "group" || it.id !== activeId,
        ) as BucketItem[];
        const toIdx = Math.min(
          destIndexInContainer,
          bucketLevelItems.length - 1,
        );
        const reordered = [...bucketLevelItems];
        reordered.splice(toIdx, 0, { ...taskBeingMoved, rank: null } as Task);
        const newRank = computeMidpointRank(reordered, toIdx);
        onMoveTask(list.id, activeId, bucket.key, null, toIdx, newRank);
      } else {
        // task moving into a group (from standalone or different group)
        const destGroupId = (
          destContainer as { type: "group"; groupId: number }
        ).groupId;
        const destGrp = items.find(
          (it): it is Group => it.type === "group" && it.id === destGroupId,
        )!;
        const toIdx = Math.min(destIndexInContainer, destGrp.items.length);
        const tasksClone = [...destGrp.items];
        // find the task being moved to get a rank reference
        let movedTask: Task | undefined;
        for (const it of items) {
          if (it.type === "task" && it.id === activeId) {
            movedTask = it;
            break;
          }
          if (it.type === "group") {
            movedTask = it.items.find((t) => t.id === activeId);
            if (movedTask) break;
          }
        }
        if (!movedTask) return;
        tasksClone.splice(toIdx, 0, { ...movedTask, rank: null } as Task);
        const newRank = computeGroupTaskRank(tasksClone, toIdx);
        onMoveTask(list.id, activeId, bucket.key, destGroupId, toIdx, newRank);
      }
    }
  }

  function submitNewGroup() {
    const name = newGroupName.trim();
    if (!name) return;
    onCreateGroup(list.id, bucket.key, name);
    setNewGroupName("");
    setAddingGroup(false);
  }

  return (
    <div className="date-group">
      <span className="date-group-label">{bucket.label}</span>
      <DndContext
        sensors={sensors}
        collisionDetection={collisionDetection}
        onDragEnd={handleDragEnd}
      >
        <SortableContext items={ids} strategy={verticalListSortingStrategy}>
          <ul>
            {bucket.items.map((item) =>
              item.type === "task" ? (
                <SortableTask key={item.id} task={item} />
              ) : (
                <li key={`group-${item.id}`} className="group-item-wrapper">
                  <GroupContainer
                    group={item}
                    onRename={(gid, name) =>
                      onRenameGroup(list.id, gid, bucket.key, name)
                    }
                    onDelete={(gid) => onDeleteGroup(list.id, gid, bucket.key)}
                  />
                </li>
              ),
            )}
          </ul>
        </SortableContext>
      </DndContext>
      {addingGroup ? (
        <div className="add-group-form">
          <input
            className="group-name-input"
            placeholder="Group name"
            value={newGroupName}
            autoFocus
            onChange={(e) => setNewGroupName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submitNewGroup();
              if (e.key === "Escape") {
                setAddingGroup(false);
                setNewGroupName("");
              }
            }}
          />
          <button className="add-group-confirm" onClick={submitNewGroup}>
            Add
          </button>
          <button
            className="add-group-cancel"
            onClick={() => {
              setAddingGroup(false);
              setNewGroupName("");
            }}
          >
            Cancel
          </button>
        </div>
      ) : (
        <button className="add-group-btn" onClick={() => setAddingGroup(true)}>
          + group
        </button>
      )}
    </div>
  );
}

// ── Task list section ─────────────────────────────────────────────────────────

interface TaskListSectionProps {
  list: TaskList;
  onReorderTask: BucketSectionProps["onReorderTask"];
  onMoveTask: BucketSectionProps["onMoveTask"];
  onReorderGroup: BucketSectionProps["onReorderGroup"];
  onRenameGroup: BucketSectionProps["onRenameGroup"];
  onDeleteGroup: BucketSectionProps["onDeleteGroup"];
  onCreateGroup: BucketSectionProps["onCreateGroup"];
}

function TaskListSection({
  list,
  onReorderTask,
  onMoveTask,
  onReorderGroup,
  onRenameGroup,
  onDeleteGroup,
  onCreateGroup,
}: TaskListSectionProps) {
  return (
    <div className="task-list-section">
      <h3>{list.title}</h3>
      {list.buckets.map((bucket) => (
        <BucketSection
          key={bucket.key}
          bucket={bucket}
          list={list}
          onReorderTask={onReorderTask}
          onMoveTask={onMoveTask}
          onReorderGroup={onReorderGroup}
          onRenameGroup={onRenameGroup}
          onDeleteGroup={onDeleteGroup}
          onCreateGroup={onCreateGroup}
        />
      ))}
    </div>
  );
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export function TasksPanel() {
  const {
    taskLists,
    isLoading,
    error,
    reorderTask,
    moveTask,
    reorderGroup,
    createGroup,
    renameGroup,
    deleteGroup,
  } = useTasksPanel();

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
            onReorderTask={reorderTask}
            onMoveTask={moveTask}
            onReorderGroup={reorderGroup}
            onRenameGroup={renameGroup}
            onDeleteGroup={deleteGroup}
            onCreateGroup={(listId, bucketKey, name) =>
              void createGroup(listId, bucketKey, name)
            }
          />
        ))}
    </section>
  );
}
