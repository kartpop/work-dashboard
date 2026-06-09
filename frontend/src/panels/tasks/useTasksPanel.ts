import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPatch } from "../../api";

export interface Task {
  id: string;
  title: string;
  status: string;
  due: string | null;
  notes: string | null;
  rank: number | null;
  priority: number | null;
}

export interface DateGroup {
  label: string;
  tasks: Task[];
}

export interface TaskList {
  id: string;
  title: string;
  groups: DateGroup[];
}

interface TasksResponse {
  task_lists: TaskList[];
}

interface TasksPanelState {
  taskLists: TaskList[];
  isLoading: boolean;
  error: string | null;
}

export function useTasksPanel() {
  const [state, setState] = useState<TasksPanelState>({
    taskLists: [],
    isLoading: true,
    error: null,
  });

  const load = useCallback(() => {
    setState((s) => ({ ...s, isLoading: true, error: null }));
    let cancelled = false;
    apiGet<TasksResponse>("/tasks?view=grouped")
      .then((data) => {
        if (!cancelled)
          setState({ taskLists: data.task_lists, isLoading: false, error: null });
      })
      .catch((err: Error) => {
        if (!cancelled)
          setState({ taskLists: [], isLoading: false, error: err.message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(load, [load]);

  const setPriority = useCallback(
    async (tasklistId: string, taskId: string, priority: number) => {
      await apiPatch(`/tasks/${tasklistId}/${taskId}/overlay`, { priority });
      load();
    },
    [load],
  );

  // Applies an optimistic reorder in local state and persists a single rank write.
  // newRank is computed by the component from its current group tasks.
  const reorderTask = useCallback(
    (
      tasklistId: string,
      taskId: string,
      groupLabel: string,
      fromIndex: number,
      toIndex: number,
      newRank: number,
    ) => {
      setState((prev) => {
        const lists = prev.taskLists.map((list) => {
          if (list.id !== tasklistId) return list;
          const groups = list.groups.map((g) => {
            if (g.label !== groupLabel) return g;
            const tasks = [...g.tasks];
            const [moved] = tasks.splice(fromIndex, 1);
            tasks.splice(toIndex, 0, moved);
            return { ...g, tasks };
          });
          return { ...list, groups };
        });
        return { ...prev, taskLists: lists };
      });
      apiPatch(`/tasks/${tasklistId}/${taskId}/overlay`, { rank: newRank }).catch(() => {});
    },
    [],
  );

  return { ...state, setPriority, reorderTask };
}
