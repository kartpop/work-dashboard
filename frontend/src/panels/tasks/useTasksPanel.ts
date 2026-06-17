import { useCallback, useEffect, useRef, useState } from "react";
import { apiDelete, apiGet, apiPatch, apiPost } from "../../api";

export interface Task {
  type: "task";
  id: string;
  title: string;
  status: string;
  due: string | null;
  notes: string | null;
  // Google subtask parent id; rendered flat (MVP) — never dropped/duplicated.
  parent: string | null;
  rank: number | null;
  group_id: number | null;
}

// A transient toast carrying an Undo affordance. Used by two distinct state
// machines (see .claude/rules/tasks-panel.md): completion writes to Google
// immediately (Undo = uncomplete), delete defers the Google write until the
// window closes (Undo = cancel, zero Google writes).
export interface ActionToast {
  message: string;
}

const ACTION_TOAST_MS = 5000;

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
  actionToast: ActionToast | null;
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

/** Shallow-patch a task's fields wherever it lives (standalone or in a group). */
function updateTaskFields(
  state: TasksPanelState,
  tasklistId: string,
  taskId: string,
  patch: Partial<Task>,
): TasksPanelState {
  return {
    ...state,
    taskLists: state.taskLists.map((list) => {
      if (list.id !== tasklistId) return list;
      return {
        ...list,
        buckets: list.buckets.map((b) => ({
          ...b,
          items: b.items.map((it) => {
            if (it.type === "task" && it.id === taskId)
              return { ...it, ...patch };
            if (it.type === "group") {
              return {
                ...it,
                items: it.items.map((t) =>
                  t.id === taskId ? { ...t, ...patch } : t,
                ),
              };
            }
            return it;
          }),
        })),
      };
    }),
  };
}

/** Insert a task at the top of a list's NO_DATE bucket (creating it if absent). */
function insertAtTopOfNoDate(
  state: TasksPanelState,
  tasklistId: string,
  task: Task,
): TasksPanelState {
  return {
    ...state,
    taskLists: state.taskLists.map((list) => {
      if (list.id !== tasklistId) return list;
      const idx = list.buckets.findIndex((b) => b.key === "NO_DATE");
      if (idx === -1) {
        return {
          ...list,
          buckets: [
            ...list.buckets,
            { label: "No date", key: "NO_DATE", items: [task] },
          ],
        };
      }
      return {
        ...list,
        buckets: list.buckets.map((b) =>
          b.key === "NO_DATE" ? { ...b, items: [task, ...b.items] } : b,
        ),
      };
    }),
  };
}

/** Replace a standalone task (matched by id) in a list with a new task object. */
function replaceTaskInList(
  state: TasksPanelState,
  tasklistId: string,
  oldId: string,
  newTask: Task,
): TasksPanelState {
  return {
    ...state,
    taskLists: state.taskLists.map((list) => {
      if (list.id !== tasklistId) return list;
      return {
        ...list,
        buckets: list.buckets.map((b) => ({
          ...b,
          items: b.items.map((it) =>
            it.type === "task" && it.id === oldId ? newTask : it,
          ),
        })),
      };
    }),
  };
}

// ── Client-side bucketing (move-to-list optimistic placement only) ─────────────
// Mirrors the backend bucket rules (IST date key, NO_DATE, Overdue rollup) just
// enough to drop a moved task into the right destination bucket WITHOUT a reload.
// The backend remains the source of truth; a later refresh reconciles any drift.

function istDateKey(d: Date): string {
  const ist = new Date(d.getTime() + 5.5 * 3600 * 1000);
  return ist.toISOString().slice(0, 10);
}

function bucketKeyForDue(due: string | null): string {
  if (!due) return "NO_DATE";
  const key = istDateKey(new Date(due));
  return key < istDateKey(new Date()) ? "OVERDUE" : key;
}

