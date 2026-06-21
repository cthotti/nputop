"""
DDR bandwidth proxy via /proc/vmstat (pgpgin / pgpgout) delta.
Since the QCS8300 BSP doesn't expose a DDR devfreq node, we use
page-in/out rates as a coarse bandwidth signal.

Also reads GPU devfreq (3d00000.gpu) as a bonus metric since it IS present.
"""

import time


_VMSTAT_KEYS = ("pgpgin", "pgpgout", "pswpin", "pswpout")


def _read_vmstat():
    vals = {}
    try:
        with open("/proc/vmstat") as f:
            for line in f:
                parts = line.split()
                if len(parts) == 2 and parts[0] in _VMSTAT_KEYS:
                    vals[parts[0]] = int(parts[1])
    except Exception:
        pass
    return vals


def _read_devfreq_freq(name):
    path = f"/sys/class/devfreq/{name}/cur_freq"
    try:
        with open(path) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _read_devfreq_load(name):
    """Read trans_stat to estimate load (some devfreq drivers expose this)."""
    path = f"/sys/class/devfreq/{name}/load"
    try:
        with open(path) as f:
            return int(f.read().strip())
    except Exception:
        return None


class DDRCollector:
    def __init__(self):
        self._prev = _read_vmstat()
        self._prev_time = time.monotonic()

    def collect(self):
        curr = _read_vmstat()
        now  = time.monotonic()
        dt   = max(now - self._prev_time, 0.001)

        def rate(key):
            return (curr.get(key, 0) - self._prev.get(key, 0)) / dt

        # Pages are 4KB each → KB/s
        read_kbps  = rate("pgpgin")  * 4.0
        write_kbps = rate("pgpgout") * 4.0
        swap_in    = rate("pswpin")  * 4.0
        swap_out   = rate("pswpout") * 4.0

        self._prev = curr
        self._prev_time = now

        gpu_freq = _read_devfreq_freq("3d00000.gpu")
        gpu_load = _read_devfreq_load("3d00000.gpu")

        return {
            "read_kbps":   read_kbps,
            "write_kbps":  write_kbps,
            "swap_in_kbps":  swap_in,
            "swap_out_kbps": swap_out,
            "gpu_freq_hz": gpu_freq,
            "gpu_load_pct": gpu_load,
        }
