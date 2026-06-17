import { useCallback, useEffect, useRef, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPost } from "../../api";

export interface Task {
  type: "task";
  id: string;
  title: string;
  status: string;
  due: string | null;
  notes: string | null;
  rank: number | null;
  group_id: number | null;
}

export interface Group {
  type: "group";
  id: number;
  name: string;
  rank: number | null;
  items: Task[];
}

export type BucketItem = Task | Group;

export interface Bucket {
  label: string;
  key: string;
  items: BucketItem[];
}

export interface TaskList {
  id: string;
  title: string;
  buckets: Bucket[];
}

interface TasksResponse {
  task_lists: TaskList[];
}

interface TasksPanelState {
  taskLists: TaskList[];
  isLoading: boolean;
  error: string | null;
  writeError: string | null;
}

// ── Pure helpers for optimistic state transforms ──────────────────────────────

function updateBucket(
  state: TasksPanelState,
  tasklistId: string,
  bucketKey: string,
  updater: (items: BucketItem[]) => BucketItem[],
): TasksPanelState {
  return {
    ...state,
    taskLists: state.taskLists.map((list) => {
      if (list.id !== tasklistId) return list;
      return {
        ...list,
        buckets: list.buckets.map((b) => {
          if (b.key !== bucketKey) return b;
          return { ...b, items: updater(b.items) };
        }),
      };
    }),
  };
}

/**
 * Remove a task (standalone OR inside a group) from a bucket's items.
 * If removing it empties its source group, the group is dropped — mirroring
 * `moveTask`'s auto-remove. Returns the new items array; other rows untouched.
 */
function removeTaskFromItems(
  items: BucketItem[],
  taskId: string,
): BucketItem[] {
  return items
    .map((item) => {
      if (item.type === "task") {
        return item.id === taskId ? null : item;
      }
      const idx = item.items.findIndex((t) => t.id === taskId);
      if (idx === -1) return item;
      const remaining = item.items.filter((t) => t.id !== taskId);
      return remaining.length > 0 ? { ...item, items: remaining } : null;
    })
    .filter((it): it is BucketItem => it !== null);
}

/** Find a task anywhere in a bucket's items (standalone or nested in a group). */
function findTaskInItems(items: BucketItem[], taskId: string): Task | null {
  for (const item of items) {
    if (item.type === "task" && item.id === taskId) return item;
    if (item.type === "group") {
      const found = item.items.find((t) => t.id === taskId);
      if (found) return found;
    }
  }
  return null;
}

/** Insert a task into a bucket's items, either standalone or into a group. */
function insertTaskIntoItems(
  items: BucketItem[],
  task: Task,
  destGroupId: number | null,
  destIndex: number,
): BucketItem[] {
  if (destGroupId === null) {
    const result = [...items];
    result.splice(destIndex, 0, task);
    return result;
  }
  return items.map((item) => {
    if (item.type !== "group" || item.id !== destGroupId) return item;
    const tasks = [...item.items];
    tasks.splice(destIndex, 0, task);
    return { ...item, items: tasks };
  });
}

/**
 * Move a task between two buckets within the same list (cross-bucket reschedule).
 * Removes from the source bucket (with group auto-remove), updates its fields,
 * and inserts into the destination bucket at destIndex.
 */
function moveTaskAcrossBuckets(
  state: TasksPanelState,
  tasklistId: string,
  taskId: string,
  fromBucketKey: string,
  toBucketKey: string,
  updatedTask: Task,
  destGroupId: number | null,
  destIndex: number,
): TasksPanelState {
  return {
    ...state,
    taskLists: state.taskLists.map((list) => {
      if (list.id !== tasklistId) return list;
      return {
        ...list,
        buckets: list.buckets.map((b) => {
          if (b.key === fromBucketKey) {
            return { ...b, items: removeTaskFromItems(b.items, taskId) };
          }
          if (b.key === toBucketKey) {
            return {
              ...b,
              items: insertTaskIntoItems(
                b.items,
                updatedTask,
                destGroupId,
                destIndex,
              ),
            };
          }
          return b;
        }),
      };
    }),
  };
}

