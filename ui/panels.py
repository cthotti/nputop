"""
UI panels: curses rendering for each nputop dashboard section.
"""

import curses
import time


# ── Color pair IDs ────────────────────────────────────────────────────────────
C_TITLE         = 1
C_HEADER        = 2
C_OK            = 3
C_WARN          = 4
C_CRIT          = 5
C_DIM           = 6
C_ACCENT        = 7
C_BAR_FILL      = 8
C_BAR_EMPTY     = 9
C_SPARK         = 10
C_CLUSTER_BIG   = 11
C_CLUSTER_LITTLE= 12
C_ACTIVE        = 13
C_IDLE          = 14


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_TITLE,          curses.COLOR_BLACK,  curses.COLOR_CYAN)
    curses.init_pair(C_HEADER,         curses.COLOR_CYAN,   -1)
    curses.init_pair(C_OK,             curses.COLOR_GREEN,  -1)
    curses.init_pair(C_WARN,           curses.COLOR_YELLOW, -1)
    curses.init_pair(C_CRIT,           curses.COLOR_RED,    -1)
    curses.init_pair(C_DIM,            curses.COLOR_WHITE,  -1)
    curses.init_pair(C_ACCENT,         curses.COLOR_CYAN,   -1)
    curses.init_pair(C_BAR_FILL,       curses.COLOR_GREEN,  -1)
    curses.init_pair(C_BAR_EMPTY,      curses.COLOR_WHITE,  -1)
    curses.init_pair(C_SPARK,          curses.COLOR_MAGENTA,-1)
    curses.init_pair(C_CLUSTER_BIG,    curses.COLOR_CYAN,   -1)
    curses.init_pair(C_CLUSTER_LITTLE, curses.COLOR_BLUE,   -1)
    curses.init_pair(C_ACTIVE,         curses.COLOR_BLACK,  curses.COLOR_GREEN)
    curses.init_pair(C_IDLE,           curses.COLOR_BLACK,  curses.COLOR_WHITE)


# ── Drawing helpers ───────────────────────────────────────────────────────────

def _safe_addstr(win, row, col, text, attr=0):
    h, w = win.getmaxyx()
    if row < 0 or row >= h - 1:
        return
    if col >= w:
        return
    text = text[:max(0, w - col - 1)]
    try:
        win.addstr(row, col, text, attr)
    except curses.error:
        pass


def _bar(pct, width, fill="█", empty="░"):
    filled = int(round(pct / 100.0 * width))
    filled = max(0, min(width, filled))
    return fill * filled + empty * (width - filled)


def _pct_color(pct):
    if pct < 60:
        return curses.color_pair(C_OK)
    elif pct < 85:
        return curses.color_pair(C_WARN)
    else:
        return curses.color_pair(C_CRIT)


def _temp_color(t):
    if t is None:
        return curses.color_pair(C_DIM)
    if t < 60:
        return curses.color_pair(C_OK)
    elif t < 80:
        return curses.color_pair(C_WARN)
    else:
        return curses.color_pair(C_CRIT)


def _sparkline(history, width, chars=" ▁▂▃▄▅▆▇█"):
    if not history:
        return " " * width
    vals = list(history)[-width:]
    if not vals:
        return " " * width
    lo, hi = min(vals), max(vals)
    rng = hi - lo if hi != lo else 1.0
    n   = len(chars) - 1
    out = ""
    for v in vals:
        idx = int((v - lo) / rng * n)
        out += chars[max(0, min(n, idx))]
    return out.rjust(width)


def _section_header(win, row, col, width, label):
    left  = f"── {label} "
    right = "─" * max(0, width - len(left) - 1)
    line  = left + right
    _safe_addstr(win, row, col, line[:width],
                 curses.color_pair(C_HEADER) | curses.A_BOLD)
    return 1


# ── Panels ────────────────────────────────────────────────────────────────────

def draw_title(win, row, col, width, version="0.2.0"):
    now   = time.strftime("%H:%M:%S")
    left  = f" nputop v{version} — QCS8300 / Hexagon V75 HTP "
    right = f" {now} "
    pad   = " " * max(0, width - len(left) - len(right))
    title = (left + pad + right)[:width]
    _safe_addstr(win, row, col, title,
                 curses.color_pair(C_TITLE) | curses.A_BOLD)
    return 1


