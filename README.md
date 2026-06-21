# nputop

**NPU + System Monitor for Qualcomm IQ8 (QCS8300 / Hexagon V75 HTP)**

A terminal dashboard (`htop`-style) for monitoring on-device LLM inference on the
Qualcomm Dragonwing IQ8. Designed around the constraint that the Hexagon V75 HTP
**does not expose a live utilization counter** — there are no `/sys` nodes for NPU
load like a GPU would have. Instead, `nputop` wraps your inference runner and parses
QNN profiling output in real-time, stitching it together with CPU, DRAM, and thermal
metrics into a single live dashboard.

---

## Dashboard layout

```
┌─ nputop v0.1.0 — QCS8300 / Hexagon V75 HTP ─────────── 14:32:07 ┐
│── NPU  (Hexagon V75 HTP) ──────────────────────────────────────── │
│  Prefill 106.6 tok/s   Decode 88.3 tok/s   runs: 12              │
│  HTP dispatch 9.4 ms   decode/tok 11.2 ms                         │
│  tok/s history          ▂▄▅▆▇█▇▆▅▇██                             │
│── op breakdown ──────────────────────────────────────────────────  │
│  MatMul               3.142 ms  ████████████████████              │
│  Conv2d               1.204 ms  ████████                           │
│── Memory ─────────────────────────────────────────────────────── │
│  DRAM  ████████████░░░░░░░░░░  8.2 / 10.8 GB  avail 2.6 GB      │
│  ION/DMA heap  ██░░░░░░░░░░░░  0.61 GB  (QNN shared buffers)     │
│── DDR Bandwidth (vmstat proxy) ───────────────────────────────── │
│  Read 142.3 MB/s   Write 88.1 MB/s                                │
│── CPU ────────────────────────────────────────────────────────── │
│  A78 (big)    ████████████░░░░░░░░░░  61.2%   2842 MHz           │
│  A55 (LITTLE) ████░░░░░░░░░░░░░░░░░  18.4%   1766 MHz           │
│  ●cpu0 ██████ 58%  2840MHz  ●cpu1 ████  41%  2800MHz             │
│── Thermals ───────────────────────────────────────────────────── │
│  CPU    52°   NPU    48°   GPU    41°   PMIC   39°               │
│  q quit   r reset NPU stats   p pause/resume   c clear           │
└───────────────────────────────────────────────────────────────── ┘
```

---

## Usage

### 1. Passive mode (system metrics only, no inference running)
```bash
python3 nputop.py
```

### 2. Wrap your inference runner directly (recommended)
`nputop` captures stdout+stderr from your command and parses QNN output live:
```bash
python3 nputop.py --wrap "python3 run_inference.py --model smollm2"

# ExecuTorch example:
python3 nputop.py --wrap \
  "cd ~/executorch && python3 -m examples.models.llama.runner \
   --checkpoint ./models/smollm2-135m.pte --prompt 'Hello'"

# llama.cpp with QNN:
python3 nputop.py --wrap "./llama.cpp/build/bin/llama-cli -m model.gguf -p 'Hello'"
```

### 3. Named pipe / log file mode
If you want to run inference separately and tail its output:
```bash
# Terminal 1: create pipe and run inference
mkfifo /tmp/qnn.pipe
python3 run_inference.py 2>&1 | tee /tmp/qnn.pipe

# Terminal 2: launch nputop pointed at the pipe
python3 nputop.py --qnn-log /tmp/qnn.pipe
```

Or with a log file (supports re-runs; nputop tails from end):
```bash
python3 run_inference.py 2>&1 | tee /tmp/qnn.log
python3 nputop.py --qnn-log /tmp/qnn.log
```

### 4. Faster refresh rate
```bash
python3 nputop.py --wrap "..." --refresh 0.5
```

---

## Keybindings

