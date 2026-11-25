# Approvals and destructive-action guards

Reference for `operator-console-ux` §2 and §3. React + TypeScript sketches; the contracts are
framework-neutral.

## Contents

- 1. The approval request contract
- 2. Approval card sketch
- 3. Confirm dialogs that still protect
- 4. Typed confirmation
- 5. Undo windows (server-side)
- 6. Toasts and status messages (accessibility)
- 7. Concurrency: two operators, one item
- 8. Illustrative case

## 1. The approval request contract

The server owns the canonical description of what will happen. The client renders it and sends
back a decision bound to it.

```ts
// GET /api/approvals/{id}  (server-built; the UI never reconstructs scope)
type ApprovalView = {
  id: string;
  version: number;            // or an ETag; bumps on any change to scope or state
  action: string;             // "grant", "disable", "deploy", ...
  summary: string;            // one line, server-rendered: "Grant deploy on runner-7 for 2 h"
  scope: { resource: string; change: string; reversible: boolean }[];
  requestedBy: string;
  requestedAt: string;        // ISO 8601
  expiresAt: string;
  riskFlags: { code: string; text: string; source: string }[];  // from the policy owner
  stepUpRequired: boolean;    // server decides; the UI does not
  state: "pending" | "approving" | "approved" | "rejected" | "failed" | "expired" | "unknown";
};

// POST /api/approvals/{id}/decision
type Decision = {
  decision: "approve" | "reject";
  version: number;            // must equal the version rendered; else 409 + fresh view
  reason?: string;            // required for reject
  idempotencyKey: string;     // one per decision attempt; replays return the first result
  stepUp?: { ceremonyId: string; assertion: unknown };  // bound to this approval (spa-auth-webauthn)
};
```

Server answers: `200` with the new state, `409` (version changed: re-render and ask again), `410`
(expired), `428` (step-up required: run the ceremony and resend), `202` when the effect is
asynchronous (state `approving`; the UI follows it by push or polling until terminal).

## 2. Approval card sketch

```tsx
function ApprovalCard({ view }: { view: ApprovalView }) {
  const decide = useDecision(view.id);            // TanStack Query mutation, no optimistic update
  const [confirming, setConfirming] = useState(false);
  const expired = useNow() > Date.parse(view.expiresAt);

  return (
    <article aria-labelledby={`appr-${view.id}`}>
      <h3 id={`appr-${view.id}`}>{view.summary}</h3>
      <p>Requested by {view.requestedBy}, <RelativeTime iso={view.requestedAt} />,
         expires <RelativeTime iso={view.expiresAt} /></p>
      <ScopeList scope={view.scope} />
      <RiskFlags flags={view.riskFlags} />
      <StateBadge state={decide.isPending ? "approving" : view.state} />
      {decide.error && <DecisionError error={decide.error} />}   {/* 409 re-renders fresh view */}
      <div role="group" aria-label="Decision">
        <button type="button" disabled={expired || decide.isPending}
                onClick={() => setConfirming(true)}>Approve…</button>
        <RejectWithReason id={view.id} version={view.version} disabled={expired} />
      </div>
      {confirming && (
        <ConfirmApprove view={view}
          onConfirm={(stepUp) => decide.mutate({ decision: "approve", version: view.version,
                                                 idempotencyKey: crypto.randomUUID(), stepUp })}
          onCancel={() => setConfirming(false)} />
      )}
    </article>
  );
}
```

Rules the sketch encodes:

- Neither decision button has `autoFocus`; `Enter` in a surrounding form never submits a decision.
- The button label ends in an ellipsis because it opens a further step.
- `ConfirmApprove` restates `view.summary` and scope, and when `view.stepUpRequired` it runs the
  WebAuthn step-up ceremony instead of showing a plain "Confirm" button.
- The idempotency key is created per attempt and reused on a network retry of the same attempt.
- After success the card shows the server state; it is removed from the queue by the next push or
  refetch, not by the click handler.

## 3. Confirm dialogs that still protect

- Use the native `<dialog>` element with `showModal()` (focus trap, `Esc`, inert background) or a
  library dialog that does the same.
- Title is a question naming the target: "Disable runner-7?". Body states the consequence and
  whether it can be undone. Buttons: the verb ("Disable runner-7") and "Cancel".
- Initial focus on the **least destructive** control (Cancel) for irreversible actions.
- Never stack two confirm dialogs; never confirm inside a toast.
- If the same confirm appears more than a few times a day to the same operator, it is guarding a
  reversible action: replace it with undo.

## 4. Typed confirmation

For irreversible, high-blast-radius actions (purge, revoke everything, transfer ownership):

- The operator types the **target's name** (not "DELETE"); the action button enables only on an
  exact match. Paste is allowed (the protection is reading the name, not typing speed).
- The server re-checks the typed value; the UI check is a convenience.
- Pair it with step-up re-authentication when the action changes who can do what.

## 5. Undo windows (server-side)

```text
client: POST /api/jobs/42/archive            -> 202 { undoToken, undoUntil }
server: job 42 state = archived (reversible) ; hard effects deferred until undoUntil
client: toast "Archived job 42. [Undo]" (focusable, stays until undoUntil or dismissal)
client: POST /api/undo/{undoToken}           -> 200 state restored  (or 410 if past undoUntil)
```

- The window lives on the server (`undoUntil`); the client toast is only a shortcut to it.
- Keep the undo reachable after the toast closes (an activity log with "Undo" while the window is
  open).
- Window length: at least 10 s for a toast; longer when the action is easy to trigger by mistake.

## 6. Toasts and status messages (accessibility)

- Results of an operator action are status messages (WCAG 2.2 SC 4.1.3): put them in a live region
  that exists **before** the message is inserted (`role="status"` = polite; `role="alert"` only
  for errors that need immediate attention).
- A toast that carries an action (Undo, Retry) must not vanish before the user can reach it: no
  auto-dismiss under about 10 s, pause on hover and focus, and a keyboard shortcut or a log entry
  that reaches the same action (SC 2.2.1 Timing Adjustable).
- Do not move focus into a toast; announce it and let the operator choose.
- Do not cover the focused element with a toast (SC 2.4.11 Focus Not Obscured).

## 7. Concurrency: two operators, one item

- Every mutating request carries the version the operator saw (`If-Match` with an ETag, or a
  `version` field); the server returns `409` or `412` on mismatch.
- On conflict show what changed ("Approved by Ana 20 s ago") and offer the next action; never
  silently re-apply the stale decision.
- Push updates that touch an open item mark it "changed since you opened this" instead of swapping
  content under the operator's cursor.

## 8. Illustrative case

A single-owner automation service exposes time-boxed signed grants for its agents. Its console
queue shows each grant request as an approval card with scope (which capability, for how long),
the requester and an expiry. Approving needs a passkey step-up whose challenge is bound to the
grant id and version; the card stays `approving` until the service reports the grant as issued,
and an expired request leaves the queue as `expired` rather than being approved late.
