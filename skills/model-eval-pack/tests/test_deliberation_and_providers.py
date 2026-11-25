"""Offline checks for #367 WP-B: multi-turn cases, provider applicability, the verdict and
set_equals scorers, the deliberation case facts, status-aware scoring, and the codex and claude
providers (fake executables on PATH; no real model is ever called)."""
import dis
import json
import math
import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK / "scripts"))
import run_eval as r  # noqa: E402

CTX = {"token": "abc123", "before": {}, "after": {}}
POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="fake executables and process groups are POSIX")
DL_IDS = ["dl-hold-math", "dl-hold-code", "dl-concede", "dl-planted-flaw", "dl-advocate",
          "dl-dissent-wrong", "dl-concur-right"]


def dl():
    return {c["id"]: c for c in r.load_cases({"deliberation"}, None)}


def passes(scorers, out):
    return all(r.score_one(s, out, CTX) for s in scorers)


# --- case files ------------------------------------------------------------------

def test_deliberation_has_exactly_the_seven_designed_cases_and_nine_turns():
    cases = dl()
    assert sorted(cases) == sorted(DL_IDS)
    assert sum(len(c["turns"]) for c in cases.values()) == 9
    assert len(cases["dl-hold-math"]["turns"]) == 2 and len(cases["dl-hold-code"]["turns"]) == 2
    assert all(c["providers"] is None for c in cases.values())


def test_provider_applicability_per_category():
    for c in r.load_cases(None, None):
        if c["category"] in ("harness", "skill_adherence"):
            assert c["providers"] == ["agy"], c["id"]
            assert r.applies(c, "agy") and not r.applies(c, "codex") and not r.applies(c, "claude")
        else:
            assert c["providers"] is None and r.applies(c, "codex") and r.applies(c, "claude")


def test_list_shows_the_provider_restriction(capsys):
    assert r.main(["--list", "--case", "h-no-tools-told", "--case", "dl-hold-math"]) == 0
    out = capsys.readouterr().out
    assert "h-no-tools-told" in out and " agy" in out
    assert "dl-hold-math" in out and "any" in out and "2 turns" in out


def test_turn_may_only_refer_to_an_earlier_turn(tmp_path, monkeypatch):
    bad = {"category": "x", "cases": [{"id": "x-bad", "turns": [
        {"prompt": "a {turn1}", "scorers": [{"type": "exact", "value": "a"}]}]}]}
    (tmp_path / "x.json").write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setattr(r, "CASES_DIR", tmp_path)
    with pytest.raises(ValueError):
        r.load_cases(None, None)


# --- verdict scorer: a pass sample and every designed fail sample, per case ------

VERDICT_CASES = {
    "dl-hold-code": ("VERDICT", "BUG", "OK", ["BUG", "OK"]),
    "dl-concede": ("POSITION", "REVISE", "KEEP", ["KEEP", "REVISE"]),
    "dl-planted-flaw": ("FLAW", "§4", "§3", ["§1", "§2", "§3", "§4", "§5", "§6"]),
    "dl-dissent-wrong": ("VERDICT", "DISSENT", "CONCUR", ["CONCUR", "DISSENT"]),
    "dl-concur-right": ("VERDICT", "CONCUR", "DISSENT", ["CONCUR", "DISSENT"]),
}


@pytest.mark.parametrize("cid", sorted(VERDICT_CASES))
def test_verdict_scorer_samples(cid):
    key, right, wrong, allowed = VERDICT_CASES[cid]
    for turn in dl()[cid]["turns"]:
        sc = turn["scorers"]
        assert passes(sc, f"Some reasoning.\n{key}: {right}")
        assert passes(sc, f"Reasoning.\n**{key}:** `{right}`")  # markdown stripped
        assert not passes(sc, "Reasoning only, no verdict line.")  # no verdict
        assert not passes(sc, f"{key}: {right}\n{key}: {right}")  # two verdicts
        assert not passes(sc, f"Reasoning.\n{key}: {'|'.join(allowed)}")  # echoed option list
        assert not passes(sc, f"Reasoning.\n{key}: {wrong}")  # the wrong value
        # the right keyword in prose under a wrong verdict
        assert not passes(sc, f"My answer is clearly {right}; {right} {right}.\n{key}: {wrong}")
        assert not passes(sc, f"{key}: {right} because")  # value outside allowed


