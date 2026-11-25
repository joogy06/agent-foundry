# Keyboard-first layout, command palette and type-ahead

Reference for `operator-console-ux` §6. React + TypeScript sketches.

## Contents

- 1. Shortcut map conventions
- 2. A scoped shortcut hook
- 3. Command palette
- 4. Mention and #tag type-ahead (ARIA combobox)
- 5. Focus management in a list-detail shell
- 6. Library notes (dated)

## 1. Shortcut map conventions

| Keys | Action | Scope |
|---|---|---|
| `Ctrl+K` / `Cmd+K` | Command palette | Global (works inside inputs; it has a modifier) |
| `?` | Shortcut help overlay | Global, not inside inputs |
| `j` / `k`, `↓` / `↑` | Next / previous row | List region |
| `Enter` | Open selected | List region |
| `Esc` | Close the innermost layer (dialog, palette, detail) | Global |
| `g` then a letter | Go to a section (`g q` queue, `g b` board) | Global, not inside inputs |
| `e`, `a`, `r` … | Row verbs (archive, approve…, reject…) | List region; consequential verbs open the guard, never act directly |

Rules:

- **Single printable-key shortcuts** must be scoped to a focused region or be turn-off-able or
  remappable (WCAG 2.2 SC 2.1.4 Character Key Shortcuts). Never let them fire from `input`,
  `textarea`, `select` or `contenteditable`.
- Do not take keys the browser or assistive technology uses (`Ctrl+L`, `Ctrl+T`, `Ctrl+W`, `F6`,
  screen-reader modifier combinations). Test with a screen reader running: in browse mode it
  consumes single letters before the page sees them.
- Show shortcuts in menus and tooltips (`aria-keyshortcuts` on the control) so they are
  discoverable without the help overlay.

## 2. A scoped shortcut hook

```ts
const EDITABLE = "input, textarea, select, [contenteditable=''], [contenteditable='true']";

export function useShortcut(
  key: string,
  handler: (e: KeyboardEvent) => void,
  opts: { scope?: React.RefObject<HTMLElement>; allowInEditable?: boolean; enabled?: boolean } = {},
) {
  useEffect(() => {
    if (opts.enabled === false) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing || e.repeat) return;                       // IME and key-repeat safety
      const t = e.target as HTMLElement | null;
      if (!opts.allowInEditable && (t?.isContentEditable || t?.closest(EDITABLE))) return;  // covers plaintext-only
      if (opts.scope?.current && !opts.scope.current.contains(t)) return;
      if (matches(e, key)) { e.preventDefault(); handler(e); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);   // cleanup (modern-frontend rule)
  }, [key, handler, opts.enabled, opts.allowInEditable, opts.scope]);
}
```

`matches` normalises `mod` to `metaKey` on macOS and `ctrlKey` elsewhere, and compares `e.key`
(the character) for printable keys and `e.code` only for layout-independent keys.

## 3. Command palette

- Opens on `Ctrl/Cmd+K`, as a modal dialog with a combobox input and a listbox of results
  (the pattern in §4 applies).
- Results are **typed**: navigation targets, objects (by name or id), and actions. Each action
  row shows its shortcut.
- Actions run through the same code path as their buttons: a destructive action from the palette
  still opens its confirm or step-up. The palette is a faster route to a decision, not a bypass.
- Server search results are debounced (150–250 ms), cancelled on new input (an `AbortController`
  or TanStack Query's signal) and marked "searching…" so an empty list is not mistaken for "no
  match".
- Recent and pinned commands first when the input is empty.

## 4. Mention and #tag type-ahead (ARIA combobox)

Follow the WAI-ARIA Authoring Practices combobox pattern with a listbox popup:

| Element | Attributes |
|---|---|
| The text field | `role="combobox"`, `aria-expanded`, `aria-controls` = listbox id, `aria-autocomplete="list"`, `aria-activedescendant` = id of the highlighted option |
| The popup | `role="listbox"`, each option `role="option"` with a stable `id` and `aria-selected` on the highlighted one |
| Keys | `↓`/`↑` move the highlight (focus stays in the field), `Enter` or `Tab` inserts, `Esc` closes without inserting |

Mention specifics:

- Trigger on `@` (people, agents) or `#` (tags, items) only at a word boundary; the query is the
  text from the trigger to the caret.
- Insert a **token**, not plain text: store the entity id (`{type: "mention", id: "u_42"}`) and
  render the display name, so renames do not break references and the server can authorise
  notifications.
- The server validates every mention and tag id; the client list is a suggestion, never an
  authorisation.
- Announce the result count through a polite live region ("5 suggestions") when the list opens.
- In a plain `<textarea>` this pattern is manageable by hand; in a rich-text editor
  (`contenteditable`) use the editor's mention or type-ahead extension rather than hand-rolling
  caret and selection logic (see §6).

## 5. Focus management in a list-detail shell

- One **roving tab stop** in the list (`tabindex=0` on the selected row, `-1` on the others), or
  `aria-activedescendant` on the list container; arrows move within, `Tab` leaves the list.
- Opening the detail pane does not steal focus from the list unless the operator pressed `Enter`;
  `Esc` in the detail returns focus to the row it came from.
- When the selected row disappears (approved, archived, filtered out by a push update), move
  selection and focus to the next row, or to the empty-state heading when none remain.
- Sticky headers, toolbars and toasts must not hide the focused row (SC 2.4.11): use
  `scroll-margin` on rows equal to the sticky header height.

## 6. Library notes (dated)

Verified 2026-10-26; check the registry before adopting, and apply the minimal-dependency policy
in `modern-frontend` (supply-chain reference) — a shortcut hook and a combobox are small enough to
own.

- **Command palette:** `cmdk` 1.1.1 (last release 2025-03, not archived, slow-moving) is the
  common choice; it does not bind `Cmd/Ctrl+K` itself — register the shortcut and call
  `preventDefault` (browsers use `Ctrl+K` for search on Windows and Linux). `kbar` 1.0.0 (2026-08)
  is an alternative.
- **Rich-text mentions:** Tiptap's Mention extension and Lexical's type-ahead menu plugin provide
  the caret tracking and popup positioning; both still need the ARIA contract above checked.
- **Headless primitives:** a headless component library with an accessible combobox (for example
  React Aria's `useComboBox`) saves the ARIA wiring when you do not want to own it.
