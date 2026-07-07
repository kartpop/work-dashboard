// Plain-textarea bullet ergonomics (goal 7). No rich-text framework: the value is
// exactly what gets captured. "Bullets" are literal `- ` prefixes; indentation is
// two spaces per level. Every function is pure over an editor snapshot so the
// keydown handler stays a thin dispatcher.

export interface EditorState {
  value: string;
  selectionStart: number;
  selectionEnd: number;
}

const INDENT = "  "; // two spaces per level
const BULLET_RE = /^(\s*)- (.*)$/; // indent, marker, content

// The start index of the line containing `pos`.
function lineStartOf(value: string, pos: number): number {
  return value.lastIndexOf("\n", pos - 1) + 1;
}

/**
 * Enter on a bullet line continues the list at the same indent; Enter on an
 * *empty* bullet exits the list (removes the marker, no new line — Docs behavior);
 * Enter on a non-bullet line returns null so the browser inserts a plain newline.
 * Plain Enter NEVER submits (the caller only submits on Shift/Cmd/Ctrl+Enter).
 */
export function handleEnter(s: EditorState): EditorState | null {
  const { value, selectionStart, selectionEnd } = s;
  const left = value.slice(0, selectionStart);
  const right = value.slice(selectionEnd);
  const lineStart = lineStartOf(value, selectionStart);
  const lineToCaret = value.slice(lineStart, selectionStart);

  const m = BULLET_RE.exec(lineToCaret);
  if (!m) return null; // not a bullet line → plain newline (browser default)

  const [, indent, content] = m;
  if (content.length === 0) {
    // Empty bullet → exit the list: drop the "indent- " marker, keep the caret on
    // the now-blank line (no extra newline inserted).
    return {
      value: value.slice(0, lineStart) + right,
      selectionStart: lineStart,
      selectionEnd: lineStart,
    };
  }

  const insert = `\n${indent}- `;
  return {
    value: left + insert + right,
    selectionStart: selectionStart + insert.length,
    selectionEnd: selectionStart + insert.length,
  };
}

/** Tab: indent the current line one level (two spaces at the line start). */
export function indentLine(s: EditorState): EditorState {
  const { value, selectionStart, selectionEnd } = s;
  const lineStart = lineStartOf(value, selectionStart);
  return {
    value: value.slice(0, lineStart) + INDENT + value.slice(lineStart),
    selectionStart: selectionStart + INDENT.length,
    selectionEnd: selectionEnd + INDENT.length,
  };
}

/**
 * Shift+Tab: outdent the current line one level. Removes up to two leading spaces;
 * a no-op at depth 0. The caret shifts left by however many spaces were removed.
 */
export function outdentLine(s: EditorState): EditorState {
  const { value, selectionStart, selectionEnd } = s;
  const lineStart = lineStartOf(value, selectionStart);
  let removable = 0;
  while (removable < INDENT.length && value[lineStart + removable] === " ") {
    removable += 1;
  }
  if (removable === 0) return s; // already at depth 0

  const shift = (pos: number) => Math.max(lineStart, pos - removable);
  return {
    value: value.slice(0, lineStart) + value.slice(lineStart + removable),
    selectionStart: shift(selectionStart),
    selectionEnd: shift(selectionEnd),
  };
}