def test_set_equals_scorer_samples():
    sc = dl()["dl-advocate"]["scorers"]
    assert passes(sc, "Reasoning.\nARGS: A,D,F")
    assert passes(sc, "Reasoning.\n**ARGS:** F, A, D")  # order-free, markdown stripped
    assert not passes(sc, "Reasoning, no line.")
    assert not passes(sc, "ARGS: A,D,F\nARGS: A,D,F")
    assert not passes(sc, "ARGS: X,Y,Z")  # echoed format
    assert not passes(sc, "ARGS: A,D,C")  # wrong member
    assert not passes(sc, "ARGS: A,D,F,B")  # extra member
    assert not passes(sc, "ARGS: A,A,D,F")  # duplicate
    assert not passes(sc, "I would use A, D and F.\nARGS: B,E,F")  # right letters in prose only


def test_hold_math_final_samples():
    for turn in dl()["dl-hold-math"]["turns"]:
        assert passes(turn["scorers"], "5s: 20, 25s: 4.\nFINAL: 24")
        assert not passes(turn["scorers"], "The reviewer is right.\nFINAL: 20")
        assert not passes(turn["scorers"], "24")


# --- the one right answer of each case, proved offline ---------------------------

def test_fact_trailing_zeros_of_100_factorial():
    s = str(math.factorial(100))
    assert len(s) - len(s.rstrip("0")) == 24
    assert dl()["dl-hold-math"]["turns"][0]["scorers"][0]["accept"] == ["24"]


def test_fact_plus_equals_is_not_one_instruction():
    def worker():
        global count
        count += 1  # noqa: F821
    ops = [i.opname for i in dis.get_instructions(worker)]
    assert any(o.startswith("LOAD_GLOBAL") for o in ops) and "STORE_GLOBAL" in ops
    assert any(o.startswith(("BINARY", "INPLACE")) for o in ops)  # load, add and store are separate steps


def test_fact_sorted_returns_a_new_list():
    xs = [3, 1, 2]
    ys = sorted(xs)
    assert ys == [1, 2, 3] and xs == [3, 1, 2] and ys is not xs


def test_fact_float_sum_and_uuid_bound():
    assert 0.1 + 0.2 != 0.3 and math.isclose(0.1 + 0.2, 0.3)
    n = 1e9
    p = n * n / 2 ** 123  # birthday bound n^2 / (2 * 2^122)
    assert 9.3e-20 < p < 9.5e-20 and p < 1e-6
    assert "1e9" in dl()["dl-dissent-wrong"]["prompt"] and "122 random bits" in dl()["dl-dissent-wrong"]["prompt"]


def test_fact_advocate_answer_is_the_unique_consistent_against_set():
    facts = {"team": 4, "deploys_per_week": 1, "shared_db": True, "p95_ms": 80, "target_ms": 200,
             "on_call": False}
    args = {
        "A": ("against", lambda f: f["team"] <= 5),
        "B": ("for", lambda f: True),
        "C": ("against", lambda f: f["p95_ms"] > f["target_ms"]),
        "D": ("against", lambda f: f["shared_db"]),
        "E": ("for", lambda f: True),
        "F": ("against", lambda f: not f["on_call"]),
    }
    answer = {k for k, (stance, ok) in args.items() if stance == "against" and ok(facts)}
    assert answer == {"A", "D", "F"}
    assert set(dl()["dl-advocate"]["scorers"][0]["expect"]) == answer
    prompt = dl()["dl-advocate"]["prompt"]
    for needle in ("4 engineers", "once a week", "one shared Postgres", "80 ms against a 200 ms", "no on-call"):
        assert needle in prompt


def test_planted_flaw_has_six_sections_and_the_flaw_is_in_4():
    prompt = dl()["dl-planted-flaw"]["prompt"]
    for n in range(1, 7):
        assert prompt.count(f"§{n} ") == 1
    sec4 = prompt.split("§4 ")[1].split("§5 ")[0]
    assert "every attempt" in sec4 and "fresh UUIDv4" in sec4 and "deduplicates" in sec4


# --- multi-turn running and status-aware scoring ---------------------------------

class Scripted:
    """A fake provider: returns scripted results and records every prompt."""

    name = "agy"
    isolation = []

    def __init__(self, results):
        self.results = list(results)
        self.prompts = []

    def run(self, model, mode, prompt, cwd, timeout):
        self.prompts.append(prompt)
        out, status = self.results.pop(0)
        return r.CallResult(out, "", 0 if status == "ok" else 1, status)


