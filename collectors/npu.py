"""
NPU hardware state collector for QCS8300 / Hexagon V75 HTP.

Signals available on this BSP (confirmed via probe):
  1. CDSP remoteproc state  → running / offline / crashed
  2. SMP2P IRQ 18 counter   → increments on every HTP dispatch completion
                               delta/sec = dispatch rate (best activity proxy)
  3. /dev/fastrpc-cdsp fds  → number of processes holding active NPU context
  4. cdsprpcd cgroup        → CPU time consumed by CDSP daemon (spikes during inference)
  5. cooling_device10       → cdsp:cdsp_sw throttle state (0=none, >0=throttled)
  6. amc6821 hwmon          → board temp (milliC) + fan RPM
"""

import os
import time
import glob


# ── Confirmed sysfs paths on this BSP ────────────────────────────────────────
_CDSP_STATE    = "/sys/devices/platform/soc@0/26300000.remoteproc/remoteproc/remoteproc0/state"
_SMP2P_IRQ_DIR = "/proc/irq/18"
_PROC_INTERRUPTS = "/proc/interrupts"
_FASTRPC_DEV   = "/dev/fastrpc-cdsp"
_CGROUP_STAT   = "/sys/fs/cgroup/system.slice/cdsprpcd.service/cpu.stat"
_COOLING_STATE = "/sys/class/thermal/cooling_device10/cur_state"
_COOLING_MAX   = "/sys/class/thermal/cooling_device10/max_state"
_HWMON_BASE    = "/sys/devices/platform/soc@0/9c0000.geniqup/984000.i2c/i2c-1/1-0018/hwmon/hwmon0"


def _read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return default


def _read_int(path, default=0):
    v = _read(path)
    try:
        return int(v)
    except Exception:
        return default


def _cdsp_state():
    return _read(_CDSP_STATE, "unknown")


def _smp2p_irq_count():
    """
    Read IRQ 18 total count across all CPUs from /proc/interrupts.
    Line looks like:
      18:   393218   0   0   0   0   0   0   0   ipcc ...  smp2p-cdsp
    We sum all per-CPU columns.
    """
    try:
        with open(_PROC_INTERRUPTS) as f:
            for line in f:
                if "smp2p-" in line and line.strip().startswith("18:"):
                    parts = line.split()
                    # parts[0] = "18:", parts[1..N] = per-cpu counts, then type/name
                    total = 0
                    for p in parts[1:]:
                        try:
                            total += int(p)
                        except ValueError:
                            break
                    return total
    except Exception:
        pass
    return 0


def _fastrpc_open_fds():
    """Count processes with /dev/fastrpc-cdsp open via /proc/<pid>/fd."""
    count = 0
    pids_found = []
    try:
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            fd_dir = f"/proc/{entry.name}/fd"
            try:
                for fd in os.scandir(fd_dir):
                    try:
                        target = os.readlink(fd.path)
                        if "fastrpc-cdsp" in target:
                            count += 1
                            comm = _read(f"/proc/{entry.name}/comm", "?")
                            pids_found.append((int(entry.name), comm))
                            break
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass
    return count, pids_found


def _cgroup_cpu_usec():
    """Return (usage_usec, user_usec, system_usec) from cdsprpcd cgroup."""
    vals = {"usage_usec": 0, "user_usec": 0, "system_usec": 0}
    try:
        with open(_CGROUP_STAT) as f:
            for line in f:
                parts = line.split()
                if len(parts) == 2 and parts[0] in vals:
                    vals[parts[0]] = int(parts[1])
    except Exception:
        pass
    return vals["usage_usec"], vals["user_usec"], vals["system_usec"]


def _cooling():
    cur = _read_int(_COOLING_STATE, 0)
    mx  = _read_int(_COOLING_MAX,  0)
    return cur, mx


def _hwmon():
    t1 = _read_int(os.path.join(_HWMON_BASE, "temp1_input"), 0) / 1000.0
    t2 = _read_int(os.path.join(_HWMON_BASE, "temp2_input"), 0) / 1000.0
    fan = _read_int(os.path.join(_HWMON_BASE, "fan1_input"), 0)
    name = _read(os.path.join(_HWMON_BASE, "name"), "?")
    return t1, t2, fan, name


class NPUCollector:
    def __init__(self):
        self._prev_irq   = _smp2p_irq_count()
        self._prev_usec  = _cgroup_cpu_usec()[0]
        self._prev_time  = time.monotonic()
        self._dispatch_history = []   # rolling irq delta/s (last 60 samples)
        self._cdsp_usage_history = [] # rolling cgroup cpu% (last 60 samples)

    def collect(self):
        now = time.monotonic()
        dt  = max(now - self._prev_time, 0.001)

        # 1. CDSP state
        state = _cdsp_state()

        # 2. SMP2P dispatch rate
        irq_now   = _smp2p_irq_count()
        irq_delta = max(0, irq_now - self._prev_irq)
        dispatch_rate = irq_delta / dt   # dispatches/sec

        self._dispatch_history.append(dispatch_rate)
        if len(self._dispatch_history) > 60:
            self._dispatch_history.pop(0)

        # 3. FastRPC open sessions
        fd_count, fd_procs = _fastrpc_open_fds()

        # 4. cdsprpcd cgroup CPU usage %
        usage_now, user_usec, sys_usec = _cgroup_cpu_usec()
        usec_delta  = max(0, usage_now - self._prev_usec)
        # dt is in seconds, usec_delta in microseconds
        cdsp_cpu_pct = min(100.0, (usec_delta / 1e6) / dt * 100.0)

        self._cdsp_usage_history.append(cdsp_cpu_pct)
        if len(self._cdsp_usage_history) > 60:
            self._cdsp_usage_history.pop(0)

        # 5. Cooling / throttle
        cool_cur, cool_max = _cooling()

        # 6. Board sensor (amc6821)
        board_t1, board_t2, fan_rpm, sensor_name = _hwmon()

        # Derived: active heuristic
        # NPU is "active" if: dispatch rate > 0 in last interval, or fd_count > 0
        is_active = (irq_delta > 0) or (fd_count > 0)

        # Update state
        self._prev_irq  = irq_now
        self._prev_usec = usage_now
        self._prev_time = now

        return {
            "cdsp_state":        state,           # "running" / "offline" / "crashed"
            "is_active":         is_active,        # bool
            "irq_total":         irq_now,          # cumulative dispatch count
            "irq_delta":         irq_delta,        # dispatches this interval
            "dispatch_rate":     dispatch_rate,    # dispatches/sec
            "dispatch_history":  list(self._dispatch_history),
            "fd_count":          fd_count,         # active NPU sessions
            "fd_procs":          fd_procs,         # [(pid, comm), ...]
            "cdsp_cpu_pct":      cdsp_cpu_pct,     # cdsprpcd CPU usage %
            "cdsp_cpu_history":  list(self._cdsp_usage_history),
            "cool_cur":          cool_cur,         # throttle level
            "cool_max":          cool_max,
            "board_temp1_c":     board_t1,
            "board_temp2_c":     board_t2,
            "fan_rpm":           fan_rpm,
            "sensor_name":       sensor_name,
        }
