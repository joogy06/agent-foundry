"""LiveCodeBench (code_generation_lite) suite for local_bench.py.

Problems come from the Hugging Face dataset `livecodebench/code_generation_lite` (AtCoder and
LeetCode contest problems, each with a release date and ~40 hidden tests). The dataset is downloaded
into a cache directory at run time and never stored in the repo (its card gives the licence only as
"cc"). It is read as data: rows are parsed as JSON and the hidden tests are base64 + zlib + pickle,
which is decoded with an unpickler that refuses every class lookup, so only plain strings, lists and
dicts can come out of it.

Repeatability: the first run picks the problems (date filter, then a seeded order per difficulty)
and writes them to `<out>/lcb_manifest.json`; every later run with the same --out reuses exactly
those problem ids, so rows for different models or hardware are scored on the same problems.

Grading follows the LiveCodeBench shape: stdin problems run the program once per case and compare
stripped output lines (numbers within 1e-6 also match); functional problems call
`Solution().<func_name>(*args)` with one JSON argument per input line and compare to the JSON
output. A problem passes only when every hidden case passes (pass@1). Stops at the first failure.
"""
import base64, hashlib, io, json, os, pickle, subprocess, sys, tempfile, urllib.request, zlib

HF_URL = "https://huggingface.co/datasets/livecodebench/code_generation_lite/resolve/main/{name}"
RELEASE_FILES = {"v1": "test.jsonl", "v2": "test2.jsonl", "v3": "test3.jsonl", "v4": "test4.jsonl",
                 "v5": "test5.jsonl", "v6": "test6.jsonl"}


class _NoGlobals(pickle.Unpickler):
    def find_class(self, module, name):
        raise pickle.UnpicklingError(f"refused {module}.{name}")


def decode_tests(field):
    try:
        out = json.loads(field)
    except ValueError:
        obj = _NoGlobals(io.BytesIO(zlib.decompress(base64.b64decode(field)))).load()
        out = json.loads(obj) if isinstance(obj, str) else obj
    if not isinstance(out, list) or not all(isinstance(c, dict) and isinstance(c.get("input"), str)
                                            and isinstance(c.get("output"), str) for c in out):
        raise ValueError("unexpected test-case shape")
    return out


