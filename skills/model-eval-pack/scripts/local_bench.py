#!/usr/bin/env python3
"""Baseline benchmark for a local OpenAI-compatible model server (Strata, llama.cpp, vLLM ...).

Run it ON the serving host (it reads the host's GPUs, RAM and the Strata launch config). Three suites:

  coding    medium and hard coding tasks (bench_tasks.TASKS); the answer's code is run against test
            cases in a separate, time- and memory-limited `python3 -I` process. Pass = every case.
  longctx   a coding task whose rules are spread through a synthetic codebase of ~N prompt tokens
            (default 117000 and 228000); graded by tests the same way.
  parallel  N concurrent sessions (default 1,2,4) of the medium tasks: does every session finish and
            pass, and how much do they actually overlap (effective parallelism, aggregate tokens/s).

Every request is one CSV row in <out>/bench_runs.csv; each invocation adds one row to
<out>/bench_summary.csv with the hardware and model specs, so runs before and after a hardware
change (e.g. a second GPU) compare directly. Measurement only: a local model holds no seat.

Running model-written code: each answer runs in a temp directory under `python3 -I` with a CPU-time,
memory and wall-clock limit, no network isolation. Only run it against a model you trust that far.

usage: local_bench.py --profile 1gpu-iq3xxs-256k [--suites coding,longctx,parallel] [--repeat 2]
"""
import argparse, csv, datetime, glob, json, os, platform, re, statistics, subprocess, sys, tempfile
import threading, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench_tasks  # noqa: E402
import lcb_suite  # noqa: E402

RUN_COLS = ["run_id", "timestamp", "profile", "model", "suite", "task", "difficulty", "repeat", "concurrency",
            "prompt_tokens", "completion_tokens", "reasoning_chars", "ttft_s", "decode_tok_s", "wall_s", "finish",
            "tests_passed", "tests_total", "pass", "peak_ram_gib", "peak_vram_gib", "error"]
SUMMARY_COLS = [
    "run_id", "timestamp", "profile", "notes", "host", "cpu", "cpu_threads", "ram_gib", "gpu_count", "gpus",
    "vram_total_gib", "gpu_pcie", "nvidia_driver", "os_kernel", "engine", "engine_version", "model", "model_file",
    "context_window", "kv_format", "drafting", "server_slots", "engine_args", "max_tokens",
    "coding_pass", "coding_medium_pass", "coding_hard_pass", "coding_case_rate", "coding_median_s",
    "coding_median_decode_tok_s", "longctx_results", "longctx_max_ok_tokens", "parallel_results",
    "parallel_max_ok_sessions", "parallel_real_sessions", "parallel_best_speedup", "lcb_release", "lcb_manifest", "lcb_pass",
    "lcb_easy", "lcb_medium", "lcb_hard", "lcb_median_s", "peak_ram_gib", "peak_vram_gib", "duration_min",
    "suites"]

_THINK = re.compile(r"<think>.*?</think>\s*", re.S)
_BLOCK = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.S)


