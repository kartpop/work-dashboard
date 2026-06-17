import {
  DndContext,
  type DragEndEvent,
  type CollisionDetection,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  pointerWithin,
  useDroppable,
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
import { useEffect, useRef, useState } from "react";

import {
  type Bucket,
  type BucketItem,
  type Group,
  type Task,
  type TaskList,
  useTasksPanel,
} from "./useTasksPanel";

// A minimal {id,title} reference to every list, for the move-to-list picker.
interface ListRef {
  id: string;
  title: string;
}

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

/**
 * Find which bucket of a list contains a given sortable id. `id` may be a
 * standalone task id, a `group-{id}` header, or a task id nested in a group.
 */
function findBucketForId(buckets: Bucket[], id: string): Bucket | null {
  if (id.startsWith("group-")) {
    const groupId = parseInt(id.slice(6), 10);
    return (
      buckets.find((b) =>
        b.items.some((it) => it.type === "group" && it.id === groupId),
      ) ?? null
    );
  }
  return (
    buckets.find(
      (b) =>
        b.items.some((it) => it.type === "task" && it.id === id) ||
        b.items.some(
          (it) => it.type === "group" && it.items.some((t) => t.id === id),
        ),
    ) ?? null
  );
}

// ── Draggable task ────────────────────────────────────────────────────────────

interface SortableTaskProps {
  task: Task;
  compact?: boolean;
  // otherLists is the move-to-list picker set (current list already excluded).
  otherLists: ListRef[];
  onMoveToList: (taskId: string, targetListId: string) => void;
}

function SortableTask({
  task,
  compact,
  otherLists,
  onMoveToList,
}: SortableTaskProps) {
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

  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onPointerDown(e: PointerEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [menuOpen]);

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
      <div className="task-menu-wrap" ref={menuRef}>
        <button
          className="task-menu"
          aria-label="task actions"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            setMenuOpen((o) => !o);
          }}
        >
          ⋯
        </button>
        {menuOpen && (
          <div className="task-menu-popover" role="menu">
            <span className="task-menu-title">Move to list…</span>
            {otherLists.length === 0 ? (
              <span className="task-menu-empty">No other lists</span>
            ) : (
              otherLists.map((l) => (
                <button
                  key={l.id}
                  className="move-to-list-option"
                  role="menuitem"
                  onClick={(e) => {
                    e.stopPropagation();
                    setMenuOpen(false);
                    onMoveToList(task.id, l.id);
                  }}
                >
                  {l.title}
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </li>
  );
}

// ── Group container ───────────────────────────────────────────────────────────

interface GroupContainerProps {
  group: Group;
  otherLists: ListRef[];
  onRename: (groupId: number, name: string) => void;
  onDelete: (groupId: number) => void;
  onMoveToList: (taskId: string, targetListId: string) => void;
}

function GroupContainer({
  group,
  otherLists,
  onRename,
  onDelete,
  onMoveToList,
}: GroupContainerProps) {
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
          <SortableTask
            key={task.id}
            task={task}
            compact
            otherLists={otherLists}
            onMoveToList={onMoveToList}
          />
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
  otherLists: ListRef[];
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
  onMoveToList: (taskId: string, targetListId: string) => void;
}

function BucketSection({
  bucket,
  list,
  otherLists,
  onRenameGroup,
  onDeleteGroup,
  onCreateGroup,
  onMoveToList,
}: BucketSectionProps) {
  const [addingGroup, setAddingGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");

  // Droppable for the whole bucket so empty/open-area drops resolve to a bucket.
  const { setNodeRef: setDroppableRef } = useDroppable({
    id: `bucket:${bucket.key}`,
  });

  const ids = flatItemIds(bucket.items);

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
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <ul ref={setDroppableRef} className="bucket-droppable">
          {bucket.items.map((item) =>
            item.type === "task" ? (
              <SortableTask
                key={item.id}
                task={item}
                otherLists={otherLists}
                onMoveToList={onMoveToList}
              />
            ) : (
              <li key={`group-${item.id}`} className="group-item-wrapper">
                <GroupContainer
                  group={item}
                  otherLists={otherLists}
                  onRename={(gid, name) =>
                    onRenameGroup(list.id, gid, bucket.key, name)
                  }
                  onDelete={(gid) => onDeleteGroup(list.id, gid, bucket.key)}
                  onMoveToList={onMoveToList}
                />
              </li>
            ),
          )}
        </ul>
      </SortableContext>
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
// ONE DndContext wraps ALL buckets of a single list, so a drag can leave its
// bucket. handleDragEnd resolves source/dest buckets across the whole list.

interface TaskListSectionProps {
  list: TaskList;
  otherLists: ListRef[];
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
  onRescheduleTask: (
    listId: string,
    taskId: string,
    fromBucketKey: string,
    toBucketKey: string,
    dueDate: string | null,
    destGroupId: number | null,
    destIndex: number,
    newRank: number,
  ) => void;
  onRenameGroup: BucketSectionProps["onRenameGroup"];
  onDeleteGroup: BucketSectionProps["onDeleteGroup"];
  onCreateGroup: BucketSectionProps["onCreateGroup"];
  onMoveToList: (listId: string, taskId: string, targetListId: string) => void;
}

function TaskListSection({
  list,
  otherLists,
  onReorderTask,
  onMoveTask,
  onReorderGroup,
  onRescheduleTask,
  onRenameGroup,
  onDeleteGroup,
  onCreateGroup,
  onMoveToList,
}: TaskListSectionProps) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  // Keep a ref to the latest buckets for use inside handleDragEnd (which is a
  // stable-ish closure invoked after render). Update the ref in an effect so we
  // never write to a ref during render.
  const bucketsRef = useRef(list.buckets);
  useEffect(() => {
    bucketsRef.current = list.buckets;
  }, [list.buckets]);

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const buckets = bucketsRef.current;
    const activeId = String(active.id);
    const overId = String(over.id);

    // Resolve source bucket (which bucket holds activeId).
    const srcBucket = findBucketForId(buckets, activeId);
    if (!srcBucket) return;

    // Resolve destination bucket. overId may be a task id, a `group-{id}`, a
    // task inside a group, or a `bucket:{key}` droppable.
    let destBucket: Bucket | null;
    if (overId.startsWith("bucket:")) {
      const key = overId.slice("bucket:".length);
      destBucket = buckets.find((b) => b.key === key) ?? null;
    } else {
      destBucket = findBucketForId(buckets, overId);
    }
    if (!destBucket) return;

    // ── Group reorder (groups never span buckets) ─────────────────────────────
    if (activeId.startsWith("group-")) {
      // Only allow reorder within the SAME bucket.
      if (destBucket.key !== srcBucket.key) return;
      const items = srcBucket.items;
      const groupId = parseInt(activeId.slice(6), 10);
      const fromIndex = findBucketItemIndex(activeId, items);
      if (fromIndex === -1) return;

      let toIndex: number;
      if (overId.startsWith("bucket:")) {
        // dropping on the open bucket area → move to the end
        toIndex = items.length - 1;
      } else {
        // overId may be a task inside a group (flat SortableContext) — resolve
        // it to that group's header id before indexing at bucket level.
        let resolvedOverId = overId;
        if (!overId.startsWith("group-")) {
          const overContainer = findContainer(overId, items);
          if (overContainer?.type === "group")
            resolvedOverId = `group-${overContainer.groupId}`;
        }
        toIndex = findBucketItemIndex(resolvedOverId, items);
      }
      if (toIndex === -1 || fromIndex === toIndex) return;

      const reordered = [...items];
      const [moved] = reordered.splice(fromIndex, 1);
      reordered.splice(toIndex, 0, moved);
      const newRank = computeMidpointRank(reordered, toIndex);
      onReorderGroup(
        list.id,
        groupId,
        srcBucket.key,
        fromIndex,
        toIndex,
        newRank,
      );
      return;
    }

    // ── Task drag ─────────────────────────────────────────────────────────────
    // Resolve the destination container (bucket open-area, a group, or a
    // specific task position) within destBucket.
    const destItems = destBucket.items;
    let destContainer: ContainerRef;
    let destIndexInContainer: number;

    if (overId.startsWith("bucket:")) {
      // Dropped on the open bucket area → append to the end of standalone items.
      destContainer = { type: "bucket" };
      destIndexInContainer = destItems.length;
    } else if (overId.startsWith("group-")) {
      // Dropped on a group header → append to that group.
      const groupId = parseInt(overId.slice(6), 10);
      const grp = destItems.find(
        (it): it is Group => it.type === "group" && it.id === groupId,
      );
      if (!grp) return;
      destContainer = { type: "group", groupId };
      destIndexInContainer = grp.items.length;
    } else {
      const overContainer = findContainer(overId, destItems);
      if (!overContainer) return;
      destContainer = overContainer;
      if (overContainer.type === "bucket") {
        destIndexInContainer = destItems.findIndex(
          (it) => it.type === "task" && it.id === overId,
        );
      } else {
        const grp = destItems.find(
          (it): it is Group =>
            it.type === "group" && it.id === overContainer.groupId,
        );
        if (!grp) return;
        destIndexInContainer = grp.items.findIndex((t) => t.id === overId);
      }
    }

    // ── Cross-bucket drag = RESCHEDULE ────────────────────────────────────────
    if (destBucket.key !== srcBucket.key) {
      const dueDate = destBucket.key === "NO_DATE" ? null : destBucket.key;
      const destGroupId =
        destContainer.type === "group" ? destContainer.groupId : null;

      // Compute destIndex + newRank against the DEST container, with the task
      // hypothetically inserted at the drop position.
      const srcItems = srcBucket.items;
      let movedTask: Task | null = null;
      for (const it of srcItems) {
        if (it.type === "task" && it.id === activeId) {
          movedTask = it;
          break;
        }
        if (it.type === "group") {
          const f = it.items.find((t) => t.id === activeId);
          if (f) {
            movedTask = f;
            break;
          }
        }
      }
      if (!movedTask) return;

      let destIndex: number;
      let newRank: number;
      if (destGroupId === null) {
        // Insert among the dest bucket's standalone-level items.
        const toIdx = Math.min(destIndexInContainer, destItems.length);
        const clone = [...destItems];
        clone.splice(toIdx, 0, { ...movedTask, rank: null } as Task);
        newRank = computeMidpointRank(clone, toIdx);
        destIndex = toIdx;
      } else {
        const destGrp = destItems.find(
          (it): it is Group => it.type === "group" && it.id === destGroupId,
        );
        if (!destGrp) return;
        const toIdx = Math.min(destIndexInContainer, destGrp.items.length);
        const clone = [...destGrp.items];
        clone.splice(toIdx, 0, { ...movedTask, rank: null } as Task);
        newRank = computeGroupTaskRank(clone, toIdx);
        destIndex = toIdx;
      }

      onRescheduleTask(
        list.id,
        activeId,
        srcBucket.key,
        destBucket.key,
        dueDate,
        destGroupId,
        destIndex,
        newRank,
      );
      return;
    }

    // ── Same bucket: behave exactly as goal 3 (overlay PATCH only) ─────────────
    const items = srcBucket.items;
    const srcContainer = findContainer(activeId, items);
    if (!srcContainer) return;

    const sameType =
      srcContainer.type === destContainer.type &&
      (srcContainer.type === "bucket" ||
        (srcContainer as { type: "group"; groupId: number }).groupId ===
          (destContainer as { type: "group"; groupId: number }).groupId);

    if (sameType) {
      // ── Same container: reorder ─────────────────────────────────────────────
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
          srcBucket.key,
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
          srcBucket.key,
          groupId,
          fromIdx,
          toIdx,
          newRank,
        );
      }
    } else {
      // ── Cross-container move within the same bucket ─────────────────────────
      if (destContainer.type === "bucket") {
        // task leaving a group → standalone
        const grp = items.find(
          (it): it is Group =>
            it.type === "group" &&
            it.id ===
              (srcContainer as { type: "group"; groupId: number }).groupId,
        )!;
        const taskBeingMoved = grp.items.find((t) => t.id === activeId)!;

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
        onMoveTask(list.id, activeId, srcBucket.key, null, toIdx, newRank);
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
        onMoveTask(
          list.id,
          activeId,
          srcBucket.key,
          destGroupId,
          toIdx,
          newRank,
        );
      }
    }
  }

  return (
    <div className="task-list-section">
      <h3>{list.title}</h3>
      <DndContext
        sensors={sensors}
        collisionDetection={collisionDetection}
        onDragEnd={handleDragEnd}
      >
        {list.buckets.map((bucket) => (
          <BucketSection
            key={bucket.key}
            bucket={bucket}
            list={list}
            otherLists={otherLists}
            onRenameGroup={onRenameGroup}
            onDeleteGroup={onDeleteGroup}
            onCreateGroup={onCreateGroup}
            onMoveToList={(taskId, targetListId) =>
              onMoveToList(list.id, taskId, targetListId)
            }
          />
        ))}
      </DndContext>
    </div>
  );
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export function TasksPanel() {
  const {
    taskLists,
    isLoading,
    error,
    writeError,
    reorderTask,
    moveTask,
    reorderGroup,
    createGroup,
    renameGroup,
    deleteGroup,
    rescheduleTask,
    moveTaskToList,
    dismissWriteError,
  } = useTasksPanel();

  // Auto-dismiss the toast after ~4s.
  useEffect(() => {
    if (!writeError) return;
    const id = window.setTimeout(dismissWriteError, 4000);
    return () => window.clearTimeout(id);
  }, [writeError, dismissWriteError]);

  const allLists: ListRef[] = taskLists.map((l) => ({
    id: l.id,
    title: l.title,
  }));

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
            otherLists={allLists.filter((l) => l.id !== list.id)}
            onReorderTask={reorderTask}
            onMoveTask={moveTask}
            onReorderGroup={reorderGroup}
            onRescheduleTask={rescheduleTask}
            onRenameGroup={renameGroup}
            onDeleteGroup={deleteGroup}
            onCreateGroup={(listId, bucketKey, name) =>
              void createGroup(listId, bucketKey, name)
            }
            onMoveToList={moveTaskToList}
          />
        ))}
      {writeError && (
        <div className="toast" role="alert">
          <span>{writeError}</span>
          <button
            className="toast-dismiss"
            aria-label="dismiss"
            onClick={dismissWriteError}
          >
            ×
          </button>
        </div>
      )}
    </section>
  );
}
