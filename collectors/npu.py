import os
import time

_CDSP_STATE      = "/sys/devices/platform/soc@0/26300000.remoteproc/remoteproc/remoteproc0/state"
_PROC_INTERRUPTS = "/proc/interrupts"
_CGROUP_STAT     = "/sys/fs/cgroup/system.slice/cdsprpcd.service/cpu.stat"
_COOLING_STATE   = "/sys/class/thermal/cooling_device10/cur_state"
_COOLING_MAX     = "/sys/class/thermal/cooling_device10/max_state"
_HWMON_BASE      = "/sys/devices/platform/soc@0/9c0000.geniqup/984000.i2c/i2c-1/1-0018/hwmon/hwmon0"

_FD_SCAN_INTERVAL = 3.0
_HWMON_INTERVAL   = 5.0
_COOLING_INTERVAL = 5.0


def _read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return default


def _read_int(path, default=0):
    try:
        return int(_read(path, default))
    except Exception:
        return default


def _smp2p_irq_count():
    try:
        with open(_PROC_INTERRUPTS) as f:
            for line in f:
                if "smp2p-" in line and line.strip().startswith("18:"):
                    parts = line.split()
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


def _cgroup_usage_usec():
    try:
        with open(_CGROUP_STAT) as f:
            for line in f:
                if line.startswith("usage_usec"):
                    return int(line.split()[1])
    except Exception:
        pass
    return 0


def _fastrpc_open_fds():
    count = 0
    procs = []
    try:
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            fd_dir = f"/proc/{entry.name}/fd"
            try:
                for fd in os.scandir(fd_dir):
                    try:
                        if "fastrpc-cdsp" in os.readlink(fd.path):
                            count += 1
                            comm = _read(f"/proc/{entry.name}/comm", "?")
                            procs.append((int(entry.name), comm))
                            break
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass
    return count, procs


class NPUCollector:
    def __init__(self):
        self._prev_irq  = _smp2p_irq_count()
        self._prev_usec = _cgroup_usage_usec()
        self._prev_time = time.monotonic()
        self._dispatch_history = []
        self._cdsp_cpu_history = []
        self._fd_count    = 0
        self._fd_procs    = []
        self._cool_cur    = 0
        self._cool_max    = 0
        self._board_t1    = 0.0
        self._board_t2    = 0.0
        self._fan_rpm     = 0
        self._sensor_name = "amc6821"
        self._last_fd_scan  = 0.0
        self._last_hwmon    = 0.0
        self._last_cooling  = 0.0

    def collect(self):
        now = time.monotonic()
        dt  = max(now - self._prev_time, 0.001)

        state    = _read(_CDSP_STATE, "unknown")
        irq_now  = _smp2p_irq_count()
        usec_now = _cgroup_usage_usec()

        irq_delta     = max(0, irq_now - self._prev_irq)
        dispatch_rate = irq_delta / dt
        cdsp_cpu_pct  = min(100.0, (max(0, usec_now - self._prev_usec) / 1e6) / dt * 100.0)

        self._dispatch_history.append(dispatch_rate)
        if len(self._dispatch_history) > 60:
            self._dispatch_history.pop(0)
        self._cdsp_cpu_history.append(cdsp_cpu_pct)
        if len(self._cdsp_cpu_history) > 60:
            self._cdsp_cpu_history.pop(0)

        if now - self._last_fd_scan >= _FD_SCAN_INTERVAL:
            self._fd_count, self._fd_procs = _fastrpc_open_fds()
            self._last_fd_scan = now

        if now - self._last_cooling >= _COOLING_INTERVAL:
            self._cool_cur = _read_int(_COOLING_STATE, 0)
            self._cool_max = _read_int(_COOLING_MAX, 0)
            self._last_cooling = now

        if now - self._last_hwmon >= _HWMON_INTERVAL:
            self._board_t1    = _read_int(os.path.join(_HWMON_BASE, "temp1_input"), 0) / 1000.0
            self._board_t2    = _read_int(os.path.join(_HWMON_BASE, "temp2_input"), 0) / 1000.0
            self._fan_rpm     = _read_int(os.path.join(_HWMON_BASE, "fan1_input"), 0)
            self._sensor_name = _read(os.path.join(_HWMON_BASE, "name"), "amc6821")
            self._last_hwmon  = now

        self._prev_irq  = irq_now
        self._prev_usec = usec_now
        self._prev_time = now

        return {
            "cdsp_state":       state,
            "is_active":        (irq_delta > 0) or (self._fd_count > 0),
            "irq_total":        irq_now,
            "irq_delta":        irq_delta,
            "dispatch_rate":    dispatch_rate,
            "dispatch_history": list(self._dispatch_history),
            "fd_count":         self._fd_count,
            "fd_procs":         self._fd_procs,
            "cdsp_cpu_pct":     cdsp_cpu_pct,
            "cdsp_cpu_history": list(self._cdsp_cpu_history),
            "cool_cur":         self._cool_cur,
            "cool_max":         self._cool_max,
            "board_temp1_c":    self._board_t1,
            "board_temp2_c":    self._board_t2,
            "fan_rpm":          self._fan_rpm,
            "sensor_name":      self._sensor_name,
        }