function bucketLabelForKey(key: string): string {
  if (key === "NO_DATE") return "No date";
  if (key === "OVERDUE") return "Overdue";
  const today = istDateKey(new Date());
  if (key === today) return "Today";
  const t = new Date(today + "T00:00:00Z");
  const tomorrow = istDateKey(new Date(t.getTime() + 24 * 3600 * 1000));
  if (key === tomorrow) return "Tomorrow";
  return new Date(key + "T00:00:00Z").toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

/** Insert a moved task into a destination list at the top of its due-date bucket. */
function insertMovedTask(
  state: TasksPanelState,
  targetListId: string,
  task: Task,
): TasksPanelState {
  const key = bucketKeyForDue(task.due);
  return {
    ...state,
    taskLists: state.taskLists.map((list) => {
      if (list.id !== targetListId) return list;
      const idx = list.buckets.findIndex((b) => b.key === key);
      if (idx === -1) {
        const bucket: Bucket = {
          label: bucketLabelForKey(key),
          key,
          items: [task],
        };
        // Overdue sits at the top; everything else is appended (a later refresh
        // settles exact ordering against the backend's sort).
        return key === "OVERDUE"
          ? { ...list, buckets: [bucket, ...list.buckets] }
          : { ...list, buckets: [...list.buckets, bucket] };
      }
      return {
        ...list,
        buckets: list.buckets.map((b) =>
          b.key === key ? { ...b, items: [task, ...b.items] } : b,
        ),
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
    actionToast: null,
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

  // ── Action-toast state machine (Undo for completion + delete) ───────────────
  // Only one toast is shown at a time. `onExpire` runs when the ~5s window
  // closes (delete: fire the held Google DELETE; completion: no-op — the write
  // already happened). `onUndo` runs on the Undo click. Pushing a new toast
  // commits any in-flight one first, so a deferred delete can never be orphaned.
  const toastTimerRef = useRef<number | null>(null);
  const pendingExpireRef = useRef<(() => void) | null>(null);
  const pendingUndoRef = useRef<(() => void) | null>(null);

  const commitPending = useCallback(() => {
    if (toastTimerRef.current !== null) {
      window.clearTimeout(toastTimerRef.current);
      toastTimerRef.current = null;
    }
    const expire = pendingExpireRef.current;
    pendingExpireRef.current = null;
    pendingUndoRef.current = null;
    if (expire) expire();
  }, []);

  const pushActionToast = useCallback(
    (message: string, onUndo: () => void, onExpire: () => void) => {
      commitPending(); // flush any still-open window before opening a new one
      pendingExpireRef.current = onExpire;
      pendingUndoRef.current = onUndo;
      setState((s) => ({ ...s, actionToast: { message } }));
      toastTimerRef.current = window.setTimeout(() => {
        toastTimerRef.current = null;
        const expire = pendingExpireRef.current;
        pendingExpireRef.current = null;
        pendingUndoRef.current = null;
        setState((s) => ({ ...s, actionToast: null }));
        if (expire) expire();
      }, ACTION_TOAST_MS);
    },
    [commitPending],
  );

  const undoActionToast = useCallback(() => {
    if (toastTimerRef.current !== null) {
      window.clearTimeout(toastTimerRef.current);
      toastTimerRef.current = null;
    }
    const undo = pendingUndoRef.current;
    pendingExpireRef.current = null;
    pendingUndoRef.current = null;
    setState((s) => ({ ...s, actionToast: null }));
    if (undo) undo();
  }, []);

  // Flush any pending deferred action when the panel unmounts (don't orphan a
  // delete that the user neither undid nor waited out).
  useEffect(() => () => commitPending(), [commitPending]);

  // Manual per-panel refresh (re-run GET /tasks) — surfaces phone-app changes
  // and a recurring task's next instance after completion.
  const refresh = useCallback(() => {
    refetchSilently().catch((err: Error) =>
      setState((s) => ({ ...s, writeError: `Refresh failed: ${err.message}` })),
    );
  }, [refetchSilently]);

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

  // ── Content CRUD (Google content writes, goal 4a) ──────────────────────────

  // Create a task at the top of NO_DATE. Optimistic temp row → POST → reconcile
  // the server-assigned id (insert-from-response, g3 createGroup pattern).
  const createTask = useCallback(async (listId: string, title: string) => {
    const trimmed = title.trim();
    if (!trimmed) return; // empty title rejected client-side
    const tempId = `temp-${Date.now()}`;
    let snapshot: TaskList[] | null = null;
    let rank = 1000;
    setState((prev) => {
      snapshot = prev.taskLists;
      const list = prev.taskLists.find((l) => l.id === listId);
      const noDate = list?.buckets.find((b) => b.key === "NO_DATE");
      const topRank =
        noDate && noDate.items.length
          ? Math.min(...noDate.items.map((it, i) => it.rank ?? (i + 1) * 1000))
          : 2000;
      rank = topRank - 1000;
      const temp: Task = {
        type: "task",
        id: tempId,
        title: trimmed,
        status: "needsAction",
        due: null,
        notes: null,
        parent: null,
        rank,
        group_id: null,
      };
      return insertAtTopOfNoDate(prev, listId, temp);
    });
    try {
      const created = await apiPost<Task>(`/tasks/${listId}`, {
        title: trimmed,
        rank,
      });
      setState((s) =>
        replaceTaskInList(s, listId, tempId, { ...created, type: "task" }),
      );
    } catch (err) {
      setState((s) => ({
        ...s,
        taskLists: snapshot ?? s.taskLists,
        writeError: `Create failed: ${(err as Error).message}`,
      }));
    }
  }, []);

  // Inline edit of title or notes. The component guards same-value (so a no-op
  // fires no PATCH); the hook applies optimistically and reconciles on failure.
  const editTaskField = useCallback(
    (
      listId: string,
      taskId: string,
      patch: { title?: string; notes?: string },
    ) => {
      let snapshot: TaskList[] | null = null;
      setState((prev) => {
        snapshot = prev.taskLists;
        return updateTaskFields(prev, listId, taskId, patch);
      });
      apiPatch(`/tasks/${listId}/${taskId}`, patch).catch((err: Error) => {
        setState((s) => ({
          ...s,
          taskLists: snapshot ?? s.taskLists,
          writeError: `Edit failed: ${err.message}`,
        }));
      });
    },
    [],
  );

  // Complete a task: optimistic remove from the active view + IMMEDIATE status
  // write, plus an Undo toast. Undo uncompletes and restores the snapshot
  // (position + group + any group auto-removed when it lost its last member).
  const completeTask = useCallback(
    (listId: string, taskId: string) => {
      let snapshot: TaskList[] | null = null;
      setState((prev) => {
        snapshot = prev.taskLists;
        return removeTaskFromList(prev, listId, taskId);
      });
      apiPatch(`/tasks/${listId}/${taskId}`, { status: "completed" }).catch(
        (err: Error) => {
          setState((s) => ({
            ...s,
            taskLists: snapshot ?? s.taskLists,
            writeError: `Complete failed: ${err.message}`,
          }));
        },
      );
      pushActionToast(
        "Task completed",
        () => {
          setState((s) => ({ ...s, taskLists: snapshot ?? s.taskLists }));
          apiPatch(`/tasks/${listId}/${taskId}`, {
            status: "needsAction",
          }).catch((err: Error) => {
            setState((s) => ({
              ...s,
              writeError: `Undo failed: ${err.message}`,
            }));
          });
        },
        () => {}, // expire: the complete write already happened
      );
    },
    [pushActionToast],
  );

  // Delete a task: optimistic remove + Undo toast. The Google DELETE is HELD
  // until the window closes (onExpire) — Undo cancels it with zero Google writes.
  const deleteTask = useCallback(
    (listId: string, taskId: string) => {
      let snapshot: TaskList[] | null = null;
      setState((prev) => {
        snapshot = prev.taskLists;
        return removeTaskFromList(prev, listId, taskId);
      });
      pushActionToast(
        "Task deleted",
        () => {
          setState((s) => ({ ...s, taskLists: snapshot ?? s.taskLists }));
        },
        () => {
          apiDelete(`/tasks/${listId}/${taskId}`).catch((err: Error) => {
            setState((s) => ({
              ...s,
              taskLists: snapshot ?? s.taskLists,
              writeError: `Delete failed: ${err.message}`,
            }));
          });
        },
      );
    },
    [pushActionToast],
  );

  // Set / change / clear an arbitrary due date via the picker. Reuses the g4
  // reschedule endpoint (no new endpoint). Optimistically removes the row, then
  // silently refetches so it re-buckets correctly — including dates with no
  // existing bucket and the Overdue rollup (which drag cannot reach).
  const setDueDate = useCallback(
    (listId: string, taskId: string, dueDate: string | null) => {
      let snapshot: TaskList[] | null = null;
      setState((prev) => {
        snapshot = prev.taskLists;
        return removeTaskFromList(prev, listId, taskId);
      });
      apiPost(`/tasks/${listId}/${taskId}/reschedule`, {
        due_date: dueDate,
        group_id: null,
      })
        .then(() => refetchSilently().catch(() => {}))
        .catch((err: Error) => {
          setState((s) => ({
            ...s,
            taskLists: snapshot ?? s.taskLists,
            writeError: `Reschedule failed: ${err.message}`,
          }));
        });
    },
    [refetchSilently],
  );

  // Rename a list header → PATCH the tasklists resource. Component guards
  // same-value. Optimistic with snapshot-rollback + toast on failure.
  const renameList = useCallback((listId: string, title: string) => {
    const trimmed = title.trim();
    if (!trimmed) return;
    let snapshot: TaskList[] | null = null;
    setState((prev) => {
      snapshot = prev.taskLists;
      return {
        ...prev,
        taskLists: prev.taskLists.map((l) =>
          l.id === listId ? { ...l, title: trimmed } : l,
        ),
      };
    });
    apiPatch(`/lists/${listId}`, { title: trimmed }).catch((err: Error) => {
      setState((s) => ({
        ...s,
        taskLists: snapshot ?? s.taskLists,
        writeError: `Rename failed: ${err.message}`,
      }));
    });
  }, []);

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
  // Optimistic on BOTH sides (g4a fix): remove from the source immediately, and
  // on success insert the moved task into the destination from the move response
  // (its new id) — the g3 insert-from-response pattern, NOT a refetch (the old
  // refetch was the ~2-3s destination lag). Rollback + toast on failure.
  const moveTaskToList = useCallback(
    (listId: string, taskId: string, targetListId: string) => {
      let snapshot: TaskList[] | null = null;
      let moved: Task | null = null;
      setState((prev) => {
        snapshot = prev.taskLists;
        const list = prev.taskLists.find((l) => l.id === listId);
        if (list) {
          for (const b of list.buckets) {
            const found = findTaskInItems(b.items, taskId);
            if (found) {
              moved = found;
              break;
            }
          }
        }
        return removeTaskFromList(prev, listId, taskId);
      });

      apiPost<{ new_task_id: string; rank: number | null }>(
        `/tasks/${listId}/${taskId}/move`,
        { target_list_id: targetListId },
      )
        .then((res) => {
          if (!moved) return;
          const inserted: Task = {
            ...(moved as Task),
            id: res.new_task_id,
            rank: res.rank,
            group_id: null,
          };
          setState((s) => insertMovedTask(s, targetListId, inserted));
        })
        .catch((err: Error) => {
          setState((s) => ({
            ...s,
            taskLists: snapshot ?? s.taskLists,
            writeError: `Move failed: ${err.message}`,
          }));
        });
    },
    [],
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
    createTask,
    editTaskField,
    completeTask,
    deleteTask,
    setDueDate,
    renameList,
    refresh,
    undoActionToast,
  };
}
