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

# Memory profile
python -m memory_profiler script.py
# tracemalloc in code:
import tracemalloc; tracemalloc.start(); ...; print(tracemalloc.get_traced_memory())
```

**Node.js:**
```bash
# CPU profile
node --prof app.js
node --prof-process isolate-*.log > processed.txt

# Flame graph
0x app.js
# Generates flamegraph.html after stopping the process

# Memory
node --inspect app.js
# Attach Chrome DevTools, take heap snapshot
```

**PHP:**
```bash
# Xdebug profiler
# In php.ini: xdebug.mode=profile; xdebug.output_dir=/tmp
# Run request, view cachegrind.out.* in KCacheGrind or qcachegrind

# SPX (simpler, web UI)
# Enable via ?SPX_UI_URI=/_spx header, view in browser

# Blackfire (paid, production-safe)
blackfire run php script.php
```

**Go:**
```bash
# CPU profile
go test -cpuprofile=cpu.prof -bench=.
go tool pprof cpu.prof

# Memory profile
go test -memprofile=mem.prof -bench=.
go tool pprof -alloc_space mem.prof

# Live profile (with net/http/pprof)
go tool pprof http://localhost:6060/debug/pprof/profile?seconds=30
```

**Java:**
```bash
# async-profiler (low overhead, attach to running JVM)
./profiler.sh -d 30 -f flame.html <PID>

# JFR (built into JDK)
jcmd <PID> JFR.start duration=60s filename=recording.jfr
jmc  # Java Mission Control for analysis
```

---

## Profile Analysis Methodology

### Step 1: Identify the Top 3 Hotspots

```
From the profile output, find the 3 functions consuming the most CPU time.
Order matters: the top hotspot is where optimization yields the most gain.
```

### Step 2: Classify Each Hotspot

| Classification | Signal | Optimization approach |
|---------------|--------|----------------------|
| Algorithmic (O(n^2) or worse) | Time grows quadratically with input | Replace with better algorithm |
| I/O-bound waiting | High wall time, low CPU | Add concurrency or caching |
| CPU-bound loop | High CPU, sequential logic | Vectorize, parallelize, or cache results |
| Memory allocation | Heap churn visible in memory profile | Reuse objects, pool, or switch to stack |
| External call | Spends time in HTTP/DB client | Batch, cache, or make async |

### Step 3: Measure, Change, Re-measure

```
1. Record baseline (exact numbers)
2. Apply one change
3. Re-run the same profile
4. Compare: did the hotspot shrink? Did a new hotspot appear?
5. If no improvement: revert, try next candidate
```

### Step 4: Avoid Micro-Optimization

Don't optimize functions that don't appear in the top 10 of the profile. Micro-optimizations of cold code waste effort and add complexity.

---

## Flame Graph Interpretation

A flame graph shows call stacks vertically (caller at bottom, callee at top) with width proportional to time spent.

### What to look for

| Pattern | Meaning |
|---------|---------|
| Wide plateaus at the top | Leaf functions consuming significant time |
| Many thin spikes | No single hotspot; possibly death by a thousand cuts |
| Wide blocks with deep stacks | Call overhead or recursion |
| Unexpected libraries | Import-time work or unintended calls |
| Repeated patterns across stacks | Same bottleneck hit from multiple paths |

### Common Anti-Patterns Visible in Flame Graphs

- Serialization/deserialization taking >20% of the profile -> switch formats or cache parsed data
- Logging visible in hot loops -> remove or batch
- String concatenation in inner loops -> use buffers or join
- Recursive JSON/XML traversal -> iterative or typed access
- Database client overhead -> connection pooling or batch queries

---

## Memory Profiling Patterns

### Memory Leak Detection

```
1. Record baseline memory usage after warmup
2. Apply load for N minutes
3. Force GC, record memory
4. Repeat. If memory grows each cycle, there's a leak.
```

### Common Leak Sources

| Language | Common leak |
|----------|-------------|
| Python | Circular references with __del__, unclosed resources, global caches |
| Node.js | Event listeners not removed, closures capturing large objects |
| Java | Static collections growing unbounded, listeners not deregistered |
| Go | Goroutine leaks (goroutines blocked on channels), slices holding refs |
| Rust | Rc cycles, unbounded Vec growth, Arc leaks |

### Heap Snapshot Comparison

```
1. Take heap snapshot at baseline
2. Perform the suspicious operation
3. Take heap snapshot again
4. Diff: objects that appeared but weren't GCed are suspect
```

Node.js Chrome DevTools and JVM VisualVM both support this natively.

---

## Hotspot Hunting Checklist

1. [ ] Profile ran for long enough (>30 seconds for representative data)
2. [ ] Profile captured realistic workload (not just startup or tests)
3. [ ] Top 3 hotspots identified with numbers
4. [ ] Each hotspot classified (algorithmic/IO/CPU/memory/external)
5. [ ] Optimization applied to the top hotspot only
6. [ ] Re-profile shows the hotspot shrank
7. [ ] Finding logged to `_meta/perf-findings.jsonl`

---

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Profile only in development | Dev workload differs from production. Profile staging or production-like load. |
| Optimize functions not in the profile's top N | You're optimizing cold code. No user-visible impact. |
| Profile without warmup | JIT, caches, and pools behave differently after warmup. Skewed results. |
| Use a sampling profiler for short-lived code | Samples miss short functions. Use tracing profilers for short code paths. |
| Profile on different hardware than production | Ratios may match but absolute numbers do not. Pin to similar specs. |
| Skip memory profiling for "just CPU" issues | High CPU is often a symptom of memory pressure (GC, allocation churn). |