def draw_npu_hw(win, row, col, width, npu_data):
    """
    NPU hardware state panel — shows CDSP state, dispatch rate (IRQ proxy),
    active sessions, throttle level, board sensor.
    """
    consumed = 0
    consumed += _section_header(win, row + consumed, col, width,
                                 "NPU  (Hexagon V75 HTP — hardware signals)")

    state      = npu_data.get("cdsp_state", "unknown")
    is_active  = npu_data.get("is_active", False)
    irq_total  = npu_data.get("irq_total", 0)
    irq_delta  = npu_data.get("irq_delta", 0)
    disp_rate  = npu_data.get("dispatch_rate", 0.0)
    disp_hist  = npu_data.get("dispatch_history", [])
    fd_count   = npu_data.get("fd_count", 0)
    fd_procs   = npu_data.get("fd_procs", [])
    cdsp_pct   = npu_data.get("cdsp_cpu_pct", 0.0)
    cdsp_hist  = npu_data.get("cdsp_cpu_history", [])
    cool_cur   = npu_data.get("cool_cur", 0)
    cool_max   = npu_data.get("cool_max", 0)
    board_t1   = npu_data.get("board_temp1_c", 0.0)
    fan_rpm    = npu_data.get("fan_rpm", 0)
    sensor     = npu_data.get("sensor_name", "?")

    # ── Row 1: CDSP state badge + activity indicator ──────────────────────────
    if state == "running":
        state_attr = curses.color_pair(C_OK) | curses.A_BOLD
        state_str  = "● CDSP running"
    elif state == "offline":
        state_attr = curses.color_pair(C_DIM)
        state_str  = "○ CDSP offline"
    else:
        state_attr = curses.color_pair(C_CRIT) | curses.A_BOLD
        state_str  = f"✗ CDSP {state}"

    _safe_addstr(win, row + consumed, col + 2, state_str, state_attr)

    # Activity badge
    if is_active:
        badge     = " ◆ ACTIVE "
        badge_attr = curses.color_pair(C_ACTIVE) | curses.A_BOLD
    else:
        badge     = " ◇ IDLE   "
        badge_attr = curses.color_pair(C_IDLE)
    _safe_addstr(win, row + consumed, col + 22, badge, badge_attr)

    # Sessions
    sess_str = f"  {fd_count} session{'s' if fd_count != 1 else ''} open"
    _safe_addstr(win, row + consumed, col + 34, sess_str,
                 curses.color_pair(C_ACCENT) if fd_count > 0 else curses.color_pair(C_DIM))

    # Throttle
    if cool_cur > 0:
        th_str = f"  ⚠ THROTTLED {cool_cur}/{cool_max}"
        _safe_addstr(win, row + consumed, col + 54, th_str,
                     curses.color_pair(C_CRIT) | curses.A_BOLD)
    consumed += 1

    # ── Row 2: Dispatch rate (IRQ proxy) ──────────────────────────────────────
    bar_w  = min(28, width - 48)
    # Normalize bar to max observed in history or 10 disp/s
    hist_max = max(max(disp_hist) if disp_hist else 1.0, 1.0)
    disp_pct = min(100.0, disp_rate / hist_max * 100.0)
    disp_bar = _bar(disp_pct, bar_w)

    disp_color = curses.color_pair(C_ACCENT) if disp_rate > 0 else curses.color_pair(C_DIM)
    _safe_addstr(win, row + consumed, col + 2,
                 f"HTP dispatches  {disp_bar}  {disp_rate:5.1f}/s   total {irq_total:,}",
                 disp_color)
    consumed += 1

    # ── Row 3: cdsprpcd CPU usage (spikes during inference) ───────────────────
    cdsp_bar = _bar(min(100.0, cdsp_pct), bar_w)
    _safe_addstr(win, row + consumed, col + 2,
                 f"CDSP daemon CPU {cdsp_bar}  {cdsp_pct:5.1f}%",
                 _pct_color(cdsp_pct))
    consumed += 1

    # ── Row 4: Sparklines side by side ────────────────────────────────────────
    spark_w = min(30, (width - 6) // 2)
    spark_d = _sparkline(disp_hist,  spark_w)
    spark_c = _sparkline(cdsp_hist,  spark_w)
    _safe_addstr(win, row + consumed, col + 2,
                 f"dispatch/s  ", curses.color_pair(C_DIM))
    _safe_addstr(win, row + consumed, col + 14,
                 spark_d, curses.color_pair(C_SPARK) | curses.A_BOLD)
    _safe_addstr(win, row + consumed, col + 14 + spark_w + 2,
                 f"daemon CPU  ", curses.color_pair(C_DIM))
    _safe_addstr(win, row + consumed, col + 14 + spark_w + 14,
                 spark_c, curses.color_pair(C_ACCENT) | curses.A_BOLD)
    consumed += 1

    # ── Row 5: Active session pids ────────────────────────────────────────────
    if fd_procs:
        proc_str = "  sessions: " + "  ".join(
            f"pid {p} ({c})" for p, c in fd_procs[:4]
        )
        _safe_addstr(win, row + consumed, col, proc_str[:width],
                     curses.color_pair(C_DIM))
        consumed += 1

    # ── Row 6: Board sensor ───────────────────────────────────────────────────
    fan_color = curses.color_pair(C_OK) if fan_rpm > 500 else curses.color_pair(C_WARN)
    _safe_addstr(win, row + consumed, col + 2,
                 f"board ({sensor})  temp {board_t1:.0f}°C   fan {fan_rpm} RPM",
                 fan_color)
    consumed += 1

    return consumed


def draw_qnn(win, row, col, width, qnn_data):
    """QNN inference profiling panel (tok/s, latency, op breakdown)."""
    consumed = 0
    consumed += _section_header(win, row + consumed, col, width,
                                 "NPU  inference metrics  (QNN profiling output)")

    tps_p   = qnn_data.get("tps_prompt")
    tps_g   = qnn_data.get("tps_gen")
    lat     = qnn_data.get("htp_latency_ms")
    dec     = qnn_data.get("decode_ms")
    runs    = qnn_data.get("run_count", 0)
    updated = qnn_data.get("last_updated")
    ops     = qnn_data.get("ops", {})
    history = qnn_data.get("tps_history", [])

    stale = ""
    if updated is not None:
        age = time.monotonic() - updated
        if age > 10:
            stale = f"  [stale {age:.0f}s]"

    if tps_g is None and tps_p is None:
        _safe_addstr(win, row + consumed, col + 2,
                     "Waiting for inference output…  use --wrap or --qnn-log" + stale,
                     curses.color_pair(C_DIM) | curses.A_ITALIC)
        consumed += 1
    else:
        parts = []
        if tps_p is not None:
            parts.append(f"prefill {tps_p:.1f} tok/s")
        if tps_g is not None:
            parts.append(f"decode {tps_g:.1f} tok/s")
        _safe_addstr(win, row + consumed, col + 2,
                     "  ".join(parts) + f"   runs: {runs}" + stale,
                     curses.color_pair(C_ACCENT) | curses.A_BOLD)
        consumed += 1

        lat_parts = []
        if lat is not None:
            lat_parts.append(f"HTP dispatch {lat:.2f} ms")
        if dec is not None:
            lat_parts.append(f"decode/tok {dec:.2f} ms")
        if lat_parts:
            _safe_addstr(win, row + consumed, col + 2,
                         "  ".join(lat_parts), curses.color_pair(C_DIM))
            consumed += 1

    spark_w = min(40, width - 22)
    if spark_w > 4:
        spark = _sparkline(history, spark_w)
        _safe_addstr(win, row + consumed, col + 2, "tok/s  ",
                     curses.color_pair(C_DIM))
        _safe_addstr(win, row + consumed, col + 9, spark,
                     curses.color_pair(C_SPARK) | curses.A_BOLD)
        consumed += 1

    if ops:
        sorted_ops  = sorted(ops.items(), key=lambda x: x[1], reverse=True)[:6]
        bar_w       = min(20, width - 40)
        max_lat     = sorted_ops[0][1] if sorted_ops else 1.0
        for op_name, op_ms in sorted_ops:
            pct = min(100.0, op_ms / max(max_lat, 0.001) * 100)
            bar = _bar(pct, bar_w)
            _safe_addstr(win, row + consumed, col + 2,
                         f"{op_name:<20} {op_ms:7.3f} ms  {bar}"[:width - 2],
                         curses.color_pair(C_DIM))
            consumed += 1

    return consumed


def draw_memory(win, row, col, width, mem_data):
    consumed = 0
    consumed += _section_header(win, row + consumed, col, width, "Memory")

    total_kb   = mem_data.get("total_kb", 1)
    used_kb    = mem_data.get("used_kb", 0)
    avail_kb   = mem_data.get("avail_kb", 0)
    cached_kb  = mem_data.get("cached_kb", 0)
    ion_kb     = mem_data.get("ion_total_kb", 0)
    swap_total = mem_data.get("swap_total_kb", 0)
    swap_used  = mem_data.get("swap_used_kb", 0)
    procs      = mem_data.get("qnn_procs", [])

    def kb_to_gb(kb):
        return kb / 1024 / 1024

    bar_w    = min(30, width - 32)
    used_pct = min(100.0, used_kb / max(total_kb, 1) * 100)
    _safe_addstr(win, row + consumed, col + 2,
                 f"DRAM  {_bar(used_pct, bar_w)}  "
                 f"{kb_to_gb(used_kb):.1f} / {kb_to_gb(total_kb):.1f} GB  "
                 f"avail {kb_to_gb(avail_kb):.1f} GB  cached {kb_to_gb(cached_kb):.1f} GB",
                 _pct_color(used_pct))
    consumed += 1

    if swap_total > 0:
        sp_pct = min(100.0, swap_used / max(swap_total, 1) * 100)
        _safe_addstr(win, row + consumed, col + 2,
                     f"Swap  {_bar(sp_pct, bar_w)}  "
                     f"{kb_to_gb(swap_used):.1f} / {kb_to_gb(swap_total):.1f} GB",
                     _pct_color(sp_pct))
        consumed += 1

    if ion_kb > 0 or procs:
        ion_pct = min(100.0, ion_kb / max(total_kb, 1) * 100)
        _safe_addstr(win, row + consumed, col + 2,
                     f"ION/DMA  {_bar(ion_pct, bar_w)}  "
                     f"{kb_to_gb(ion_kb):.2f} GB  (QNN shared buffers)",
                     curses.color_pair(C_ACCENT))
        consumed += 1
        for p in procs[:2]:
            _safe_addstr(win, row + consumed, col + 4,
                         f"pid {p['pid']:<6} {p['comm']:<16} {kb_to_gb(p['heap_kb']):.2f} GB",
                         curses.color_pair(C_DIM))
            consumed += 1

    return consumed


def draw_ddr(win, row, col, width, ddr_data):
    consumed = 0
    consumed += _section_header(win, row + consumed, col, width,
                                 "DDR Bandwidth  (vmstat proxy — no devfreq node on this BSP)")

    r  = ddr_data.get("read_kbps",  0.0)
    w  = ddr_data.get("write_kbps", 0.0)

    def fmt(kbps):
        if kbps >= 1024 * 1024:
            return f"{kbps/1024/1024:.1f} GB/s"
        elif kbps >= 1024:
            return f"{kbps/1024:.1f} MB/s"
        return f"{kbps:.0f} KB/s"

    gpu_freq = ddr_data.get("gpu_freq_hz")
    gf_str   = f"   GPU {gpu_freq/1e6:.0f} MHz" if gpu_freq else ""
    _safe_addstr(win, row + consumed, col + 2,
                 f"Read {fmt(r)}   Write {fmt(w)}{gf_str}",
                 curses.color_pair(C_DIM))
    consumed += 1
    return consumed


def draw_cpu(win, row, col, width, cpu_cores):
    from collectors.cpu import cluster_summary
    consumed = 0
    consumed += _section_header(win, row + consumed, col, width, "CPU")

    big_util, big_freq, little_util, little_freq = cluster_summary(cpu_cores)
    bar_w = min(24, width - 36)

    for cluster, util, freq, color in (
        ("A78 (big)   ", big_util,    big_freq,    C_CLUSTER_BIG),
        ("A55 (LITTLE)", little_util, little_freq, C_CLUSTER_LITTLE),
    ):
        _safe_addstr(win, row + consumed, col + 2,
                     f"{cluster}  {_bar(util, bar_w)}  {util:5.1f}%   {freq:.0f} MHz",
                     curses.color_pair(color) | curses.A_BOLD)
        consumed += 1

    col_w      = max(1, width // 2 - 2)
    mini_bar_w = min(14, col_w - 20)
    cores      = sorted(cpu_cores, key=lambda c: c["id"])
    for i in range(0, len(cores), 2):
        for j in range(2):
            if i + j >= len(cores):
                break
            c   = cores[i + j]
            pct = c["util_pct"]
            tag = "●" if c["online"] else "○"
            s   = f" {tag}cpu{c['id']:<2} {_bar(pct, mini_bar_w)} {pct:4.0f}% {c['freq_mhz']:4d}MHz"
            xcol = col + (col_w + 1) * j
            _safe_addstr(win, row + consumed, xcol, s[:col_w], _pct_color(pct))
        consumed += 1

    return consumed


def draw_thermal(win, row, col, width, zones):
    consumed = 0
    consumed += _section_header(win, row + consumed, col, width, "Thermals")

    cols = max(1, width // 18)
    i    = 0
    while i < len(zones):
        for j in range(cols):
            if i + j >= len(zones):
                break
            z = zones[i + j]
            t = z["temp_c"]
            ts  = f"{t:.0f}°" if t is not None else "n/a"
            seg = f"  {z['label'][:8]:8s}{ts:5s}"
            _safe_addstr(win, row + consumed, col + j * 18, seg[:18],
                         _temp_color(t))
        consumed += 1
        i += cols

    return consumed


def draw_help(win, row, col, width):
    _safe_addstr(win, row, col,
                 "  q quit   r raw log   c clear NPU stats   p pause",
                 curses.color_pair(C_DIM))
    return 1