| Key | Action |
|-----|--------|
| `q` | Quit |
| `p` | Pause/resume UI updates |
| `c` | Clear NPU stats (reset tok/s history, op breakdown) |
| `r` | Toggle raw inference output panel |

---

## What's being measured

### NPU panel
Since the Hexagon V75 HTP has no live utilization register, all NPU metrics come from
**QNN profiling output** printed by ExecuTorch to stdout/stderr. `nputop` parses:

- `tokens per second` (prefill and decode)
- `HTP inference time` / `QNN_EXECUTE_COMPLETION_EVENT latency_us`
- `decode time per token`
- Per-op timing: `op_name=Conv2d,time=1234us` style lines

The sparkline shows tok/s across the last 60 inference runs.

### Memory panel
- **DRAM**: `/proc/meminfo` — total, used, available, cached
- **Swap**: `/proc/meminfo`
- **ION/DMA heap**: `/proc/<pid>/smaps` — shared memory buffers between CPU and HTP.
  This is how QNN allocates tensors that the NPU DMA engine can access directly.
  Processes named `et_run`, `qnn`, `python3`, or `runner` are tracked.

### DDR Bandwidth panel
The QCS8300 BSP **does not expose a DDR devfreq node** (only `1d84000.ufs` and
`3d00000.gpu` appear under `/sys/class/devfreq/`). Instead, `nputop` uses
`/proc/vmstat` pgpgin/pgpgout page fault rates as a coarse bandwidth proxy.
GPU devfreq is shown as a bonus metric.

### CPU panel
- Per-core utilization from `/proc/stat` deltas
- Per-core frequency from `/sys/devices/system/cpu/cpuN/cpufreq/scaling_cur_freq`
- Cluster summary: A78 (big, cores 0–3) and A55 (LITTLE, cores 4–7) averages

### Thermals panel
All `/sys/class/thermal/thermal_zone*` entries with readable temperatures.
Zone types are auto-labeled (CPU, NPU, GPU, DDR, PMIC, etc.).

---

## Enabling QNN profiling in ExecuTorch

ExecuTorch's QNN backend supports profiling levels. To get per-op timing:

```python
# In your runner or QnnExecutionContext setup:
qnn_executorch_options = QnnExecuTorchOptions(
    ...
    profile_level=QnnExecuTorchProfileLevel.kProfileDetailed,
)
```

Or via the `et_run` binary:
```bash
./et_run --model_path smollm2.pte --qnn_profiling_level=2
```

At level 2 (detailed), per-op timing lines appear in output that `nputop` will parse.

---

## Architecture

```
nputop/
├── nputop.py              # main TUI loop (curses), arg parsing, subprocess wrapper
├── collectors/
│   ├── cpu.py             # /proc/stat + /sys/devices/system/cpu
│   ├── memory.py          # /proc/meminfo + smaps ION heap tracking
│   ├── thermal.py         # /sys/class/thermal/thermal_zone*
│   ├── ddr.py             # /proc/vmstat + /sys/class/devfreq/3d00000.gpu
│   └── qnn.py             # QNN profiling stdout parser (regex + rolling state)
└── ui/
    └── panels.py          # curses drawing functions, color pairs, bar/sparkline
```

---

## Requirements

- Python 3.8+ (tested on 3.12.3)
- `curses` (stdlib, always present on Linux)
- No external dependencies

---

## Known limitations

1. **No true NPU utilization %** — the Hexagon V75 HTP firmware does not expose a
   real-time utilization counter. The NPU panel shows what QNN profiling actually
   measures: dispatch latency and per-op timing.
2. **DDR bandwidth is approximate** — vmstat page rates reflect OS-level I/O, not
   raw LPDDR bus bandwidth. A future version could use `perf mem` events if the BSP
   exposes the relevant PMU counters.
3. **ION heap tracking** — requires the nputop process to have read access to
   `/proc/<pid>/smaps` of the inference process. If running inference as root, run
   nputop as root too (or adjust permissions).
