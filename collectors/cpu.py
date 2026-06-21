"""
CPU collector: per-core utilization + frequency from /proc/stat and sysfs.
Handles heterogeneous big.LITTLE cores (A78 + A55 on QCS8300).
"""

import os
import time


# QCS8300 core topology: cores 0-3 = Cortex-A78 (big), 4-7 = Cortex-A55 (LITTLE)
# Adjust if your BSP reports differently.
BIG_CORES   = list(range(4))   # A78
LITTLE_CORES = list(range(4, 8))  # A55


def _read_proc_stat():
    """Return dict of cpu_id -> (user, nice, system, idle, iowait, irq, softirq)."""
    stats = {}
    try:
        with open("/proc/stat") as f:
            for line in f:
                if not line.startswith("cpu"):
                    break
                parts = line.split()
                name = parts[0]
                if name == "cpu":
                    continue
                idx = int(name[3:])
                vals = tuple(int(x) for x in parts[1:8])
                stats[idx] = vals
    except Exception:
        pass
    return stats


def _core_freq_mhz(core_id):
    path = f"/sys/devices/system/cpu/cpu{core_id}/cpufreq/scaling_cur_freq"
    try:
        with open(path) as f:
            return int(f.read().strip()) // 1000
    except Exception:
        return 0


def _core_online(core_id):
    if core_id == 0:
        return True  # cpu0 is always online, no online file
    path = f"/sys/devices/system/cpu/cpu{core_id}/online"
    try:
        with open(path) as f:
            return f.read().strip() == "1"
    except Exception:
        return True


class CPUCollector:
    def __init__(self):
        self._prev = {}
        self._prev_time = time.monotonic()
        self._prev = _read_proc_stat()

    def collect(self):
        """
        Returns list of dicts, one per core:
          { id, online, util_pct, freq_mhz, cluster }
        """
        curr = _read_proc_stat()
        now = time.monotonic()
        results = []

        num_cores = max(
            max(curr.keys(), default=-1),
            max(self._prev.keys(), default=-1)
        ) + 1

        for i in range(num_cores):
            online = _core_online(i)
            freq = _core_freq_mhz(i) if online else 0

            if i in BIG_CORES:
                cluster = "A78"
            elif i in LITTLE_CORES:
                cluster = "A55"
            else:
                cluster = "???"

            util = 0.0
            if i in curr and i in self._prev:
                c = curr[i]
                p = self._prev[i]
                c_total = sum(c)
                p_total = sum(p)
                d_total = c_total - p_total
                c_idle  = c[3] + c[4]  # idle + iowait
                p_idle  = p[3] + p[4]
                d_idle  = c_idle - p_idle
                if d_total > 0:
                    util = 100.0 * (1.0 - d_idle / d_total)
                    util = max(0.0, min(100.0, util))

            results.append({
                "id":       i,
                "online":   online,
                "util_pct": util,
                "freq_mhz": freq,
                "cluster":  cluster,
            })

        self._prev = curr
        self._prev_time = now
        return results


def cluster_summary(cores):
    """Return (big_avg_util, big_avg_freq, little_avg_util, little_avg_freq)."""
    big    = [c for c in cores if c["cluster"] == "A78" and c["online"]]
    little = [c for c in cores if c["cluster"] == "A55" and c["online"]]

    def avg(lst, key):
        return sum(x[key] for x in lst) / len(lst) if lst else 0.0

    return (
        avg(big,    "util_pct"), avg(big,    "freq_mhz"),
        avg(little, "util_pct"), avg(little, "freq_mhz"),
    )
