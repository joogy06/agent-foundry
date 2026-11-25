# Task boards (kanban) with drag and drop

Reference for `operator-console-ux` §7. React + TypeScript.

## Contents

- 1. Library choice (dated)
- 2. Data model: status + rank + version
- 3. Board with @dnd-kit/react
- 4. Keyboard dragging and screen-reader announcements
- 5. The single-pointer alternative: "Move to…"
- 6. Server move contract and conflicts
- 7. Performance on large boards
- 8. Tests

## 1. Library choice (dated)

Versions read from the npm registry on 2026-10-26.

| Option | State on 2026-10-26 | Accessibility | Pick when |
|---|---|---|---|
| `@dnd-kit/react` (+ `@dnd-kit/dom`, `@dnd-kit/helpers`) | `0.5.1`, published 2026-10-15; the actively developed line of dnd-kit, still **pre-1.0** | Keyboard sensor and an Accessibility plugin (live-region announcements, screen-reader instructions) in the default preset | New boards. Pin the exact version: minors can break before 1.0 |
| `@dnd-kit/core` + `@dnd-kit/sortable` | `6.3.1` / `10.0.0`, last published 2024-12; stable and very widely used, no releases since | `KeyboardSensor` with `sortableKeyboardCoordinates`, `accessibility.announcements` and `screenReaderInstructions` props | An existing codebase already on it, or you want zero API churn |
| `@atlaskit/pragmatic-drag-and-drop` | `4.0.0`, 2026-09 | No accessible controls built in; Atlassian's guidelines: an action-menu alternative on each item, live-region announcements of old and new position, focus returned to the trigger | Very large boards or drag between windows and from outside the browser |
| `react-beautiful-dnd` | Deprecated on npm; repository archived 2025-08-18 | — | Never for new work; migrate (Atlassian points to Pragmatic drag and drop; `@hello-pangea/dnd` is a community fork) |

Whatever you choose, keep the library behind a small board adapter (`onMove(cardId, toColumn,
toIndex)`), so the move contract (§6) and the "Move to…" menu (§5) do not depend on it.

## 2. Data model: status + rank + version

```ts
type Card = {
  id: string;
  status: "todo" | "doing" | "review" | "done";   // the column
  rank: string;          // lexicographic fractional index ("a0", "a0V", "a1")
  version: number;       // optimistic-concurrency token
  title: string;
  assignee?: string;
  blocked?: boolean;
};
```

- **Fractional ranks** (lexicographic strings between neighbours, e.g. the `fractional-indexing`
  algorithm) let one move write one row. Integer positions force renumbering the column and turn
  every move into a multi-row conflict.
- The server sorts by `(status, rank)`; the client never trusts its own order after a refetch.
- Rebalance ranks server-side when strings get long; that is a maintenance job, not a move.

## 3. Board with @dnd-kit/react

```tsx
import { DragDropProvider } from "@dnd-kit/react";
import { useSortable } from "@dnd-kit/react/sortable";
import { move } from "@dnd-kit/helpers";

type Columns = Record<Card["status"], string[]>;     // column -> ordered card ids

function Board({ cards }: { cards: Card[] }) {
  const server = useMemo(() => toColumns(cards), [cards]);
  const [columns, setColumns] = useState<Columns>(server);
  const [dragging, setDragging] = useState(false);
  useEffect(() => { if (!dragging) setColumns(server); }, [server, dragging]);  // server wins, but never mid-drag
  const moveCard = useMoveCard();                      // mutation, §6

  return (
    <DragDropProvider
      onDragStart={() => setDragging(true)}
      onDragOver={(event) => setColumns((cols) => move(cols, event))}   // live preview only
      onDragEnd={(event) => {
        setDragging(false);                                             // pending push updates apply now
        if (event.canceled) { setColumns(server); return; }
        const id = String(event.operation.source?.id);
        const { status, index } = locate(columns, id);
        const col = columns[status];
        moveCard.mutate({ id, status, after: col[index - 1] ?? null, before: col[index + 1] ?? null },
                        { onError: () => setColumns(server) });         // neighbours, not an index (§6)
      }}
    >
      {(Object.keys(columns) as Card["status"][]).map((status) => (
        <Column key={status} status={status} ids={columns[status]} cardsById={byId(cards)} />
      ))}
    </DragDropProvider>
  );
}

function SortableCard({ card, index, status }: { card: Card; index: number; status: string }) {
  const { ref, handleRef, isDragging } = useSortable({ id: card.id, index, group: status, type: "card",
                                                       accept: "card" });
  return (
    <li ref={ref} data-dragging={isDragging || undefined}>
      <button ref={handleRef} aria-label={`Move ${card.title}`} className="drag-handle">⠿</button>
      <span>{card.title}</span>
      <MoveToMenu card={card} />                {/* §5 */}
    </li>
  );
}
```