def fetch(release, cache_dir):
    """Return (path, sha256) of the release file, downloading it once."""
    name = RELEASE_FILES[release]
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, name)
    if not os.path.exists(path):
        tmp = path + ".part"
        with urllib.request.urlopen(HF_URL.format(name=name), timeout=600) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        os.replace(tmp, path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return path, h.hexdigest()


def load_rows(path):
    with open(path, encoding="utf-8") as f:
        return {r["question_id"]: r for r in (json.loads(l) for l in f if l.strip())}


def select(rows, since, per_difficulty, seed):
    picked = []
    for diff in ("easy", "medium", "hard"):
        pool = [q for q, r in rows.items() if r["difficulty"] == diff and r["contest_date"] >= since]
        pool.sort(key=lambda q: hashlib.sha256(f"{seed}:{q}".encode()).hexdigest())
        picked += pool[:per_difficulty]
    return picked


def manifest(out_dir, release, cache_dir, since, per_difficulty, seed):
    """Load the run's manifest, or create it. Returns (manifest dict, rows by id)."""
    path = os.path.join(out_dir, "lcb_manifest.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            man = json.load(f)
        data, sha = fetch(man["release"], cache_dir)
        if sha != man["file_sha256"]:
            raise SystemExit(f"LiveCodeBench {man['release']} file changed (sha {sha[:12]} != "
                             f"{man['file_sha256'][:12]}): results would not compare; use a new --out")
        return man, load_rows(data)
    data, sha = fetch(release, cache_dir)
    rows = load_rows(data)
    ids = select(rows, since, per_difficulty, seed)
    man = {"release": release, "file": RELEASE_FILES[release], "file_sha256": sha, "since": since,
           "per_difficulty": per_difficulty, "seed": seed, "ids": ids,
           "dates": [min(rows[q]["contest_date"] for q in ids), max(rows[q]["contest_date"] for q in ids)]}
    man["manifest_sha256"] = hashlib.sha256(json.dumps(ids).encode()).hexdigest()[:16]
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1)
    return man, rows


def prompt(row):
    head = ("You will be given a question (problem specification) and will generate a correct Python "
            "program that matches the specification and passes all tests. Do not use any tools.\n\n"
            f"Question: {row['question_content']}\n\n")
    if row["starter_code"].strip():
        return head + ("You will use the following starter code to write the solution to the problem and "
                       "enclose your code within delimiters.\n```python\n" + row["starter_code"] + "\n```\n")
    return head + ("Read the inputs from stdin, solve the problem and write the answer to stdout (do not "
                   "directly test on the sample inputs). Enclose your code within delimiters as follows. "
                   "Ensure that when the python program runs, it reads the inputs, runs the algorithm and "
                   "writes output to STDOUT.\n```python\n# YOUR CODE HERE\n```\n")


PRELUDE = ("import sys, math, heapq, bisect, itertools, functools, collections, string, re, random, operator\n"
           "from typing import *\nfrom collections import *\nfrom itertools import *\nfrom functools import *\n"
           "from heapq import *\nfrom bisect import *\nfrom math import *\nsys.setrecursionlimit(1 << 20)\n")

FUNC_RUNNER = r'''
import json, resource, signal, sys
resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))
src = open("solution.py", encoding="utf-8").read()
cases = json.load(open("cases.json", encoding="utf-8"))
func, per_case = sys.argv[1], float(sys.argv[2])
def norm(x):
    if isinstance(x, tuple):
        x = list(x)
    if isinstance(x, list):
        return [norm(v) for v in x]
    return x
def handler(*_):
    raise TimeoutError("case timeout")
signal.signal(signal.SIGALRM, handler)
ns = {"__name__": "solution"}
try:
    exec(compile(src, "solution.py", "exec"), ns)
    method = getattr(ns["Solution"](), func)
except BaseException as e:
    print(json.dumps({"passed": 0, "error": "load: " + repr(e)[:200]})); sys.exit()
passed = 0
for c in cases:
    try:
        args = [json.loads(line) for line in c["input"].split("\n") if line.strip()]
        want = json.loads(c["output"])
        signal.setitimer(signal.ITIMER_REAL, per_case)
        got = method(*args)
        signal.setitimer(signal.ITIMER_REAL, 0)
    except BaseException as e:
        signal.setitimer(signal.ITIMER_REAL, 0)
        print(json.dumps({"passed": passed, "error": f"case {passed + 1}: {e!r}"[:200]})); sys.exit()
    if norm(got) != norm(want):
        print(json.dumps({"passed": passed, "error": f"case {passed + 1}: wrong answer"})); sys.exit()
    passed += 1
print(json.dumps({"passed": passed, "error": ""}))
'''


def _same_output(got, want):
    g = [l.strip() for l in got.strip().splitlines()]
    w = [l.strip() for l in want.strip().splitlines()]
    if g == w:
        return True
    if len(g) != len(w):
        return False
    for gl, wl in zip(g, w):
        gt, wt = gl.split(), wl.split()
        if len(gt) != len(wt):
            return False
        for a, b in zip(gt, wt):
            if a == b:
                continue
            try:
                if abs(float(a) - float(b)) > 1e-6 * max(1.0, abs(float(b))):
                    return False
            except ValueError:
                return False
    return True


def _limits():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))


def grade(row, code, per_case=10.0, total=600.0):
    """Return (passed_cases, total_cases, error)."""
    cases = decode_tests(row["private_test_cases"])
    n = len(cases)
    if not code.strip():
        return 0, n, "no code block"
    with tempfile.TemporaryDirectory(prefix="lcb-") as d:
        with open(os.path.join(d, "solution.py"), "w", encoding="utf-8") as f:
            f.write(PRELUDE + "\n" + code)
        if row["starter_code"].strip():
            func = json.loads(row["metadata"] or "{}").get("func_name", "")
            with open(os.path.join(d, "cases.json"), "w", encoding="utf-8") as f:
                json.dump(cases, f)
            with open(os.path.join(d, "runner.py"), "w", encoding="utf-8") as f:
                f.write(FUNC_RUNNER)
            try:
                p = subprocess.run([sys.executable, "-I", "runner.py", func, str(per_case)], cwd=d,
                                   capture_output=True, text=True, timeout=total)
                out = json.loads(p.stdout.strip().splitlines()[-1])
            except subprocess.TimeoutExpired:
                return 0, n, "grader timeout"
            except Exception as exc:
                return 0, n, f"grader: {exc!r}"[:200]
            return out["passed"], n, out["error"]
        for i, c in enumerate(cases):
            try:
                p = subprocess.run([sys.executable, "-I", "solution.py"], cwd=d, input=c["input"],
                                   capture_output=True, text=True, timeout=per_case, preexec_fn=_limits)
            except subprocess.TimeoutExpired:
                return i, n, f"case {i + 1}: time limit"
            if p.returncode != 0:
                return i, n, f"case {i + 1}: exit {p.returncode}: {p.stderr.strip()[-160:]}"
            if not _same_output(p.stdout, c["output"]):
                return i, n, f"case {i + 1}: wrong answer"
    return n, n, ""
