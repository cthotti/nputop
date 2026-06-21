"""
Memory collector: system DRAM from /proc/meminfo,
per-process ION/DMA heap (QNN shared buffers) from /proc/<pid>/smaps.
"""

import os
import re
import subprocess


def _parse_meminfo():
    fields = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    val = int(parts[1])  # kB
                    fields[key] = val
    except Exception:
        pass
    return fields


def _find_qnn_pids():
    """Find PIDs of processes likely running QNN inference (et_run, qnn-net-run, python3)."""
    pids = []
    try:
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            try:
                with open(f"/proc/{entry.name}/comm") as f:
                    comm = f.read().strip()
                if any(k in comm for k in ("et_run", "qnn", "python3", "python", "runner")):
                    pids.append((int(entry.name), comm))
            except Exception:
                pass
    except Exception:
        pass
    return pids


def _ion_heap_kb(pid):
    """
    Sum up /dmabuf or ION-backed anonymous mappings in smaps.
    These show up as Anonymous or as labeled [ion] / /dev/ion sections.
    Falls back to summing all anonymous RSS if ION labels aren't present.
    """
    ion_kb = 0
    anon_kb = 0
    try:
        path = f"/proc/{pid}/smaps"
        with open(path, errors="replace") as f:
            in_ion = False
            cur_rss = 0
            for line in f:
                if line[0].isdigit() or line[0] == "0":
                    # New mapping header
                    in_ion = "/dev/ion" in line or "dmabuf" in line.lower()
                    cur_rss = 0
                elif line.startswith("Rss:"):
                    val = int(line.split()[1])
                    if in_ion:
                        ion_kb += val
                    anon_kb += val
    except Exception:
        pass
    return ion_kb if ion_kb > 0 else anon_kb


class MemoryCollector:
    def collect(self):
        info = _parse_meminfo()

        total_kb = info.get("MemTotal", 0)
        free_kb  = info.get("MemFree", 0)
        avail_kb = info.get("MemAvailable", 0)
        buffers  = info.get("Buffers", 0)
        cached   = info.get("Cached", 0) + info.get("SReclaimable", 0)
        swap_total = info.get("SwapTotal", 0)
        swap_free  = info.get("SwapFree", 0)

        used_kb = total_kb - avail_kb

        qnn_procs = _find_qnn_pids()
        ion_total_kb = 0
        proc_details = []
        for pid, comm in qnn_procs:
            heap = _ion_heap_kb(pid)
            ion_total_kb += heap
            proc_details.append({
                "pid":  pid,
                "comm": comm,
                "heap_kb": heap,
            })

        return {
            "total_kb":     total_kb,
            "used_kb":      used_kb,
            "avail_kb":     avail_kb,
            "buffers_kb":   buffers,
            "cached_kb":    cached,
            "swap_total_kb": swap_total,
            "swap_used_kb":  swap_total - swap_free,
            "ion_total_kb": ion_total_kb,
            "qnn_procs":    proc_details,
        }
