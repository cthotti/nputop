import os
import time


def _parse_meminfo():
    fields = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    fields[key] = int(parts[1])
    except Exception:
        pass
    return fields


def _find_qnn_pids():
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
    ion_kb = 0
    try:
        with open(f"/proc/{pid}/smaps", errors="replace") as f:
            in_ion = False
            for line in f:
                if line[0].isdigit() or line[0] == "0":
                    in_ion = "/dev/ion" in line or "dmabuf" in line.lower()
                elif line.startswith("Rss:") and in_ion:
                    ion_kb += int(line.split()[1])
    except Exception:
        pass
    return ion_kb


class MemoryCollector:
    _SMAPS_INTERVAL = 5.0

    def __init__(self):
        self._last_smaps_time = 0.0
        self._cached_procs = []
        self._cached_ion_kb = 0

    def collect(self):
        info = _parse_meminfo()
        total_kb   = info.get("MemTotal", 0)
        avail_kb   = info.get("MemAvailable", 0)
        buffers    = info.get("Buffers", 0)
        cached     = info.get("Cached", 0) + info.get("SReclaimable", 0)
        swap_total = info.get("SwapTotal", 0)
        swap_free  = info.get("SwapFree", 0)
        used_kb    = total_kb - avail_kb

        now = time.monotonic()
        if now - self._last_smaps_time >= self._SMAPS_INTERVAL:
            qnn_procs = _find_qnn_pids()
            ion_total = 0
            proc_details = []
            for pid, comm in qnn_procs:
                heap = _ion_heap_kb(pid)
                ion_total += heap
                proc_details.append({"pid": pid, "comm": comm, "heap_kb": heap})
            self._cached_procs    = proc_details
            self._cached_ion_kb   = ion_total
            self._last_smaps_time = now

        return {
            "total_kb":      total_kb,
            "used_kb":       used_kb,
            "avail_kb":      avail_kb,
            "buffers_kb":    buffers,
            "cached_kb":     cached,
            "swap_total_kb": swap_total,
            "swap_used_kb":  swap_total - swap_free,
            "ion_total_kb":  self._cached_ion_kb,
            "qnn_procs":     self._cached_procs,
        }
