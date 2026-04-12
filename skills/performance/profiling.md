# Profiling

Reference file for `performance` skill. CPU/memory profiling, flame graphs, hotspot identification across languages.

---

## Per-Language Tools

| Language | CPU Profiler | Memory Profiler | Flame Graphs |
|----------|-------------|-----------------|--------------|
| Python | cProfile, py-spy, scalene | tracemalloc, memory_profiler, objgraph | py-spy -> flamegraph |
| JavaScript/TS | --prof, clinic.js, 0x | --inspect + DevTools heap snapshot | 0x -> flamegraph |
| PHP | Xdebug profiler, SPX, Blackfire | Xdebug trace + memory | Blackfire -> flamegraph |
| Go | pprof (runtime/pprof) | pprof heap profile | go tool pprof -> flamegraph |
| Rust | cargo-flamegraph, perf | DHAT (Valgrind), heaptrack | cargo flamegraph |
| Java | async-profiler, JFR | JFR heap analysis, VisualVM | async-profiler -> flamegraph |
| C/C++ | perf, gprof, Valgrind | Valgrind massif, AddressSanitizer | perf -> flamegraph |

### Quick-Start Commands

**Python:**
```bash
# CPU profile (non-invasive, attaches to running process)
py-spy record -o profile.svg --pid <PID>

# CPU profile (script)
python -m cProfile -o output.prof script.py
# View: python -m pstats output.prof

# Memory
python -c "import tracemalloc; tracemalloc.start(); <your code>; snapshot = tracemalloc.take_snapshot(); top_stats = snapshot.statistics('lineno'); print(top_stats[:10])"

# Scalene (CPU + memory + GPU in one tool)
scalene script.py
```

**JavaScript/Node.js:**
```bash
# CPU profile
node --prof app.js
node --prof-process isolate-*.log > processed.txt

# Clinic.js (auto-detects bottleneck type)
npx clinic doctor -- node app.js

# 0x flamegraph
npx 0x app.js
```

**Go:**
```bash
# CPU profile (built into test)
go test -cpuprofile cpu.prof -bench .
go tool pprof -http=:8080 cpu.prof

# HTTP server (add to main)
import _ "net/http/pprof"
# Then: go tool pprof http://localhost:6060/debug/pprof/profile?seconds=30
```

**PHP:**
```bash
# Xdebug profiler (add to php.ini)
xdebug.mode=profile
xdebug.output_dir=/tmp/xdebug
# View with KCachegrind/QCachegrind

# SPX (low overhead, web UI)
# Enable: SPX_ENABLED=1 SPX_KEY=dev php script.php
```

---

## 5-Phase Methodology

### Phase 1: Symptom Identification

What is slow? Be specific:
- User-reported ("the page takes 10 seconds")
- Measured (p95 response time is 2.3s, SLA is 500ms)
- Observed (CPU at 95% during peak)

If no one can articulate the symptom, there is no performance problem to solve.

### Phase 2: Baseline Measurement

Measure BEFORE changing anything:
- Record the metric you intend to improve (response time, throughput, memory usage)
- Record the conditions (concurrency, data volume, hardware)
- Record the tool and command used (reproducible)

```
Baseline: p95 response time = 1,200ms at 50 concurrent users
Tool: hey -n 1000 -c 50 http://localhost:8080/api/products
Date: YYYY-MM-DD
```

### Phase 3: Profile

Run the appropriate profiler. Collect data. Do not guess.

**Decision tree:**
```
Slow overall?
  -> CPU profile first (cProfile / py-spy / --prof / pprof)

High memory?
  -> Memory profile (tracemalloc / heap snapshot / pprof heap)

Intermittent slowness?
  -> Continuous profiler (py-spy / async-profiler) over 30+ seconds

I/O wait?
  -> strace / ltrace to trace system calls
  -> Check disk I/O (iostat) and network (ss, netstat)
```

### Phase 4: Analyze

Identify top N hotspots from profile data:

1. Sort by cumulative time (not self time) to find the call chain
2. Look for functions taking >10% of total time
3. Check call counts -- a fast function called 1M times is a hotspot
4. Distinguish CPU-bound from I/O-bound (I/O-bound shows in wait time, not CPU time)

### Phase 5: Report

Use the structured Performance Finding format from the parent skill SKILL.md.

---

## Thresholds (Defaults -- Adaptable Per Project)

| Indicator | Threshold | Action |
|-----------|-----------|--------|
| Function >10% of total CPU time | Hotspot | Investigate and optimize |
| Memory allocation >100MB for single request | Investigate | Check for leaks, unnecessary copies |
| GC pause >50ms | Investigate | Tune GC parameters or reduce allocation rate |
| I/O wait >30% of request time | I/O bound | Optimize I/O, not CPU. Cache, batch, or async. |
| Single function >1M calls per request | Call count hotspot | Reduce call frequency, cache results |
| Memory growth over time (no plateau) | Memory leak | Profile allocations, check for retained references |

### When to Override Defaults

- **Latency-critical systems** (trading, real-time): tighten all thresholds by 2-5x
- **Batch processing**: relax response time thresholds, focus on throughput
- **Resource-constrained environments** (embedded, edge): tighten memory thresholds
- **COMPONENT.md has performance budget**: use those targets instead of defaults

---

## Cross-Platform Notes

### Linux
- `perf` -- hardware performance counters, kernel-level profiling
- `strace` -- trace system calls (I/O patterns)
- `valgrind --tool=callgrind` -- instruction-level profiling (slow but precise)
- Flame graphs: `perf record -g` then `FlameGraph/stackcollapse-perf.pl`

### Windows
- ETW (Event Tracing for Windows) -- system-wide tracing
- dotnet-trace -- .NET profiling
- Process Monitor -- file/registry/network activity
- Visual Studio Profiler -- integrated CPU/memory

### Docker
- **Profile from host**: `perf record -p <container_pid>` (requires SYS_ADMIN or --privileged)
- **Profile inside container**: install profiler in image, run normally
- **py-spy from host**: `py-spy record --pid <host_pid_of_python_process>`
- Note: container PID namespace means host PIDs differ from container PIDs. Use `docker inspect` to find the host PID.

---

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Profile in debug mode | Debug builds add overhead that distorts profiles |
| Profile with too-small data | Profiling a 10-row table tells you nothing about 10M rows |
| Optimize before profiling | You will optimize the wrong thing 80% of the time |
| Trust a single profile run | Variance exists. Run 3+ times and look at patterns. |
| Ignore I/O wait | High CPU is not always the problem. Check I/O. |
| Read flame graphs bottom-up | Read top-down. Wide bars at the top = most total time. |
