"""
QNN profiling collector.

Since ExecuTorch + QNN prints profiling output to stdout/stderr,
nputop reads from a named pipe (FIFO) or a log file that you redirect
your inference runner into, e.g.:

    mkfifo /tmp/qnn_prof.pipe
    python3 run_inference.py 2>&1 | tee /tmp/qnn_prof.pipe

Or just:
    python3 run_inference.py 2>&1 | tee /tmp/qnn_prof.log

Pass the path with --qnn-log.  nputop tails it non-blocking.

Parsed formats (QNN SDK + ExecuTorch emit variations of these):

  [QNN ExecuTorch]: Prompt processing tokens per second: 106.6
  [QNN ExecuTorch]: Generated tokens per second: 88.3
  Execute(): op_name=Conv2d,time=1234us
  [INFO] HTP inference time: 9.4 ms
  QNN_EXECUTE_COMPLETION_EVENT: latency_us=9412
  Prompt tokens: 128, time: 2.34 s
  Decode time per token: 11.2 ms
"""

import re
import os
import time
from collections import deque


# ── Regex patterns ────────────────────────────────────────────────────────────

_RE_TPS_PROMPT = re.compile(
    r"[Pp]rompt.*?tokens?\s+per\s+second[:\s]+([0-9]+\.?[0-9]*)", re.IGNORECASE
)
_RE_TPS_GEN = re.compile(
    r"[Gg]enerat\w*.*?tokens?\s+per\s+second[:\s]+([0-9]+\.?[0-9]*)", re.IGNORECASE
)
_RE_TPS_GENERIC = re.compile(
    r"tokens?\s+per\s+second[:\s]+([0-9]+\.?[0-9]*)", re.IGNORECASE
)
# HTP inference time with explicit ms/us unit
_RE_HTP_LATENCY_MS = re.compile(
    r"HTP inference time[:\s]+([0-9]+\.?[0-9]*)\s*(ms|us)?",
    re.IGNORECASE,
)
# QNN_EXECUTE_COMPLETION_EVENT: latency_us=9412  (unit is in the key name)
_RE_HTP_LATENCY_US = re.compile(
    r"QNN_EXECUTE_COMPLETION_EVENT.*?latency_us[=:\s]+([0-9]+\.?[0-9]*)",
    re.IGNORECASE,
)
_RE_OP = re.compile(
    r"op[_\s]?name[=:\s]+(\w+).*?time[=:\s]+([0-9]+)(us|ms)?",
    re.IGNORECASE,
)
_RE_OP_ALT = re.compile(
    r"(\w+)\s+execution\s+time[:\s]+([0-9]+\.?[0-9]*)\s*(us|ms)?",
    re.IGNORECASE,
)
_RE_DECODE_MS = re.compile(
    r"[Dd]ecode\s+time\s+per\s+token[:\s]+([0-9]+\.?[0-9]*)\s*(ms|us)?",
    re.IGNORECASE,
)
_RE_PROMPT_TOK = re.compile(
    r"[Pp]rompt\s+tokens?[:\s]+([0-9]+)",
    re.IGNORECASE,
)


def _to_ms(val, unit):
    if unit and unit.lower() == "us":
        return val / 1000.0
    return val  # assume ms


class QNNProfileCollector:
    def __init__(self, log_path=None):
        self.log_path = log_path
        self._fh = None
        self._buf = deque(maxlen=500)   # raw recent lines
        self._ops = {}                  # op_name -> latest latency_ms
        self._run_history = deque(maxlen=60)  # tok/s over time (sparkline)

        # Latest parsed snapshot
        self.last = {
            "tps_prompt":    None,
            "tps_gen":       None,
            "htp_latency_ms": None,
            "decode_ms":     None,
            "prompt_tokens": None,
            "ops":           {},
            "run_count":     0,
            "last_updated":  None,
        }
        self._run_count = 0

    def _open(self):
        if self.log_path and self._fh is None:
            try:
                self._fh = open(self.log_path, "r", errors="replace")
                self._fh.seek(0, 2)  # seek to end (tail mode)
            except Exception:
                self._fh = None

    def _parse_line(self, line):
        changed = False

        m = _RE_TPS_PROMPT.search(line)
        if m:
            self.last["tps_prompt"] = float(m.group(1))
            self._run_count += 1
            self._run_history.append(self.last["tps_prompt"])
            self.last["run_count"] = self._run_count
            self.last["last_updated"] = time.monotonic()
            changed = True

        m = _RE_TPS_GEN.search(line)
        if m:
            self.last["tps_gen"] = float(m.group(1))
            if not _RE_TPS_PROMPT.search(line):
                self._run_count += 1
                self._run_history.append(self.last["tps_gen"])
                self.last["run_count"] = self._run_count
                self.last["last_updated"] = time.monotonic()
            changed = True

        if not changed:
            m = _RE_TPS_GENERIC.search(line)
            if m:
                self.last["tps_gen"] = float(m.group(1))
                self._run_count += 1
                self._run_history.append(self.last["tps_gen"])
                self.last["run_count"] = self._run_count
                self.last["last_updated"] = time.monotonic()

        # HTP latency — two formats
        m = _RE_HTP_LATENCY_MS.search(line)
        if m:
            val  = float(m.group(1))
            unit = m.group(2) or "ms"
            self.last["htp_latency_ms"] = _to_ms(val, unit)
            self.last["last_updated"]   = time.monotonic()
        else:
            m = _RE_HTP_LATENCY_US.search(line)
            if m:
                # latency_us key means the value IS in microseconds
                self.last["htp_latency_ms"] = float(m.group(1)) / 1000.0
                self.last["last_updated"]   = time.monotonic()

        m = _RE_DECODE_MS.search(line)
        if m:
            val  = float(m.group(1))
            unit = m.group(2) or "ms"
            self.last["decode_ms"] = _to_ms(val, unit)

        m = _RE_PROMPT_TOK.search(line)
        if m:
            self.last["prompt_tokens"] = int(m.group(1))

        m = _RE_OP.search(line) or _RE_OP_ALT.search(line)
        if m:
            op_name = m.group(1)
            val     = float(m.group(2))
            unit    = m.group(3) if m.lastindex >= 3 else "us"
            self._ops[op_name] = _to_ms(val, unit or "us")
            self.last["ops"] = dict(self._ops)

    def feed_line(self, line):
        """Manually feed a line (used when wrapping a subprocess)."""
        self._buf.append(line)
        self._parse_line(line)

    def poll(self):
        """Non-blocking poll of the log file for new lines."""
        self._open()
        if self._fh is None:
            return
        while True:
            line = self._fh.readline()
            if not line:
                break
            self._buf.append(line.rstrip())
            self._parse_line(line)

    def collect(self):
        self.poll()
        snap = dict(self.last)
        snap["ops"]         = dict(self._ops)
        snap["tps_history"] = list(self._run_history)
        return snap

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None