/** Remove a task from a whole list (any bucket / group), with group auto-remove. */
function removeTaskFromList(
  state: TasksPanelState,
  tasklistId: string,
  taskId: string,
): TasksPanelState {
  return {
    ...state,
    taskLists: state.taskLists.map((list) => {
      if (list.id !== tasklistId) return list;
      return {
        ...list,
        buckets: list.buckets.map((b) => ({
          ...b,
          items: removeTaskFromItems(b.items, taskId),
        })),
      };
    }),
  };
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useTasksPanel() {
  const [state, setState] = useState<TasksPanelState>({
    taskLists: [],
    isLoading: true,
    error: null,
    writeError: null,
  });

  // Holds the pre-op snapshot of taskLists, captured inside a setState updater
  // so it reflects the latest committed state before an optimistic mutation.
  const snapshotRef = useRef<TaskList[] | null>(null);

  // Initial load. The fetch is async (setState fires in its callbacks, not
  // synchronously in the effect body), and initial state is already
  // `isLoading: true`, so there is no synchronous setState in the effect.
  useEffect(() => {
    let cancelled = false;
    apiGet<TasksResponse>("/tasks?view=grouped")
      .then((data) => {
        if (!cancelled)
          setState((s) => ({
            ...s,
            taskLists: data.task_lists,
            isLoading: false,
            error: null,
          }));
      })
      .catch((err: Error) => {
        if (!cancelled)
          setState((s) => ({
            ...s,
            taskLists: [],
            isLoading: false,
            error: err.message,
          }));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Refetch task lists WITHOUT flipping isLoading (no spinner flash). Used after
  // a cross-list move so the moved task appears in its destination, correctly
  // bucketed, with the server-assigned new task id.
  const refetchSilently = useCallback(async () => {
    const data = await apiGet<TasksResponse>("/tasks?view=grouped");
    setState((s) => ({ ...s, taskLists: data.task_lists }));
  }, []);

  const dismissWriteError = useCallback(() => {
    setState((s) => ({ ...s, writeError: null }));
  }, []);

  // Reorder a task within its current container (same group or same standalone zone).
  // Rank is pre-computed by the component.
  const reorderTask = useCallback(
    (
      tasklistId: string,
      taskId: string,
      bucketKey: string,
      groupId: number | null,
      fromIndex: number,
      toIndex: number,
      newRank: number,
    ) => {
      setState((prev) =>
        updateBucket(prev, tasklistId, bucketKey, (items) => {
          if (groupId === null) {
            // reorder at bucket level (standalone task moving among bucket items)
            const idx = items.findIndex(
              (it) => it.type === "task" && it.id === taskId,
            );
            if (idx === -1) return items;
            const next = [...items];
            const [moved] = next.splice(idx, 1);
            next.splice(toIndex, 0, moved);
            return next;
          } else {
            return items.map((item) => {
              if (item.type !== "group" || item.id !== groupId) return item;
              const tasks = [...item.items];
              const [moved] = tasks.splice(fromIndex, 1);
              tasks.splice(toIndex, 0, moved);
              return { ...item, items: tasks };
            });
          }
        }),
      );
      apiPatch(`/tasks/${tasklistId}/${taskId}/overlay`, {
        rank: newRank,
      }).catch(() => {});
    },
    [],
  );

  // Move a task between containers (standalone ↔ group, or group → different group).
  const moveTask = useCallback(
    (
      tasklistId: string,
      taskId: string,
      bucketKey: string,
      destGroupId: number | null,
      destIndex: number,
      newRank: number,
    ) => {
      setState((prev) =>
        updateBucket(prev, tasklistId, bucketKey, (items) => {
          // find and extract the task
          let task: Task | null = null;
          const withoutTask = items
            .map((item) => {
              if (item.type === "task" && item.id === taskId) {
                task = { ...item, group_id: destGroupId, rank: newRank };
                return null;
              }
              if (item.type === "group") {
                const idx = item.items.findIndex((t) => t.id === taskId);
                if (idx !== -1) {
                  task = {
                    ...item.items[idx],
                    group_id: destGroupId,
                    rank: newRank,
                  };
                  const remaining = item.items.filter((t) => t.id !== taskId);
                  return remaining.length > 0
                    ? { ...item, items: remaining }
                    : null;
                }
              }
              return item;
            })
            .filter((it): it is BucketItem => it !== null);

          if (!task) return items;

          if (destGroupId === null) {
            // insert as standalone at destIndex in the bucket items
            const result = [...withoutTask];
            result.splice(destIndex, 0, task);
            return result;
          } else {
            // insert into the target group
            return withoutTask.map((item) => {
              if (item.type !== "group" || item.id !== destGroupId) return item;
              const tasks = [...item.items];
              tasks.splice(destIndex, 0, task!);
              return { ...item, items: tasks };
            });
          }
        }),
      );
      const patch: Record<string, unknown> = {
        rank: newRank,
        group_id: destGroupId,
      };
      apiPatch(`/tasks/${tasklistId}/${taskId}/overlay`, patch).catch(() => {});
    },
    [],
  );

  // Reorder a group among bucket-level items.
  const reorderGroup = useCallback(
    (
      tasklistId: string,
      groupId: number,
      bucketKey: string,
      fromIndex: number,
      toIndex: number,
      newRank: number,
    ) => {
      setState((prev) =>
        updateBucket(prev, tasklistId, bucketKey, (items) => {
          const next = [...items];
          const [moved] = next.splice(fromIndex, 1);
          next.splice(toIndex, 0, moved);
          return next;
        }),
      );
      apiPatch(`/tasks/${tasklistId}/groups/${groupId}`, {
        rank: newRank,
      }).catch(() => {});
    },
    [],
  );

  // Create a group; insert from POST response so no reload is needed.
  const createGroup = useCallback(
    async (
      tasklistId: string,
      bucketKey: string,
      name: string,
      rank?: number,
    ) => {
      const data = await apiPost<{
        id: number;
        name: string;
        rank: number | null;
      }>(`/tasks/${tasklistId}/groups`, { name, bucket_key: bucketKey, rank });
      const grp: Group = {
        type: "group",
        id: data.id,
        name: data.name,
        rank: data.rank,
        items: [],
      };
      setState((prev) =>
        updateBucket(prev, tasklistId, bucketKey, (items) => [...items, grp]),
      );
      return grp;
    },
    [],
  );

  // Rename a group (optimistic).
  const renameGroup = useCallback(
    (tasklistId: string, groupId: number, bucketKey: string, name: string) => {
      setState((prev) =>
        updateBucket(prev, tasklistId, bucketKey, (items) =>
          items.map((item) =>
            item.type === "group" && item.id === groupId
              ? { ...item, name }
              : item,
          ),
        ),
      );
      apiPatch(`/tasks/${tasklistId}/groups/${groupId}`, { name }).catch(
        () => {},
      );
    },
    [],
  );

  // Delete a group; member tasks become standalone (optimistic).
  const deleteGroup = useCallback(
    (tasklistId: string, groupId: number, bucketKey: string) => {
      setState((prev) =>
        updateBucket(prev, tasklistId, bucketKey, (items) => {
          const result: BucketItem[] = [];
          for (const item of items) {
            if (item.type === "group" && item.id === groupId) {
              // ungrouped tasks go to standalone
              result.push(...item.items.map((t) => ({ ...t, group_id: null })));
            } else {
              result.push(item);
            }
          }
          return result;
        }),
      );
      apiDelete(`/tasks/${tasklistId}/groups/${groupId}`).catch(() => {});
    },
    [],
  );

  // ── Google writes (snapshot + optimistic + POST + rollback + toast) ─────────

  // Cross-bucket drag = reschedule. Moves a task to another date-bucket in the
  // same list: due-date change + group-aware drop + overlay rank. Optimistic
  // across TWO buckets; one POST; snapshot-rollback + toast on failure.
  const rescheduleTask = useCallback(
    (
      listId: string,
      taskId: string,
      fromBucketKey: string,
      toBucketKey: string,
      dueDate: string | null,
      destGroupId: number | null,
      destIndex: number,
      newRank: number,
    ) => {
      setState((prev) => {
        // Snapshot BEFORE applying the optimistic update.
        snapshotRef.current = prev.taskLists;

        const list = prev.taskLists.find((l) => l.id === listId);
        if (!list) return prev;
        const fromBucket = list.buckets.find((b) => b.key === fromBucketKey);
        if (!fromBucket) return prev;
        const original = findTaskInItems(fromBucket.items, taskId);
        if (!original) return prev;

        const updatedTask: Task = {
          ...original,
          due: dueDate ? `${dueDate}T00:00:00.000Z` : null,
          group_id: destGroupId,
          rank: newRank,
        };

        return moveTaskAcrossBuckets(
          prev,
          listId,
          taskId,
          fromBucketKey,
          toBucketKey,
          updatedTask,
          destGroupId,
          destIndex,
        );
      });

      apiPost(`/tasks/${listId}/${taskId}/reschedule`, {
        due_date: dueDate,
        rank: newRank,
        group_id: destGroupId,
      }).catch((err: Error) => {
        const snapshot = snapshotRef.current;
        setState((s) => ({
          ...s,
          taskLists: snapshot ?? s.taskLists,
          writeError: `Reschedule failed: ${err.message}`,
        }));
      });
    },
    [],
  );

  // Move a task to another list via the menu (insert + delete on the backend).
  // Optimistically remove it here; on success silently refetch so it appears
  // in the target list correctly bucketed. Rollback + toast on failure.
  const moveTaskToList = useCallback(
    (listId: string, taskId: string, targetListId: string) => {
      setState((prev) => {
        snapshotRef.current = prev.taskLists;
        return removeTaskFromList(prev, listId, taskId);
      });

      apiPost(`/tasks/${listId}/${taskId}/move`, {
        target_list_id: targetListId,
      })
        .then(() => {
          // Move succeeded server-side. Silently refetch so the moved task
          // shows in its destination. A refetch failure is NOT a move rollback
          // (the task already moved) — swallow it; next load will reconcile.
          refetchSilently().catch(() => {});
        })
        .catch((err: Error) => {
          const snapshot = snapshotRef.current;
          setState((s) => ({
            ...s,
            taskLists: snapshot ?? s.taskLists,
            writeError: `Move failed: ${err.message}`,
          }));
        });
    },
    [refetchSilently],
  );

  return {
    ...state,
    reorderTask,
    moveTask,
    reorderGroup,
    createGroup,
    renameGroup,
    deleteGroup,
    rescheduleTask,
    moveTaskToList,
    dismissWriteError,
  };
}