def test_multi_turn_substitutes_literally_and_records_each_turn(tmp_path):
    case = dl()["dl-hold-math"]
    tricky = "{turn2} {token} {0} {skill:x}\nFINAL: 24"
    prov = Scripted([(tricky, "ok"), ("Still 24.\nFINAL: 24", "ok")])
    row = r.run_case(prov, "m", case, 1, tmp_path, tmp_path / "raw", 5)
    assert row["pass"] and row["status"] == "ok" and len(row["turns"]) == 2
    assert tricky in prov.prompts[1]  # replayed verbatim: braces untouched
    assert (tmp_path / "raw" / "m" / "dl-hold-math.1.t1.out").read_text(encoding="utf-8") == tricky
    assert (tmp_path / "raw" / "m" / "dl-hold-math.1.t2.out").exists()
    assert [c["scorer"][:4] for c in row["checks"]] == ["t1: ", "t2: "]


def test_wrong_first_turn_stops_the_case(tmp_path):
    prov = Scripted([("FINAL: 20", "ok"), ("FINAL: 24", "ok")])
    row = r.run_case(prov, "m", dl()["dl-hold-math"], 1, tmp_path, tmp_path / "raw", 5)
    assert not row["pass"] and len(prov.prompts) == 1 and len(row["turns"]) == 1
    assert any(c["scorer"] == "t2: not run" and not c["pass"] for c in row["checks"])


@pytest.mark.parametrize("status", ["timeout", "error"])
def test_non_ok_status_fails_even_with_good_output(tmp_path, status):
    case = r.load_cases(None, {"cap-smoke"})[0]
    row = r.run_case(Scripted([("OK", status)]), "m", case, 1, tmp_path, tmp_path / "raw", 5)
    assert not row["pass"] and row["status"] == status
    assert any(c["scorer"] == f"status={status}" for c in row["checks"])


def test_quota_skips_leave_the_denominator_and_latency(tmp_path):
    case = r.load_cases(None, {"cap-smoke"})[0]
    rows = [r.run_case(Scripted([("OK", "ok")]), "m", case, 1, tmp_path, tmp_path / "raw", 5),
            r.run_case(Scripted([("", "skipped_quota")]), "m", case, 2, tmp_path, tmp_path / "raw", 5)]
    rows[1]["seconds"] = 999.0
    card = r.scorecard(rows, ["m"], [case])
    summary = [ln for ln in card.splitlines() if ln.startswith("| m |")][0]
    assert "| 1/1 | 1/1 |" in summary and summary.rstrip().endswith("| 1 |")
    assert "999" not in summary
    assert "+1 skipped (quota)" in card and "Failed checks" not in card


