"""local_bench: every task's reference passes its own tests, a wrong answer fails, code extraction."""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import bench_tasks  # noqa: E402
import local_bench  # noqa: E402


def test_every_reference_passes_its_tests():
    for t in bench_tasks.TASKS:
        assert local_bench.grade(t["reference"], t["tests"])[:2] == (len(t["tests"]),) * 2, t["id"]


def test_longctx_reference_passes_and_retired_rule_fails():
    ref = bench_tasks.LONGCTX_REFERENCE
    n = len(bench_tasks.LONGCTX_TESTS)
    assert local_bench.grade(ref, bench_tasks.LONGCTX_TESTS, bench_tasks.LONGCTX_SUPPORT)[:2] == (n, n)
    retired = ref.replace("prior_orders >= 5", "prior_orders >= 3").replace("* 7 / 100", "* 5 / 100")
    assert local_bench.grade(retired, bench_tasks.LONGCTX_TESTS, bench_tasks.LONGCTX_SUPPORT)[0] < n


def test_longctx_prompt_holds_every_fact():
    p = bench_tasks.build_longctx(50000)
    for path, _ in bench_tasks.LONGCTX_FACTS:
        assert f"=== FILE: {path} ===" in p
    assert len(p) > 50000


def test_extract_code_and_empty_answer():
    text = "<think>```python\ndef wrap(): pass\n```</think>\n```python\ndef other(): pass\n```\n```python\ndef wrap(t, w):\n    return []\n```"
    assert "return []" in local_bench.extract_code(text, "wrap")
    assert local_bench.grade("", ["assert True"]) == (0, 1, "no code block")


def test_grade_survives_crashing_and_looping_code():
    assert local_bench.grade("raise SystemExit(3)", ["assert True"])[0] == 0
    assert local_bench.grade("while True: pass", ["assert True"], timeout=5)[2] == "grader timeout"


# ---- LiveCodeBench suite (synthetic rows; no network) ----
import base64, json, pickle, zlib  # noqa: E402
import lcb_suite  # noqa: E402


def _packed(cases):
    return base64.b64encode(zlib.compress(pickle.dumps(json.dumps(cases)))).decode()


def _row(qid, starter="", func="", cases=(), diff="easy", date="2025-02-01T00:00:00"):
    return {"question_id": qid, "question_title": qid, "question_content": "Add the numbers.",
            "platform": "leetcode" if starter else "atcoder", "contest_date": date, "difficulty": diff,
            "starter_code": starter, "metadata": json.dumps({"func_name": func} if func else {}),
            "public_test_cases": "[]", "private_test_cases": _packed(list(cases))}


def test_lcb_stdin_and_functional_grading():
    stdin = _row("s1", cases=[{"input": "1 2\n", "output": "3\n", "testtype": "stdin"},
                              {"input": "0.5 0.25\n", "output": "0.75", "testtype": "stdin"}])
    good = "a, b = map(float, input().split())\nr = a + b\nprint(int(r) if r == int(r) else r)\n"
    assert lcb_suite.grade(stdin, good)[:2] == (2, 2)
    assert lcb_suite.grade(stdin, "print(0)")[0] == 0
    fn = _row("f1", starter="class Solution:\n    def add(self, a: int, b: List[int]) -> List[int]:\n", func="add",
              cases=[{"input": "1\n[2, 3]", "output": "[3, 4]", "testtype": "functional"}])
    ok = "class Solution:\n    def add(self, a, b):\n        return tuple(a + x for x in b)\n"
    assert lcb_suite.grade(fn, ok)[:2] == (1, 1)
    assert lcb_suite.grade(fn, ok.replace("a + x", "x"))[0] == 0
    assert "starter code" in lcb_suite.prompt(fn) and "stdin" in lcb_suite.prompt(stdin)


def test_lcb_refuses_pickled_objects():
    evil = base64.b64encode(zlib.compress(pickle.dumps(print))).decode()
    try:
        lcb_suite.decode_tests(evil)
        raise AssertionError("pickled global was loaded")
    except pickle.UnpicklingError:
        pass


def test_lcb_selection_is_stable_and_date_filtered():
    rows = {f"q{i}": _row(f"q{i}", diff=("easy", "medium", "hard")[i % 3],
                          date="2024-12-01T00:00:00" if i < 3 else "2025-02-01T00:00:00") for i in range(30)}
    a = lcb_suite.select(rows, "2025-01-01", 4, "seed")
    assert a == lcb_suite.select(rows, "2025-01-01", 4, "seed") and len(a) == 12
    assert not {"q0", "q1", "q2"} & set(a)
    assert a != lcb_suite.select(rows, "2025-01-01", 4, "other-seed")
