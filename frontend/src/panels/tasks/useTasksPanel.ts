import { useEffect, useState } from "react";
import { apiGet } from "../../api";

export interface Task {
  id: string;
  title: string;
  status: string;
  due: string | null;
  notes: string | null;
}

export interface TaskList {
  id: string;
  title: string;
  tasks: Task[];
}

interface TasksResponse {
  task_lists: TaskList[];
}

interface TasksPanelState {
  taskLists: TaskList[];
  isLoading: boolean;
  error: string | null;
}

export function useTasksPanel(): TasksPanelState {
  const [state, setState] = useState<TasksPanelState>({
    taskLists: [],
    isLoading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

    apiGet<TasksResponse>("/tasks")
      .then((data) => {
        if (!cancelled) setState({ taskLists: data.task_lists, isLoading: false, error: null });
      })
      .catch((err: Error) => {
        if (!cancelled) setState({ taskLists: [], isLoading: false, error: err.message });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