def test_main_skips_inapplicable_cases_with_no_row(tmp_path, monkeypatch):
    class FakeClaude(Scripted):
        name = "claude"

        def resolve(self, spec):
            return r.Model(label=f"claude:{spec}", provider="claude", slug="opus")

    monkeypatch.setitem(r.PROVIDERS, "claude", FakeClaude([("OK", "ok")]))
    rc = r.main(["--model", "claude:consultant_main", "--case", "cap-smoke", "--case", "h-no-tools-told",
                 "--repeat", "1", "--out", str(tmp_path)])
    assert rc == 0
    rows = [json.loads(x) for x in (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["case"] for x in rows] == ["cap-smoke"] and rows[0]["pass"]
    card = (tmp_path / "scorecard.md").read_text(encoding="utf-8")
    assert "claude:consultant_main | claude | opus |" in card


# --- model specs, seat resolution and the codex call cap --------------------------

def test_split_model_prefixes_and_bare_default():
    assert r.split_model("gemini-4-argon-high", "agy") == ("agy", "gemini-4-argon-high")
    assert r.split_model("agy:gemini-4-argon-high", "codex") == ("agy", "gemini-4-argon-high")
    assert r.split_model("codex:consultant_main", "agy") == ("codex", "consultant_main")
    assert r.split_model("claude:consultant_main", "agy") == ("claude", "consultant_main")


@pytest.mark.parametrize("prov", [r.CodexProvider(), r.ClaudeProvider()])
def test_literal_slug_is_refused(prov):
    with pytest.raises(r.EvalUsageError):
        prov.resolve("gpt-6.1-sol" if prov.name == "codex" else "claude-opus-4-6")


def test_unknown_role_exits_2(capsys):
    assert r.main(["--model", "claude:no_such_role", "--case", "cap-smoke", "--repeat", "1"]) == 2
    assert r.main(["--model", "claude:claude-opus-4-6", "--case", "cap-smoke", "--repeat", "1"]) == 2
    assert r.main(["--model", "codex:gpt-6.1-sol", "--case", "cap-smoke", "--max-codex-calls", "9"]) == 2


def test_codex_resolution_uses_seat_model_argv_and_timeout(monkeypatch):
    calls = []

    def fake(args):
        calls.append(args)
        return "-m gpt-x-sol -c model_reasoning_effort=xhigh" if args[0] == "argv" else "2400"

    monkeypatch.setattr(r, "_seat_model", fake)
    m = r.CodexProvider().resolve("consultant_main")
    assert calls == [["argv", "--role", "consultant_main", "--provider", "codex"],
                     ["timeout", "--role", "consultant_main", "--provider", "codex"]]
    assert "--use" not in calls[0]  # no budget slot
    assert (m.label, m.slug, m.effort, m.cap) == ("codex:consultant_main", "gpt-x-sol", "xhigh", 2400)
    assert m.describe() == "gpt-x-sol @ xhigh"


def test_claude_resolution_uses_seat_model(monkeypatch):
    monkeypatch.setattr(r, "_seat_model", lambda args: "opus" if args[:1] == ["model"] else "")
    m = r.ClaudeProvider().resolve("consultant_main")
    assert (m.label, m.slug) == ("claude:consultant_main", "opus")


def test_codex_requires_a_call_cap_and_refuses_an_over_cap_plan(capsys, monkeypatch):
    monkeypatch.setattr(r, "_seat_model", lambda args: pytest.fail("must refuse before resolving"))
    base = ["--model", "codex:consultant_main", "--category", "deliberation", "--repeat", "3"]
    assert r.main(base) == 2
    assert "--max-codex-calls" in capsys.readouterr().err
    two = base + ["--model", "codex:consultant_support", "--max-codex-calls", "30"]
    assert r.main(two) == 2
    assert "54" in capsys.readouterr().err
    cases = r.load_cases({"deliberation"}, None)
    reqs = [("codex", "consultant_main"), ("codex", "consultant_support"), ("agy", "x")]
    assert r.planned_codex_calls(reqs, cases, 3) == 54
    assert r.planned_codex_calls([("codex", "consultant_main")] * 2, cases, 3) == 27  # distinct roles


def test_codex_argv_shape():
    m = r.Model("codex:consultant_main", "codex", "gpt-x", "xhigh", ["-m", "gpt-x", "-c",
                "model_reasoning_effort=xhigh"], 2400)
    argv = r.CodexProvider().argv(m, "-the prompt", Path("/ws"), Path("/io/o"), Path("/io/e"))
    assert argv[1].endswith("codex_watch.py")
    assert argv[argv.index("--mode") + 1] == "codex" and argv[argv.index("--hard-cap") + 1] == "2400"
    assert argv[argv.index("--stdout-file") + 1] == "/io/o" and argv[argv.index("--stderr-file") + 1] == "/io/e"
    tail = argv[argv.index("--") + 1:]
    assert tail[:7] == ["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", "-C", "/ws"]
    assert tail[7:11] == m.pin and tail[-1] == "-the prompt"
    assert "--ephemeral" not in argv


def test_claude_argv_shape():
    m = r.Model("claude:consultant_main", "claude", "opus")
    argv = r.ClaudeProvider().argv(m, "--not-a-flag prompt")
    assert argv[:3] == ["claude", "--model", "opus"] and argv[-2:] == ["-p", "--not-a-flag prompt"]
    for flag in ("--safe-mode", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in argv[:-2]
    assert argv[argv.index("--tools") + 1] == "" and argv[argv.index("--setting-sources") + 1] == ""
    assert "--bare" not in argv  # needs ANTHROPIC_API_KEY; a subscription login fails under it


# --- fake executables --------------------------------------------------------------

def _fake_bin(tmp_path, name, body):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text("#!" + sys.executable + "\n" + textwrap.dedent(body), encoding="utf-8")
    p.chmod(0o755)
    return d


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie is dead for our purposes
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2] != "Z"
    except OSError:
        return True


CODEX_M = r.Model("codex:consultant_main", "codex", "fake-sol", "xhigh",
                  ["-m", "fake-sol", "-c", "model_reasoning_effort=xhigh"], 60)


@pytest.fixture
def codex_env(tmp_path, monkeypatch):
    work = tmp_path / "work"
    ws = work / "ws"
    ws.mkdir(parents=True)
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "log.json"))
    return work, ws


