import { useEffect, useState } from "react";
import { apiGet, apiPut } from "../api";

// One node in the notes forest. Leaves are Docs, inner nodes are folders. `node_id`
// is a stable uuid the widget owns so the server diff can tell rename from
// delete+add; `drive_id`/`drive_url` are server-materialized (absent for new nodes).
export interface NoteNode {
  node_id: string;
  name: string;
  kind: "folder" | "doc";
  drive_id?: string | null;
  drive_url?: string | null;
  children: NoteNode[];
}

interface NotesIndexResponse {
  nodes: NoteNode[];
}

const uid = () => crypto.randomUUID();

// ── Immutable tree helpers (keyed by node_id) ────────────────────────────────

function renameNode(nodes: NoteNode[], id: string, name: string): NoteNode[] {
  return nodes.map((n) =>
    n.node_id === id
      ? { ...n, name }
      : { ...n, children: renameNode(n.children, id, name) },
  );
}

function removeNode(nodes: NoteNode[], id: string): NoteNode[] {
  return nodes
    .filter((n) => n.node_id !== id)
    .map((n) => ({ ...n, children: removeNode(n.children, id) }));
}

function addChild(
  nodes: NoteNode[],
  parentId: string,
  child: NoteNode,
): NoteNode[] {
  return nodes.map((n) => {
    if (n.node_id !== parentId) {
      return { ...n, children: addChild(n.children, parentId, child) };
    }
    // Adding a child under a Doc converts it to a folder (the old Doc is orphaned
    // in Drive, never written again). The caller has already confirmed the warning.
    return {
      ...n,
      kind: "folder",
      drive_id: n.kind === "doc" ? null : n.drive_id,
      drive_url: n.kind === "doc" ? null : n.drive_url,
      children: [...n.children, child],
    };
  });
}

const newNode = (kind: "folder" | "doc"): NoteNode => ({
  node_id: uid(),
  name: kind === "folder" ? "New folder" : "New Doc",
  kind,
  children: [],
});

export function NotesHierarchy() {
  const [nodes, setNodes] = useState<NoteNode[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  useEffect(() => {
    let alive = true;
    apiGet<NotesIndexResponse>("/settings/notes-index")
      .then((r) => alive && setNodes(r.nodes))
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, []);

  const mutate = (next: NoteNode[]) => {
    setNodes(next);
    setDirty(true);
  };

  const onRename = (id: string, name: string) =>
    mutate(renameNode(nodes, id, name));

  const onDelete = (node: NoteNode) => {
    const warn = node.drive_id
      ? `Remove “${node.name}” from the hierarchy? The Drive ${
          node.kind === "doc" ? "Doc" : "folder"
        } is kept in your Drive — it just stops being written to.`
      : `Remove “${node.name}”?`;
    if (window.confirm(warn)) mutate(removeNode(nodes, node.node_id));
  };

  const onAddChild = (parent: NoteNode, kind: "folder" | "doc") => {
    if (
      parent.kind === "doc" &&
      parent.drive_id &&
      !window.confirm(
        `“${parent.name}” is a Doc. Adding a child turns it into a folder; the ` +
          `existing Doc stays in your Drive but is no longer written to. Continue?`,
      )
    ) {
      return;
    }
    mutate(addChild(nodes, parent.node_id, newNode(kind)));
  };

  const onAddTopLevel = (kind: "folder" | "doc") =>
    mutate([...nodes, newNode(kind)]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const persisted = await apiPut<NotesIndexResponse>(
        "/settings/notes-index",
        {
          nodes,
        },
      );
      setNodes(persisted.nodes);
      setDirty(false);
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 1500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="settings-section">
      <h3>Notes hierarchy</h3>
      <p className="settings-hint">
        Build a tree of folders and Docs in your Drive. Captured notes are
        routed to the best-matching Doc; anything that doesn’t fit goes to the
        default Doc. Folders and Docs are created in Drive when you save.
      </p>
      {error && <p className="settings-error">{error}</p>}

      {nodes.length === 0 ? (
        <p className="settings-hint">No folders or Docs yet.</p>
      ) : (
        <ul className="notes-tree">
          {nodes.map((n) => (
            <NoteRow
              key={n.node_id}
              node={n}
              onRename={onRename}
              onDelete={onDelete}
              onAddChild={onAddChild}
            />
          ))}
        </ul>
      )}

      <div className="settings-add-row">
        <button onClick={() => onAddTopLevel("folder")}>+ Folder</button>
        <button onClick={() => onAddTopLevel("doc")}>+ Doc</button>
      </div>

      <div className="settings-actions">
        <button
          className="settings-save"
          onClick={save}
          disabled={saving || !dirty}
        >
          {saving ? "Saving…" : "Save hierarchy"}
        </button>
        {savedFlash && <span className="settings-saved">Saved ✓</span>}
      </div>
    </section>
  );
}

function NoteRow({
  node,
  onRename,
  onDelete,
  onAddChild,
}: {
  node: NoteNode;
  onRename: (id: string, name: string) => void;
  onDelete: (node: NoteNode) => void;
  onAddChild: (node: NoteNode, kind: "folder" | "doc") => void;
}) {
  return (
    <li className="notes-tree-node">
      <div className="notes-tree-row">
        <span className="notes-tree-kind" aria-hidden>
          {node.kind === "folder" ? "📁" : "📄"}
        </span>
        <input
          className="notes-tree-name"
          value={node.name}
          onChange={(e) => onRename(node.node_id, e.target.value)}
          aria-label="Node name"
        />
        {node.drive_url && (
          <a
            className="notes-tree-link"
            href={node.drive_url}
            target="_blank"
            rel="noreferrer"
            title="Open in Drive"
          >
            ↗
          </a>
        )}
        <span className="notes-tree-actions">
          <button
            title="Add folder inside"
            onClick={() => onAddChild(node, "folder")}
          >
            +📁
          </button>
          <button
            title="Add Doc inside"
            onClick={() => onAddChild(node, "doc")}
          >
            +📄
          </button>
          <button
            className="notes-tree-del"
            title="Remove"
            onClick={() => onDelete(node)}
          >
            ✕
          </button>
        </span>
      </div>
      {node.children.length > 0 && (
        <ul className="notes-tree">
          {node.children.map((c) => (
            <NoteRow
              key={c.node_id}
              node={c}
              onRename={onRename}
              onDelete={onDelete}
              onAddChild={onAddChild}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