def append_csv(path, cols, row):
    """Append a row; if the file's header is an older column set, rewrite it under the new one."""
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f); old = r.fieldnames or []; rows = list(r)
        if old != cols:
            cols = cols + [c for c in old if c not in cols]
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def get_json(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def host_specs(base):
    meminfo = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            meminfo = {l.split(":")[0]: int(l.split()[1]) for l in f}
    except OSError:
        pass
    gpu_rows = [r.split(", ") for r in sh("nvidia-smi --query-gpu=name,memory.total,driver_version,"
                                         "pcie.link.width.current,pcie.link.gen.max --format=csv,noheader,nounits").splitlines() if r]
    cpu = sh("grep -m1 'model name' /proc/cpuinfo").split(":", 1)[-1].strip() or platform.processor()
    spec = {
        "host": platform.node(), "cpu": cpu, "cpu_threads": os.cpu_count(),
        "ram_gib": round(meminfo.get("MemTotal", 0) / 1048576, 1), "gpu_count": len(gpu_rows),
        "gpus": " + ".join(r[0] for r in gpu_rows),
        "vram_total_gib": round(sum(float(r[1]) for r in gpu_rows) / 1024, 1) if gpu_rows else 0,
        "gpu_pcie": " + ".join(f"x{r[3]} gen{r[4]}" for r in gpu_rows if len(r) > 4),
        "nvidia_driver": gpu_rows[0][2] if gpu_rows else "",
        "os_kernel": f"{sh('. /etc/os-release && echo $PRETTY_NAME')} / {platform.release()}",
        "engine": "", "engine_version": "", "model": "", "model_file": "", "context_window": "",
        "kv_format": "", "drafting": "", "server_slots": ""}
    try:
        health = get_json(base.rsplit("/v1", 1)[0] + "/health")
        spec["model"] = health.get("model", "")
        spec["context_window"] = health.get("max_context", "")
        spec["engine"] = health.get("service", "")
    except Exception as exc:
        health = {"error": repr(exc)}
    ver = sh("strata --version || ~/.local/bin/strata --version")
    if ver:
        spec["engine"] = spec["engine"] or "strata"
        spec["engine_version"] = ver.split(" (")[0] + (" " + ver.split("(")[1].split(";")[0] if "(" in ver else "")
    # Engine settings: the running Strata engine's own command line, else the newest launch config.
    args = []
    for line in sh("ps -eo args").splitlines():
        if " --serve" in line and "--pack" in line:
            args = line.split(); break
    if not args:
        confs = sorted(glob.glob(os.path.expanduser("~/.local/state/strata/launch/*.json")), key=os.path.getmtime)
        for path in reversed(confs):
            try:
                with open(path, encoding="utf-8") as f:
                    conf = json.load(f)
            except (OSError, ValueError):
                continue
            args = conf.get("args_written") or conf.get("args") or []
            if args:
                break
    opt = {args[i]: args[i + 1] for i in range(len(args) - 1) if args[i].startswith("--")}
    spec["kv_format"] = opt.get("--kv", "")
    spec["drafting"] = opt.get("--draft", "mtp" if "--mtp" in opt else ("off" if args else ""))
    spec["server_slots"] = opt.get("--parallel", opt.get("--slots", "1" if opt.get("--draft") == "dflash2" else ""))
    spec["model_file"] = os.path.basename(opt.get("--native", opt.get("--model", "")))
    spec["engine_args"] = " ".join(a for a in args[1:] if not a.startswith("/")) if args else ""
    return spec


class Sampler(threading.Thread):
    """Peak RAM in use (MemTotal - MemAvailable) and summed GPU memory while it runs."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop = False; self.ram = 0; self.vram = 0

    def run(self):
        while not self.stop:
            try:
                with open("/proc/meminfo", encoding="utf-8") as f:
                    m = {l.split(":")[0]: int(l.split()[1]) for l in f}
                self.ram = max(self.ram, (m["MemTotal"] - m["MemAvailable"]) / 1048576)
                v = sh("nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits").split()
                self.vram = max(self.vram, sum(int(x) for x in v if x.isdigit()) / 1024)
            except Exception:
                pass
            time.sleep(1)


def chat(base, model, prompt, max_tokens, timeout):
    """One streamed request. Returns dict(ttft_s, wall_s, content, reasoning, usage, finish)."""
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": True,
            "max_tokens": max_tokens, "stream_options": {"include_usage": True}}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time(); first = None; content = []; reasoning = []; usage = {}; finish = None; deltas = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            d = json.loads(data)
            if d.get("usage"):
                usage = d["usage"]
            for ch in d.get("choices") or []:
                delta = ch.get("delta") or {}
                c, r = delta.get("content") or "", delta.get("reasoning_content") or ""
                if c or r:
                    first = first or time.time(); deltas += 1
                content.append(c); reasoning.append(r)
                finish = ch.get("finish_reason") or finish
    t1 = time.time()
    ctok = usage.get("completion_tokens") or deltas
    tf = first or t1
    return {"ttft_s": round(tf - t0, 2), "wall_s": round(t1 - t0, 1), "content": "".join(content),
            "reasoning": "".join(reasoning), "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": ctok, "decode_tok_s": round(ctok / max(t1 - tf, 1e-6), 1), "finish": finish}


def extract_code(text, defines):
    """The last fenced block that defines every name in `defines`, else the last block, else ''."""
    text = _THINK.sub("", text)
    blocks = _BLOCK.findall(text)
    names = [n.strip() for n in defines.split(",") if n.strip()]
    for b in reversed(blocks if names else []):
        if all(re.search(rf"^\s*(def|class)\s+{re.escape(n)}\b", b, re.M) for n in names):
            return b
    return blocks[-1] if blocks else ""


RUNNER = r'''
import json, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))
resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
src = open(sys.argv[1], encoding="utf-8").read()
tests = json.load(open(sys.argv[2], encoding="utf-8"))
res = []
ns = {"__name__": "solution"}
try:
    exec(compile(src, "solution.py", "exec"), ns)
except BaseException as e:
    print(json.dumps({"results": [False] * len(tests), "error": "load: " + repr(e)[:200]})); sys.exit()
first_err = ""
for t in tests:
    try:
        exec(compile(t, "test", "exec"), dict(ns)); res.append(True)
    except BaseException as e:
        res.append(False); first_err = first_err or repr(e)[:200]
print(json.dumps({"results": res, "error": first_err}))
'''


def grade(code, tests, prelude="", timeout=150):
    """Run code + tests in a limited subprocess. Returns (passed, total, error)."""
    if not code.strip():
        return 0, len(tests), "no code block"
    with tempfile.TemporaryDirectory(prefix="bench-") as d:
        for name, text in (("solution.py", prelude + "\n" + code), ("runner.py", RUNNER),
                           ("tests.json", json.dumps(tests))):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(text)
        try:
            p = subprocess.run([sys.executable, "-I", "runner.py", "solution.py", "tests.json"], cwd=d,
                               capture_output=True, text=True, timeout=timeout)
            out = json.loads(p.stdout.strip().splitlines()[-1])
        except subprocess.TimeoutExpired:
            return 0, len(tests), "grader timeout"
        except Exception as exc:
            return 0, len(tests), f"grader: {exc!r}"[:200]
    return sum(out["results"]), len(tests), out.get("error", "")


def coding_prompt(task):
    return ("Advisory only - do not use any tools. " + task["prompt"] + " Use only the Python standard "
            "library. Answer with exactly one ```python code block containing the complete implementation "
            "(no tests, no example usage), then stop.")


class Bench:
    def __init__(self, a, spec):
        self.a = a; self.spec = spec; self.model = a.model or spec["model"]
        self.run_id = datetime.datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + a.profile
        self.rows = []; self.lock = threading.Lock()
        os.makedirs(a.out, exist_ok=True)
        self.raw_dir = os.path.join(a.out, "raw", self.run_id); os.makedirs(self.raw_dir, exist_ok=True)

    def record(self, row, text=""):
        row = {"run_id": self.run_id, "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
               "profile": self.a.profile, "model": self.model, **row}
        with self.lock:
            self.rows.append(row)
            append_csv(os.path.join(self.a.out, "bench_runs.csv"), RUN_COLS, row)
            if text:
                name = f"{row['suite']}.{row['task']}.c{row.get('concurrency', 1)}.r{row.get('repeat', 1)}.md"
                with open(os.path.join(self.raw_dir, name), "w", encoding="utf-8") as f:
                    f.write(text)
        print(json.dumps({k: row.get(k) for k in ("suite", "task", "concurrency", "prompt_tokens", "ttft_s",
                                                    "wall_s", "tests_passed", "tests_total", "pass", "error")}),
              flush=True)

    def one(self, suite, task_id, difficulty, prompt, defines, tests, prelude="", rep=1, conc=1, max_tokens=None,
            grader=None):
        s = Sampler(); s.start()
        row = {"suite": suite, "task": task_id, "difficulty": difficulty, "repeat": rep, "concurrency": conc}
        text = ""
        try:
            r = chat(self.a.base_url, self.model, prompt, max_tokens or self.a.max_tokens, self.a.timeout)
            text = r["reasoning"] + "\n\n----- ANSWER -----\n\n" + r["content"]
            code = extract_code(r["content"], defines)
            passed, total, err = grader(code) if grader else grade(code, tests, prelude)
            if r["finish"] not in (None, "stop"):
                err = (f"finish={r['finish']}; " + err).strip("; ")
            row.update({k: r[k] for k in ("prompt_tokens", "completion_tokens", "ttft_s", "decode_tok_s",
                                          "wall_s", "finish")},
                       reasoning_chars=len(r["reasoning"]), tests_passed=passed, tests_total=total,
                       error=err, **{"pass": passed == total})
        except Exception as exc:
            row.update(tests_passed=0, tests_total=len(tests) if tests else "", error=repr(exc)[:300],
                       **{"pass": False})
        s.stop = True; s.join(3)
        row.update(peak_ram_gib=round(s.ram, 1), peak_vram_gib=round(s.vram, 1))
        self.record(row, text)
        return row

    # ---- suites ----
    def coding(self):
        for rep in range(1, self.a.repeat + 1):
            for t in bench_tasks.TASKS:
                self.one("coding", t["id"], t["difficulty"], coding_prompt(t), t["defines"], t["tests"], rep=rep)

    def chars_per_token(self):
        probe = bench_tasks.build_longctx(60000)
        r = chat(self.a.base_url, self.model, probe, 1, self.a.timeout)
        return len(probe) / max(r["prompt_tokens"] or 1, 1)

    def longctx(self):
        window = int(self.spec.get("context_window") or 0)
        cpt = self.chars_per_token()
        print(json.dumps({"chars_per_token": round(cpt, 3), "context_window": window}), flush=True)
        for target in self.a.longctx_tokens:
            room = window - target - 512 if window else self.a.max_tokens
            if room < 2048:
                self.record({"suite": "longctx", "task": f"invoice@{target // 1000}k", "difficulty": "longctx",
                             "repeat": 1, "concurrency": 1, "tests_total": len(bench_tasks.LONGCTX_TESTS),
                             "tests_passed": 0, "pass": False,
                             "error": f"skipped: {target} tokens do not fit window {window}"})
                continue
            prompt = bench_tasks.build_longctx(int((target - 400) * cpt))
            for rep in range(1, self.a.longctx_repeat + 1):
                self.one("longctx", f"invoice@{target // 1000}k", "longctx", prompt, "invoice_total",
                         bench_tasks.LONGCTX_TESTS, prelude=bench_tasks.LONGCTX_SUPPORT, rep=rep,
                         max_tokens=min(self.a.max_tokens, room))

    def parallel(self):
        pool = [t for t in bench_tasks.TASKS if t["difficulty"] == "medium"]
        self.par = []
        for n in self.a.parallel_levels:
            out = [None] * n
            def worker(i):
                t = pool[i % len(pool)]
                out[i] = self.one("parallel", t["id"], t["difficulty"], coding_prompt(t), t["defines"],
                                  t["tests"], rep=i + 1, conc=n)
            t0 = time.time()
            th = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
            [x.start() for x in th]; [x.join() for x in th]
            wall = time.time() - t0
            ok = all(r and not str(r.get("error", "")).startswith(("HTTP", "<HTTP", "URLError", "Timeout"))
                     and r.get("wall_s") for r in out)
            passed = sum(1 for r in out if r and r["pass"])
            busy = sum(float(r.get("wall_s") or 0) for r in out)
            toks = sum(int(r.get("completion_tokens") or 0) for r in out)
            agg = toks / wall if wall else 0
            base = self.par[0]["agg_tok_s"] if self.par and self.par[0]["n"] == 1 else None
            # Speedup = aggregate output tokens/s against one session. A server that queues
            # requests stays near 1.0 however many sessions are open; queue wait shows as TTFT.
            self.par.append({"n": n, "completed": ok, "passed": passed,
                             "speedup": round(agg / base, 2) if base else (1.0 if n == 1 else None),
                             "agg_tok_s": round(agg, 1), "wall_s": round(wall, 1),
                             "max_ttft_s": max(float(r.get("ttft_s") or 0) for r in out if r),
                             "overlap": round(busy / wall, 2)})
            print(json.dumps({"parallel": self.par[-1]}), flush=True)

    def lcb(self):
        a = self.a
        man, rows = lcb_suite.manifest(a.out, a.lcb_release, os.path.expanduser(a.lcb_cache), a.lcb_since,
                                       a.lcb_per_difficulty, a.lcb_seed)
        self.lcb_man = man
        print(json.dumps({"lcb": {k: man[k] for k in ("release", "since", "dates", "manifest_sha256")},
                          "problems": len(man["ids"])}), flush=True)
        for rep in range(1, a.lcb_repeat + 1):
            for qid in man["ids"]:
                row = rows[qid]
                self.one("lcb", qid, row["difficulty"], lcb_suite.prompt(row),
                         "Solution" if row["starter_code"].strip() else "", None, rep=rep,
                         grader=lambda code, row=row: lcb_suite.grade(row, code))

    # ---- summary ----
    def lcb_summary(self, rows):
        man = getattr(self, "lcb_man", None)
        lr = [r for r in rows if r["suite"] == "lcb"]
        if not man:
            return {}
        frac = lambda rs: f"{sum(1 for r in rs if r['pass'])}/{len(rs)}"
        meds = sorted(float(r["wall_s"]) for r in lr if r.get("wall_s"))
        return {"lcb_release": f"{man['release']} {man['dates'][0][:10]}..{man['dates'][1][:10]}",
                "lcb_manifest": man["manifest_sha256"], "lcb_pass": frac(lr),
                **{f"lcb_{d}": frac([r for r in lr if r["difficulty"] == d]) for d in ("easy", "medium", "hard")},
                "lcb_median_s": round(meds[len(meds) // 2], 1) if meds else ""}

    def summary(self, started):
        rows = self.rows
        cod = [r for r in rows if r["suite"] == "coding"]
        def frac(rs):
            return f"{sum(1 for r in rs if r['pass'])}/{len(rs)}"
        cases = sum(int(r.get("tests_passed") or 0) for r in cod), sum(int(r.get("tests_total") or 0) for r in cod)
        lc = [r for r in rows if r["suite"] == "longctx"]
        lc_txt = "; ".join(f"{r['task']}: {r.get('prompt_tokens') or '-'} tok, "
                           f"{'pass' if r['pass'] else 'FAIL'} {r.get('tests_passed')}/{r.get('tests_total')}, "
                           f"ttft {r.get('ttft_s') or '-'}s" + (f" ({r['error'][:60]})" if r.get("error") else "")
                           for r in lc)
        lc_ok = max([int(r.get("prompt_tokens") or 0) for r in lc if r["pass"]] or [0])
        par = getattr(self, "par", [])
        par_txt = "; ".join(f"n={p['n']}: {'ok' if p['completed'] else 'ERR'} {p['passed']}/{p['n']} pass, "
                            f"speedup {p['speedup']}x, {p['agg_tok_s']} tok/s, max ttft {p['max_ttft_s']}s"
                            for p in par)
        par_ok = max([p["n"] for p in par if p["completed"]] or [0])
        # Sessions that really run together: the largest n whose speedup is at least 0.75 n.
        par_real = max([p["n"] for p in par if p["completed"] and p["speedup"] and p["speedup"] >= 0.75 * p["n"]]
                       or [0])
        med = lambda xs: round(statistics.median(xs), 1) if xs else ""
        row = {"run_id": self.run_id, "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
               "profile": self.a.profile, "notes": self.a.notes, **self.spec, "model": self.model,
               "max_tokens": self.a.max_tokens,
               "coding_pass": frac(cod) if cod else "",
               "coding_medium_pass": frac([r for r in cod if r["difficulty"] == "medium"]) if cod else "",
               "coding_hard_pass": frac([r for r in cod if r["difficulty"] == "hard"]) if cod else "",
               "coding_case_rate": f"{cases[0]}/{cases[1]}" if cod else "",
               "coding_median_s": med([float(r["wall_s"]) for r in cod if r.get("wall_s")]),
               "coding_median_decode_tok_s": med([float(r["decode_tok_s"]) for r in cod if r.get("decode_tok_s")]),
               "longctx_results": lc_txt, "longctx_max_ok_tokens": lc_ok or "",
               "parallel_results": par_txt, "parallel_max_ok_sessions": par_ok if par else "",
               "parallel_real_sessions": par_real if par else "",
               "parallel_best_speedup": max([p["speedup"] or 0 for p in par] or [""]) if par else "",
               **self.lcb_summary(rows),
               "suites": self.a.suites,
               "peak_ram_gib": max([float(r.get("peak_ram_gib") or 0) for r in rows] or [0]),
               "peak_vram_gib": max([float(r.get("peak_vram_gib") or 0) for r in rows] or [0]),
               "duration_min": round((time.time() - started) / 60, 1)}
        append_csv(os.path.join(self.a.out, "bench_summary.csv"), SUMMARY_COLS, row)
        print(json.dumps({"summary": row}, indent=1), flush=True)


COMPARE_COLS = [("profile", "profile"), ("date", "timestamp"), ("gpus", "gpus"), ("VRAM", "vram_total_gib"),
                ("RAM", "ram_gib"), ("model", "model"), ("window", "context_window"), ("kv", "kv_format"),
                ("draft", "drafting"), ("slots", "server_slots"), ("coding", "coding_pass"),
                ("hard", "coding_hard_pass"), ("decode tok/s", "coding_median_decode_tok_s"),
                ("longctx max ok", "longctx_max_ok_tokens"), ("sessions completed", "parallel_max_ok_sessions"),
                ("sessions concurrent", "parallel_real_sessions"), ("best speedup", "parallel_best_speedup"), ("LCB", "lcb_pass"), ("LCB easy", "lcb_easy"),
                ("LCB med", "lcb_medium"), ("LCB hard", "lcb_hard"), ("LCB set", "lcb_manifest"),
                ("peak RAM", "peak_ram_gib")]


def compare(out_dir):
    """One line per profile: the newest non-empty value of each column across that profile's runs."""
    path = os.path.join(out_dir, "bench_summary.csv")
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    merged = {}
    for r in rows:
        m = merged.setdefault(r["profile"], {})
        for k, v in r.items():
            if v not in ("", None):
                m[k] = v
    print("| " + " | ".join(h for h, _ in COMPARE_COLS) + " |")
    print("|" + "---|" * len(COMPARE_COLS))
    for m in merged.values():
        print("| " + " | ".join(str(m.get(k, ""))[:19] if k == "timestamp" else str(m.get(k, ""))
                                for _, k in COMPARE_COLS) + " |")


def ints(s):
    return [int(x) for x in s.split(",") if x.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-url", default=os.environ.get("LOCAL_EVAL_BASE_URL", "http://127.0.0.1:8080/v1"))
    ap.add_argument("--model", default="", help="default: the model the server's /health reports")
    ap.add_argument("--profile", default="", help="label for this hardware/launch setup, e.g. 1gpu-iq3xxs-256k")
    ap.add_argument("--notes", default="")
    ap.add_argument("--suites", default="coding,longctx,parallel")
    ap.add_argument("--repeat", type=int, default=2, help="repeats of each coding task")
    ap.add_argument("--longctx-tokens", type=ints, default=[117000, 228000])
    ap.add_argument("--longctx-repeat", type=int, default=1)
    ap.add_argument("--parallel-levels", type=ints, default=[1, 2, 4])
    ap.add_argument("--max-tokens", type=int, default=32768)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--out", default="bench-results")
    ap.add_argument("--lcb-release", default="v6", choices=sorted(lcb_suite.RELEASE_FILES))
    ap.add_argument("--lcb-since", default="2025-01-01", help="only problems from contests on or after this date")
    ap.add_argument("--lcb-per-difficulty", type=int, default=15)
    ap.add_argument("--lcb-repeat", type=int, default=1)
    ap.add_argument("--lcb-seed", default="local-bench-1")
    ap.add_argument("--lcb-cache", default="~/.cache/local-bench/lcb")
    ap.add_argument("--compare", action="store_true", help="print the summary table of every run in --out and exit")
    a = ap.parse_args(argv)
    a.base_url = a.base_url.rstrip("/")
    if a.compare:
        return compare(a.out)
    if not a.profile:
        ap.error("--profile is required (a label for this hardware/launch setup)")
    started = time.time()
    spec = host_specs(a.base_url)
    print(json.dumps({"spec": spec}, indent=1), flush=True)
    b = Bench(a, spec)
    for suite in [s.strip() for s in a.suites.split(",") if s.strip()]:
        getattr(b, suite)()
    b.summary(started)


if __name__ == "__main__":
    main()