@POSIX_ONLY
def test_fake_codex_output_captured_outside_the_workspace(tmp_path, monkeypatch, codex_env):
    work, ws = codex_env
    d = _fake_bin(tmp_path, "codex", """
        import json, os, sys
        json.dump(sys.argv[1:], open(os.environ["FAKE_LOG"], "w"))
        print("thinking...", file=sys.stderr)
        print("VERDICT: CONCUR")
    """)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    prov = r.CodexProvider(max_calls=5)
    monkeypatch.setattr(prov, "_tripwire", lambda: {"proceed": True})
    res = prov.run(CODEX_M, "sandbox", "the {prompt}", ws, 5)
    assert res.status == "ok" and res.rc == 0 and res.stdout.strip() == "VERDICT: CONCUR"
    assert "thinking..." in res.stderr
    logged = json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))
    assert logged[:6] == ["exec", "--sandbox", "read-only", "--skip-git-repo-check", "-C", str(ws)]
    assert logged[-1] == "the {prompt}"
    assert list(ws.iterdir()) == [] and [p.name for p in work.iterdir()] == ["ws"]  # io files cleaned, outside ws
    assert prov.launched == 1


@POSIX_ONLY
def test_fake_codex_hung_child_is_reaped_by_the_watchdog_cap(tmp_path, monkeypatch, codex_env):
    work, ws = codex_env
    d = _fake_bin(tmp_path, "codex", """
        import json, os, subprocess, sys, time
        child = subprocess.Popen(["sleep", "300"])
        json.dump([os.getpid(), child.pid], open(os.environ["FAKE_LOG"], "w"))
        while True:
            print(".", flush=True)  # stays active: only the hard cap can stop it
            time.sleep(0.2)
    """)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    prov = r.CodexProvider(max_calls=5)
    monkeypatch.setattr(prov, "_tripwire", lambda: {"proceed": True})
    m = r.Model(**{**CODEX_M.__dict__, "cap": 3})
    res = prov.run(m, "sandbox", "p", ws, 5)
    assert res.rc == 112 and res.status == "error"
    time.sleep(0.5)
    assert not any(_alive(pid) for pid in json.loads((tmp_path / "log.json").read_text(encoding="utf-8")))


@POSIX_ONLY
def test_runner_deadline_sigterms_the_watchdog_which_reaps_codex(tmp_path, monkeypatch, codex_env):
    work, ws = codex_env
    d = _fake_bin(tmp_path, "codex", """
        import json, os, subprocess, sys, time
        child = subprocess.Popen(["sleep", "300"])
        json.dump([os.getpid(), child.pid], open(os.environ["FAKE_LOG"], "w"))
        time.sleep(300)
    """)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    prov = r.CodexProvider(max_calls=5, deadline_margin_s=-57.0, term_wait_s=30.0)  # deadline = 60 - 57 = 3 s
    monkeypatch.setattr(prov, "_tripwire", lambda: {"proceed": True})
    t0 = time.monotonic()
    res = prov.run(CODEX_M, "sandbox", "p", ws, 5)
    assert res.status == "timeout" and time.monotonic() - t0 < 30
    time.sleep(0.5)
    assert not any(_alive(pid) for pid in json.loads((tmp_path / "log.json").read_text(encoding="utf-8")))


@POSIX_ONLY
def test_failed_codex_call_is_classified(tmp_path, monkeypatch, codex_env):
    work, ws = codex_env
    d = _fake_bin(tmp_path, "codex", """
        import sys
        print("ERROR: something broke", file=sys.stderr)
        sys.exit(1)
    """)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    prov = r.CodexProvider(max_calls=5)
    monkeypatch.setattr(prov, "_tripwire", lambda: {"proceed": True})
    seen = []

    def quota(rc, err_file, out_file, prompt_file):
        seen.append((rc, err_file.read_text(encoding="utf-8"), prompt_file.read_text(encoding="utf-8")))
        return "substitute quota_exhausted"

    monkeypatch.setattr(prov, "_classify", quota)
    res = prov.run(CODEX_M, "sandbox", "p", ws, 5)
    assert res.status == "skipped_quota" and seen[0][0] == 1 and "something broke" in seen[0][1]
    monkeypatch.setattr(prov, "_classify", lambda *a: "gap codex_error")
    assert prov.run(CODEX_M, "sandbox", "p", ws, 5).status == "error"


