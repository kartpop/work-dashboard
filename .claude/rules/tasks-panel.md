---
paths: ["frontend/src/panels/tasks/**"]
---

# Tasks panel — DnD architecture and learnings

This file captures the design decisions and bugs encountered while building the drag-and-drop
layer in `TasksPanel.tsx` / `useTasksPanel.ts`. Read it before touching either file.

## Architecture snapshot

The tasks panel uses **@dnd-kit** with a **flat SortableContext per bucket**. All sortable
IDs — standalone task IDs, group header IDs (`group-{id}`), and task IDs nested inside groups
— live in a single `SortableContext items` array. `GroupContainer` and `SortableTask` both
call `useSortable`; they're all children of the same context.

The alternative (nested `DndContext` per group) was rejected because dnd-kit does not support
dragging an item between two nested contexts cleanly.

### ID encoding
| Entity | Sortable ID |
|---|---|
| Standalone task | `task.id` (Google Tasks string) |
| Group header | `group-{group.id}` (prefixed number) |
| Task inside group | `task.id` (same string — no prefix) |

`activeId.startsWith("group-")` is the only way `handleDragEnd` distinguishes a group drag
from a task drag. Do not rename this prefix without updating every reference.

### Container resolution
`findContainer(id, items)` maps a sortable ID to `{type:"bucket"}` (top-level standalone) or
`{type:"group", groupId:N}` (inside a group). It is NOT called for group-prefixed IDs — those
are handled before `findContainer` in `handleDragEnd`.

### State ownership
All rank arithmetic happens in `TasksPanel.tsx` before calling the hook. `useTasksPanel.ts`
receives the pre-computed `newRank` and simply applies it. Never compute ranks inside the hook.

---

## Goal 4 — cross-bucket reschedule & move-to-list (first Google writes)

### One DndContext per LIST (was: per bucket)
To drag a task *between* date-buckets, the `<DndContext>` moved up from `BucketSection` to
`TaskListSection` — it now wraps every bucket of one list. Each bucket keeps its own
`<SortableContext>`; sortable ids (`task.id`, `group-{id}`) are globally unique so they don't
collide across buckets in the shared context. Each bucket's `<ul>` is also a
`useDroppable({ id: "bucket:"+bucket.key })` (class `.bucket-droppable`, min-height) so a drop in
a bucket's open area resolves to that bucket even when it has no item under the pointer.
Cross-**list** drag is still unsupported (each list is its own DndContext) — moving between lists
is the menu's job, not drag.

### `handleDragEnd` now lives at list level
1. `findBucketForId(buckets, activeId)` → source bucket; the dest bucket comes from `overId`
   (`bucket:{key}` → by key, else `findBucketForId(overId)`).
2. **Group drag:** groups never span buckets — if dest bucket ≠ source bucket, `return`; else the
   g3 group-reorder runs (with `bucket:` open-area resolving to the bucket end).
3. **Task drag, dest bucket ≠ source bucket → RESCHEDULE branch:**
   - `dueDate = destBucket.key === "NO_DATE" ? null : destBucket.key`.
   - **Destination group resolution:** drop on a `group-{id}` header or on a task nested in a dest
     group → `destGroupId = that group`; drop on the bucket open area or a standalone task →
     `destGroupId = null`. (Same rule as a within-bucket drop, just evaluated in the dest bucket.)
   - `destIndex` + `newRank` are computed against the **destination** container with the task
     hypothetically inserted (`computeGroupTaskRank` for a dest group, `computeMidpointRank` for the
     dest bucket) — identical math to g3, different container.
   - Calls `rescheduleTask(...)`.
4. **Task drag, same bucket → unchanged g3 paths** (reorder / move-into-group / ungroup), overlay
   PATCH only, no Google write. All five bug-fixes below still apply.

### Snapshot-rollback pattern (Google writes are NOT fire-and-forget)
Unlike overlay PATCHes (optimistic, errors swallowed), `rescheduleTask` and `moveTaskToList`:
- capture `snapshotRef.current = prev.taskLists` **inside** the `setState` updater (so it's the
  latest committed state) *before* applying the optimistic transform;
- fire exactly one `apiPost`;
- on `.catch`, restore `taskLists` from the snapshot **and** set `writeError` (the `.toast`). Never
  swallow a Google-write error.
`rescheduleTask` moves the row across two buckets in one transform (`moveTaskAcrossBuckets`):
remove from source (with the same group auto-remove as `moveTask` — an emptied source group is
dropped from local state), set `due`/`group_id`/`rank`, insert into the dest bucket at `destIndex`.
`moveTaskToList` optimistically removes the task from the source list, POSTs, then on success
**silently refetches** (`refetchSilently`, no `isLoading` flip) so the task reappears in its
destination correctly bucketed with the server's new task id; a refetch failure is swallowed (the
move already happened server-side) — only a *move* failure rolls back.

---

## Bug log — what broke, why, and what fixed it

### 1. Groups can only be dragged once

**Symptom:** First group reorder works; every subsequent attempt leaves the group in place.

**Root cause:** After the first drag the flat SortableContext contains task IDs that are
*inside* groups. When dragging a group on the second attempt, `closestCenter` frequently
reports `over.id` as one of those nested task IDs instead of the adjacent group's header ID.
`findBucketItemIndex(overId, items)` searches only top-level bucket items — it returns `-1`
for nested task IDs, causing an early `return`.

**Fix:** In the group-reorder branch of `handleDragEnd`, resolve `overId` before calling
`findBucketItemIndex`. If `overId` is not a group-prefixed ID, call `findContainer` on it; if
that returns `{type:"group", groupId:N}`, replace `overId` with `"group-N"`.