Notes:

- Columns also need to accept drops when empty (`useDroppable` on the column with `type`/`accept`
  set to `"card"`).
- Use a **drag handle** that is a real `<button>`, so the card's other controls (links, menu) keep
  working and the keyboard sensor starts from a focusable element.
- Pre-1.0 API: check names against the installed version's docs before copying.

## 4. Keyboard dragging and screen-reader announcements

Keyboard contract (both dnd-kit lines implement it through their keyboard sensor):

| Key | Effect |
|---|---|
| `Space` / `Enter` on the handle | Pick up |
| Arrow keys | Move within a column and across columns |
| `Space` / `Enter` | Drop |
| `Esc` | Cancel and return to the start position |

Announcements must use **card titles and column names**, not ids, and state the position:

```tsx
import { Accessibility, defaultPreset } from "@dnd-kit/dom";

const announcements = {
  dragstart: ({ operation }) => `Picked up ${title(operation.source)}. In ${col(operation.source)}, position ${pos(operation.source)}.`,
  dragover: ({ operation }) => operation.target
    ? `Over ${col(operation.target)}, position ${pos(operation.target)}.` : undefined,
  dragend: ({ operation, canceled }) => canceled
    ? `Move cancelled. ${title(operation.source)} returned to ${startCol(operation.source)}.`
    : `Dropped ${title(operation.source)} in ${col(operation.target)}, position ${pos(operation.target)}.`,
};

<DragDropProvider
  plugins={[...defaultPreset.plugins.filter((p) => p !== Accessibility),
            Accessibility.configure({
              announcements,
              screenReaderInstructions: { draggable:
                "To move this card, press space or enter. Use arrow keys to move, space or enter to drop, escape to cancel." },
            })]}
>
```

With the legacy line, pass the same strings via
`<DndContext accessibility={{ announcements, screenReaderInstructions }}>` and use
`KeyboardSensor` with `sortableKeyboardCoordinates`.

After the server confirms or rejects the move, announce the outcome in the console's status live
region ("Saved" is not needed; "Move failed: card was changed by Ana, restored" is).

## 5. The single-pointer alternative: "Move to…"

WCAG 2.2 SC 2.5.7 (AA): functionality that uses dragging must also work with a single pointer
without dragging. A menu on each card meets it and is also the fastest path for keyboard users
moving a card several columns:

```tsx
function MoveToMenu({ card }: { card: Card }) {
  const moveCard = useMoveCard();
  return (
    <Menu label={`Actions for ${card.title}`}>
      <MenuGroup label="Move to">
        {STATUSES.filter((s) => s !== card.status).map((s) => (
          <MenuItem key={s} onSelect={() => moveCard.mutate({ id: card.id, status: s, after: null, before: firstId(s) })}>
            {LABEL[s]}
          </MenuItem>
        ))}
      </MenuGroup>
      <MenuItem onSelect={() => moveWithinColumn(card, -1)}>Move up</MenuItem>
      <MenuItem onSelect={() => moveWithinColumn(card, +1)}>Move down</MenuItem>
    </Menu>
  );
}
```

## 6. Server move contract and conflicts

```text
PATCH /api/cards/{id}/position
{ "status": "review", "after": "<card id or null>", "before": "<card id or null>", "expectedVersion": 7 }
-> 200 { card }                       server computes the rank between the neighbours
-> 409 { current }                    version mismatch or neighbours moved: client restores server order
-> 422 { reason: "wip_limit" }        the column is full: client restores and announces the reason
```

- Send **neighbours**, not a numeric index: the server computes the rank, so a concurrent move by
  another operator cannot produce duplicate ranks.
- Moves that cause consequential effects (moving to "deploy", "approved", "done" when that
  notifies someone) are **not** previewed as done: the card shows a pending state in the target
  column until the server answers, and the move may require the confirm or step-up from the
  destructive-action ladder.
- Push updates (SSE) for cards in a column the operator is dragging into are applied after the
  drop, not during it, to keep the drop target stable.

## 7. Performance on large boards

- Virtualise long columns, but keep the dragged card and the drop target mounted.
- Memoise card components on `card.id + card.version` so a push update re-renders one card.
- Very large boards (thousands of cards): prefer filters, swimlanes and a list view over one
  enormous board; dragging across a virtualised list that scrolls is hard for everyone.

## 8. Tests

- Keyboard: pick up, move across two columns, drop; assert order and the announcement text.
- "Move to…" menu reaches every column without a drag.
- Conflict: server returns 409; the card returns to the server position and the failure is
  announced.
- Cancel with `Esc` restores the original position with no request sent.