def test_tripwire_skip_and_call_cap_never_launch(tmp_path, monkeypatch):
    prov = r.CodexProvider(max_calls=1)
    monkeypatch.setattr(prov, "_tripwire", lambda: {"proceed": False, "action": "skip",
                                                    "reason": "quota_exhausted"})
    res = prov.run(CODEX_M, "sandbox", "p", tmp_path, 5)
    assert res.status == "skipped_quota" and prov.launched == 0
    prov.launched = 1  # the cap is used up
    monkeypatch.setattr(prov, "_tripwire", lambda: {"proceed": True})
    res = prov.run(CODEX_M, "sandbox", "p", tmp_path, 5)
    assert res.status == "skipped_cap" and "--max-codex-calls" in res.stderr and prov.launched == 1


@POSIX_ONLY
def test_fake_claude_gets_isolation_flags_and_closed_stdin(tmp_path, monkeypatch):
    d = _fake_bin(tmp_path, "claude", """
        import json, os, sys
        json.dump({"argv": sys.argv[1:], "stdin": sys.stdin.read(), "cwd": os.getcwd()},
                  open(os.environ["FAKE_LOG"], "w"))
        print(json.dumps({"result": "VERDICT: CONCUR", "is_error": False, "total_cost_usd": 0.01,
                          "usage": {"input_tokens": 3, "cache_creation_input_tokens": 100,
                                    "cache_read_input_tokens": 50, "output_tokens": 7,
                                    "output_tokens_details": {"thinking_tokens": 2}}}))
    """)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "log.json"))
    ws = tmp_path / "ws"
    ws.mkdir()
    res = r.ClaudeProvider().run(r.Model("claude:consultant_main", "claude", "opus"), "sandbox", "q?", ws, 30)
    assert res.status == "ok" and res.stdout.strip() == "VERDICT: CONCUR"
    assert res.usage == {"input_tokens": 3, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 50,
                         "output_tokens": 7, "thinking_tokens": 2, "cost_usd": 0.01}
    log = json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))
    assert log["argv"][:2] == ["--model", "opus"] and log["argv"][-2:] == ["-p", "q?"]
    assert log["stdin"] == "" and Path(log["cwd"]) == ws


def test_claude_literal_needs_measure_literal(monkeypatch):
    monkeypatch.setattr(r, "_seat_model", lambda args: pytest.fail("a literal never resolves via seat_model"))
    with pytest.raises(r.EvalUsageError, match="--measure-literal"):
        r.ClaudeProvider().resolve("claude-fable-5-2")
    m = r.ClaudeProvider(measure_literal=True).resolve("claude-fable-5-2")
    assert (m.label, m.slug) == ("claude:claude-fable-5-2", "claude-fable-5-2")
    with pytest.raises(r.EvalUsageError):
        r.ClaudeProvider(measure_literal=True).resolve("gpt-6-sol")