```ts
let resolvedOverId = overId;
if (!overId.startsWith("group-")) {
  const overContainer = findContainer(overId, items);
  if (overContainer?.type === "group")
    resolvedOverId = `group-${overContainer.groupId}`;
}
const toIndex = findBucketItemIndex(resolvedOverId, items);
```

---

### 2. Dragging an item down requires n+1 steps

**Symptom:** To move item A one position below item B, the user must drag all the way past B
to hover over item C (the item after B) and then drop.

**Root cause:** The original code used `adj = toIdx > fromIdx ? toIdx - 1 : toIdx` before
splicing. Tracing through: drag A (idx 0) over B (idx 1) → `adj = 0` → splice A back at 0 →
no change. The adjustment was an incorrect attempt to compensate for the splice shifting items.

**Fix:** Use `toIdx` directly (arrayMove semantics). After `splice(fromIdx, 1)`, insert at
`toIdx` without adjustment. This matches dnd-kit's own `arrayMove` helper.

```ts
const [moved] = reordered.splice(fromIdx, 1);
reordered.splice(toIdx, 0, moved);                 // no adj
const newRank = computeMidpointRank(reordered, toIdx);
```

Applied in both the bucket-level task reorder path and the group-internal task reorder path.

---

### 3. Cannot drag tasks into groups

**Symptom:** Dragging a standalone task over a group and releasing does nothing (the task
stays standalone). The `handleDragEnd` logic for cross-container moves is correct; the problem
is earlier — collision detection never reports a group item as `over`.

**Root cause:** `closestCenter` computes distance from the drag *center* to the *center* of
every registered rect. When a standalone task is dragged near the top edge of a group, the
standalone task sitting immediately above the group has a center that is geometrically closer
to the cursor than any item inside the group. `over.id` resolves to that standalone task;
`handleDragEnd` sees a same-container reorder; nothing changes.

**Fix:** Replace `closestCenter` with a custom collision strategy:

```ts
const collisionDetection: CollisionDetection = (args) => {
  const hits = pointerWithin(args);          // pointer physically inside a rect?
  return hits.length > 0 ? hits : closestCenter(args);
};
```

`pointerWithin` checks whether the *pointer position* is inside a registered DOM rect. When
the pointer enters the group container div or any task `li` inside it, the group/task is
returned immediately — no center-distance race. `closestCenter` is used only as a fallback
for inter-item gaps where the pointer is outside every rect.

---

### 4. Empty groups have no drop target

**Symptom:** An empty group cannot receive a dragged task because `pointerWithin` (and
`closestCenter`) find no sortable rect inside the group body.

**Root cause:** `.group-tasks` (the `ul` inside the group container) has zero height when
empty, so the group-container div's only meaningful rect area is the header bar — a small
target.

**Fix:** `min-height: 32px` on `.group-tasks` ensures empty groups always present a drag
surface.

---

### 5. Group creation triggers a full data reload

**Symptom:** Creating a group shows a 2-3s loading spinner while the task list refetches from
the Google API.

**Root cause:** `createGroup` called `load()` after the POST, intending to pick up the
server-assigned `id`. The POST response already contains the full group object.

**Fix:** Construct a typed `Group` from the POST response and insert it directly via
`setState`. No network round-trip needed.

```ts
const data = await apiPost<{ id: number; name: string; rank: number | null }>(...);
const grp: Group = { type: "group", id: data.id, name: data.name, rank: data.rank, items: [] };
setState((prev) => updateBucket(prev, tasklistId, bucketKey, (items) => [...items, grp]));
```

---

## Known rough edges (as of goal 3)

The following are not fixed yet. Track them before starting DnD-related work:

- **Drag visual feedback is poor.** There is no `DragOverlay` component. The dragged item is
  dimmed in-place (`opacity: 0.4`) while a ghost follows the cursor. dnd-kit recommends a
  `DragOverlay` for smoother UX; the current approach can cause confusing visual during
  cross-container moves.
- **`verticalListSortingStrategy` shifts all items** during a drag, applying CSS transforms.
  The translated visual positions don't match the DOM rects used for collision. This can make
  it hard to precisely target a drop position, especially for groups with many items.
- **Dropping a standalone task "on" a group** always appends to the end (via the
  `overId.startsWith("group-")` → `destIndexInContainer = grp.items.length` path). There is
  no way to insert at a specific position except by hovering over an existing task inside the
  group. When dropping on the group header or body below the last task, the item goes to the
  end — this is usually fine but can surprise users.
- **Drag to ungroup** (dragging a task from inside a group to standalone) works but the
  insertion index at the bucket level is approximate; it snaps to the nearest standalone task's
  position rather than a precise between-items slot.
- **No touch / mobile support.** `PointerSensor` handles mouse; adding `TouchSensor` from
  `@dnd-kit/core` is the path to mobile drag.
- **Rank precision degrades** over many reorders. Ranks are midpoints; after many operations
  they can converge. A periodic re-normalisation pass (e.g. reset ranks to 1000-spaced
  integers on every full load) would prevent this.

---

## Rank computation rules

Both `computeMidpointRank` (bucket-level items) and `computeGroupTaskRank` (tasks inside a
group) work on the *already-reordered* array: splice the item out, splice it in at `toIdx`,
then compute midpoint between `reordered[toIdx-1]` and `reordered[toIdx+1]`. Items with
`rank === null` are treated as `(index + 1) * 1000` for comparison purposes.

`toIdx` is always the final position in the reordered array, equivalent to dnd-kit's
`arrayMove(items, fromIdx, toIdx)`. **Never apply a `toIdx - 1` adjustment for downward
drags** — that was the source of bug #2 above.
