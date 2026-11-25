# codex_top_seat.sh -- SOURCED, never executed. It defines the one function below and nothing else:
# no top-level command, no `set`, no trap, no `cd`. A call site sources it and checks that the function
# exists, in the SAME Bash call that runs its seats (shell functions do not survive between calls); the
# source-and-guard preamble is in the codex-orchestration skill, "Seat Models".
#
# codex_top_seat NAME ROLE USE SIZE KEY BRIEF_FILE OUT_FILE [codex exec flags...] -- one budgeted codex seat.
codex_top_seat() {
  local NAME="$1" ROLE="$2" USE="$3" SIZE="$4" KEY="$5" BRIEF="$6" DEST="$7" OUT RC ACT="" TRY TO MDL; shift 7
  local SEAT="$HOME/.claude/skills/_meta/seat_model.py" QUOTA="$HOME/.claude/skills/_meta/codex_quota.py"
  local WATCH="$HOME/.claude/skills/_meta/codex_watch.py" TRIES="1 2" SUBUSE="$USE" RETRY RRC RTO AID="" AKEY=""
  local L2 WA RIN UU UK UM
  # The receipt: `<admission id> <key>` of this seat's LIVE admission, written atomically by argv. DEST must be
  # unique per seat (the receipt is "$DEST.admit"). Read in a subshell, so this function's "$@" is untouched.
  rm -f "$DEST.admit"
  # SIZE and KEY are EMPTY when the caller has none, and an empty one passes NO FLAG AT ALL. Sizing is
  # opt-in: with no --size the registry reads no size file, so an unsized seat takes the TOP model even on
  # a small cycle -- and passing a literal size instead of nothing would record `size_source: routing`, a
  # routing decision nobody made. An empty KEY leaves the budget key the project derives; a caller that
  # mints its own passes it here, so its seats share ONE key and spend their OWN budget, not the round's.
  # #322: --await-quota -- a QUOTA refusal records no stand-in yet; it prints the reset lines and
  # `substitution=deferred`, and the seat's owner waits (see CODEX_QUOTA_WAIT below).
  OUT="$(python3 "$SEAT" argv --role "$ROLE" --provider codex --use "$USE" --receipt-file "$DEST.admit" \
           --await-quota ${SIZE:+--size "$SIZE"} ${KEY:+--cycle-id "$KEY"} \
           --project-root "${PROJECT_DIR:-$PWD}")"; RC=$?
  # The timeout is the seat registry's, asked only AFTER an admitted `argv --use` (asked first, a no-eligible
  # substitution would become a gap) and never as a second `argv` stdout line: $OUT is word-split into
  # `codex exec $OUT`, so an extra line would become a prompt. No timeout -> the gap line; codex never runs.
  if [ "$RC" -eq 0 ]; then
    TO="$(python3 "$SEAT" timeout --role "$ROLE" --provider codex)" || { ACT="seat_model timeout exit $?"; RC=1; }
    MDL="$(set -- $OUT; echo "$2")"     # the pinned model, named once: progress line and substitution record
    AID="$(set -- $(cat "$DEST.admit" 2>/dev/null); echo "${1-}")"
    AKEY="$(set -- $(cat "$DEST.admit" 2>/dev/null); echo "${2-}")"; AKEY="${AKEY:-$KEY}"
  fi
  if [ "$RC" -eq 0 ]; then
    while [ -n "$TRIES" ]; do
      for TRY in $TRIES; do
        # D24: the watchdog stops the call on INACTIVITY -- no stdout, no stderr and no session-rollout write
        # for the idle window -- so "thinking hard" is no longer killed as "hung". The registry timeout is
        # passed as the RUNAWAY cap only, never as the normal stop, and the watchdog prints a progress line to
        # this call's stderr while it waits. Its exits: 111 went silent (the retryable stop, classified as a
        # timeout), 112 ran away while still active (a gap on the FIRST hit, never a substitution), anything
        # else is codex's own status passed straight through.
        python3 "$WATCH" --mode codex --hard-cap "$TO" --model "$MDL" \
          --stdout-file "$DEST.stdout" --stderr-file "$DEST.stderr" \
          -- codex exec "$@" $OUT -o "$DEST" "$(cat "$BRIEF")"; RC=$?
        ACT="$(python3 "$QUOTA" classify --exit-code "$RC" --attempt "$TRY" $([ "$RC" -eq 111 ] && echo --timed-out) \
                 --stderr-file "$DEST.stderr" --output-file "$DEST" --prompt-file "$BRIEF")" || ACT=classify_error
        [ "${ACT%% *}" = retry ] || break
      done
      TRIES=""
      # U2, the astra reserve: a seat that failed on CAPABILITY (capacity or a malformed answer, twice) gets ONE
      # attempt on the codex TOP. seat_model decides whether that is a retry at all -- it proves the failed
      # attempt from its receipt (an admitted std row of this role, use and key), wants a DIFFERENT pin that
      # bills the TOP class, and admits it as `top_retry` on the FORGE CYCLE (1 per cycle) -- and records the
      # event row. The TOP timeout is asked FIRST, so a failed lookup spends no retry slot. Exit 0: run it ONCE,
      # classified as attempt 2 so it has no inner retry, and SUBUSE stops a second entry; the receipt now names
      # the retry's own admission and key. Exit 3: the D6 line, already recorded. Anything else: the original
      # failure is substituted below. Quota, auth, budget, timeout and gap outcomes never reach this branch.
      case "$SUBUSE:$ACT" in
        "$USE:substitute capacity_twice"|"$USE:substitute malformed_twice")
          RRC=1
          if RTO="$(python3 "$SEAT" timeout --role "$ROLE" --provider codex --top-retry)"; then
            rm -f "$DEST.admit"   # only the retry's own receipt may follow
            RETRY="$(python3 "$SEAT" argv --role "$ROLE" --provider codex --use "$USE" --top-retry \
                       --failed-admission-id "$AID" --failed-reason "${ACT#substitute }" \
                       --receipt-file "$DEST.admit" --await-quota ${AKEY:+--cycle-id "$AKEY"} \
                       --project-root "${PROJECT_DIR:-$PWD}")"; RRC=$?
          fi
          if [ "$RRC" -eq 0 ]; then
            OUT="$RETRY"; MDL="$(set -- $OUT; echo "$2")"; SUBUSE=top_retry; TRIES=2; TO="$RTO"
            AKEY="$(set -- $(cat "$DEST.admit" 2>/dev/null); echo "${2-}")"; AKEY="${AKEY:-$KEY}"
          elif [ "$RRC" -eq 3 ]; then
            OUT="$RETRY"; ACT=top_retry_substituted
          fi ;;
      esac
    done
    case "$ACT" in
      "ok -") ;;
      top_retry_substituted) RC=3 ;;
      # the substitution names the key its admission was billed to (the receipt's, else the caller's KEY): a
      # failed TOP retry keeps its forge-cycle key, a tournament or ballot seat its own
      "substitute "*) OUT="$(python3 "$SEAT" substitute --role "$ROLE" --use "$SUBUSE" --reason "${ACT#substitute }" \
                               --requested-model "$MDL" ${AKEY:+--cycle-id "$AKEY"} \
                               --project-root "${PROJECT_DIR:-$PWD}")"; RC=$? ;;
      # classify itself failed: after a codex exit 0 keep codex's output in $DEST; after a failed call, a gap
      classify_error) if [ "$RC" -eq 0 ]; then
                        echo "CODEX_CLASSIFY_ERROR: $NAME: classify failed after codex exit 0; $DEST keeps its output" >&2
                      else RC=1; fi ;;
      *) RC=1 ;;
    esac
  fi
  # Exit 3 prints the reason on LINE 1 and the Claude model on LINE 2; a quota refusal (#322) appends
  # key=value lines after them, so the model is read as line 2, never as the last line.
  L2="${OUT#*$'\n'}"; L2="${L2%%$'\n'*}"
  case "$RC:$OUT" in
    0:*) ;;  # codex answered: $DEST holds its output
    3:*$'\n'substitution=deferred*)
       WA="${OUT##*$'\n'wait_advice=}"; WA="${WA%%$'\n'*}"
       RIN="unknown"; case "$OUT" in *$'\n'resets_in_s=*) RIN="${OUT##*$'\n'resets_in_s=}"; RIN="${RIN%%$'\n'*}" ;; esac
       # #322 fix round 1: the use, key and codex model a later `substitute` must name (a TOP retry's own)
       UU="${OUT##*$'\n'use=}"; UU="${UU%%$'\n'*}"; UK="${OUT##*$'\n'key=}"; UK="${UK%%$'\n'*}"
       UM="-"; case "$OUT" in *$'\n'requested_model=*) UM="${OUT##*$'\n'requested_model=}"; UM="${UM%%$'\n'*}" ;; esac
       printf 'CODEX_QUOTA_WAIT: %s (reason %s; wait_advice %s; resets_in_s %s; stand-in %s; use %s; key %s; requested %s)\nbrief: %s\n' \
         "$NAME" "${OUT%%$'\n'*}" "$WA" "$RIN" "$L2" "$UU" "$UK" "$UM" "$BRIEF" > "$DEST" ;;
    3:*) printf 'CODEX_SUBSTITUTE: %s -> %s (reason %s; provider gap: openai)\nbrief: %s\n' \
         "$NAME" "$L2" "${OUT%%$'\n'*}" "$BRIEF" > "$DEST" ;;
    *) echo "CODEX_GAP: $NAME seat skipped (${ACT:-exit $RC}; see stderr)" > "$DEST" ;;
  esac
}