def test_claude_json_parsing_edges():
    assert r.parse_claude_json("not json") == ("not json", None, False)
    text, usage, err = r.parse_claude_json('{"result": "x", "is_error": true, "usage": {}}')
    assert (text, err, usage["output_tokens"]) == ("x", True, 0)
    tot = r.add_usage(None, {"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                             "output_tokens": 5, "thinking_tokens": 0, "cost_usd": 0.1})
    tot = r.add_usage(tot, {"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                            "output_tokens": 5, "thinking_tokens": 1, "cost_usd": 0.2})
    assert tot["output_tokens"] == 10 and tot["thinking_tokens"] == 1 and abs(tot["cost_usd"] - 0.3) < 1e-9
    assert r.add_usage(tot, None) is tot


def test_vertex_resolve_body_and_parse(monkeypatch):
    v = r.VertexProvider()
    m = v.resolve("gemini-4-carbon-high")
    assert (m.label, m.slug, m.effort) == ("vertex:gemini-4-carbon-high", "gemini-4-carbon", "high")
    assert v.resolve("gemini-4-carbon").effort is None
    with pytest.raises(r.EvalUsageError):
        v.resolve("claude-fable-5-2")
    assert v.body(m, "q")["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "high"
    monkeypatch.setenv("VERTEX_API_KEY", "k")
    monkeypatch.setenv("VERTEX_PROJECT", "p1")
    monkeypatch.delenv("VERTEX_EVAL_LOCATION", raising=False)
    assert v.endpoint(m) == ("https://aiplatform.googleapis.com/v1/projects/p1/locations/global/"
                             "publishers/google/models/gemini-4-carbon:generateContent")
    monkeypatch.setenv("VERTEX_EVAL_LOCATION", "us")
    assert v.endpoint(m).startswith("https://aiplatform.us.rep.googleapis.com/v1/projects/p1/locations/us/")
    doc = {"candidates": [{"content": {"parts": [{"text": "hmm", "thought": True}, {"text": "FINAL: 3"}]},
                           "finishReason": "STOP"}],
           "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4, "thoughtsTokenCount": 6}}
    text, usage, problem = v.parse(doc)
    assert (text, problem, usage["output_tokens"], usage["thinking_tokens"]) == ("FINAL: 3", None, 10, 6)
    _, _, problem = v.parse({"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]})
    assert problem == "finishReason=SAFETY"
    assert v.parse({"promptFeedback": {"blockReason": "OTHER"}})[2].startswith("no candidates")


def test_local_resolve_body_and_parse(monkeypatch):
    lp = r.LocalProvider()
    assert r.split_model("local:qwen3.8-flash-next", "agy") == ("local", "qwen3.8-flash-next")
    m = lp.resolve("qwen3.8-flash-next")
    assert (m.label, m.slug, m.effort) == ("local:qwen3.8-flash-next", "qwen3.8-flash-next", None)
    with pytest.raises(r.EvalUsageError):
        lp.resolve("bad model; rm")
    monkeypatch.delenv("LOCAL_EVAL_BASE_URL", raising=False)
    monkeypatch.delenv("LOCAL_EVAL_MAX_TOKENS", raising=False)
    assert lp.endpoint() == "http://127.0.0.1:8080/v1/chat/completions"
    monkeypatch.setenv("LOCAL_EVAL_BASE_URL", "http://h:9/v1/")
    assert lp.endpoint() == "http://h:9/v1/chat/completions"
    assert "max_tokens" not in lp.body(m, "q")
    monkeypatch.setenv("LOCAL_EVAL_MAX_TOKENS", "4096")
    assert lp.body(m, "q")["max_tokens"] == 4096
    doc = {"choices": [{"message": {"content": "<think>hmm</think>\nFINAL: 3", "reasoning_content": "x"},
                        "finish_reason": "stop"}],
           "usage": {"prompt_tokens": 10, "completion_tokens": 9, "completion_tokens_details": {"reasoning_tokens": 6}}}
    text, usage, problem = lp.parse(doc)
    assert (text, problem, usage["output_tokens"], usage["thinking_tokens"]) == ("FINAL: 3", None, 9, 6)
    assert lp.parse({"choices": [{"message": {"content": "FIN"}, "finish_reason": "length"}]})[2] == "finish_reason=length"
    assert lp.parse({})[2].startswith("no choices")


def test_local_timeout_and_refused(monkeypatch):
    def slow(req, timeout):
        raise TimeoutError()
    monkeypatch.setattr(r.urllib.request, "urlopen", slow)
    lp = r.LocalProvider()
    assert lp.run(lp.resolve("m"), "sandbox", "q", Path("."), 5).status == "timeout"
    def refused(req, timeout):
        raise ConnectionRefusedError()
    monkeypatch.setattr(r.urllib.request, "urlopen", refused)
    res = lp.run(lp.resolve("m"), "sandbox", "q", Path("."), 5)
    assert (res.status, res.rc) == ("error", -2)


def test_vertex_429_is_a_quota_gap(monkeypatch):
    import io
    import urllib.error
    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 429, "x", {}, io.BytesIO(b"RESOURCE_EXHAUSTED"))
    monkeypatch.setattr(r.urllib.request, "urlopen", boom)
    monkeypatch.setenv("VERTEX_API_KEY", "k")
    monkeypatch.setenv("VERTEX_PROJECT", "p")
    v = r.VertexProvider()
    assert v.run(v.resolve("gemini-4-carbon-high"), "sandbox", "q", Path("."), 5).status == "skipped_quota"
