#!/usr/bin/env python3
"""nputop v0.2.1 — NPU + System Monitor for Qualcomm IQ8 (QCS8300 / Hexagon V75 HTP)"""

import argparse
import curses
import os
import subprocess
import sys
import threading
import time
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collectors.cpu     import CPUCollector
from collectors.memory  import MemoryCollector
from collectors.thermal import ThermalCollector
from collectors.ddr     import DDRCollector
from collectors.qnn     import QNNProfileCollector
from collectors.npu     import NPUCollector
from ui.panels import (
    init_colors, draw_title, draw_npu_hw, draw_qnn,
    draw_memory, draw_ddr, draw_cpu, draw_thermal, draw_help,
)

VERSION = "0.2.1"


class SubprocessFeeder:
    def __init__(self, cmd, qnn_collector):
        self.cmd   = cmd
        self.qnn   = qnn_collector
        self._proc = None
        self._done = False
        self._log  = deque(maxlen=200)
        self._t    = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._t.start()

    def _run(self):
        try:
            self._proc = subprocess.Popen(
                self.cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in self._proc.stdout:
                line = line.rstrip()
                self._log.append(line)
                self.qnn.feed_line(line)
            self._proc.wait()
        except Exception as e:
            self._log.append(f"[nputop error] {e}")
        self._done = True

    @property
    def done(self):
        return self._done

    @property
    def returncode(self):
        return self._proc.returncode if self._proc and self._done else None

    def recent_output(self, n=8):
        return list(self._log)[-n:]

    def terminate(self):
        if self._proc and not self._done:
            self._proc.terminate()


def _draw(stdscr, collectors, feeder, show_raw):
    cpu_c, mem_c, therm_c, ddr_c, qnn_c, npu_c = collectors
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    row  = 0

    row += draw_title(stdscr, row, 0, w, VERSION)
    if row < h - 2: row += draw_npu_hw (stdscr, row, 0, w, npu_c.collect())
    if row < h - 2: row += draw_qnn    (stdscr, row, 0, w, qnn_c.collect())
    if row < h - 2: row += draw_memory (stdscr, row, 0, w, mem_c.collect())
    if row < h - 2: row += draw_ddr    (stdscr, row, 0, w, ddr_c.collect())
    if row < h - 2: row += draw_cpu    (stdscr, row, 0, w, cpu_c.collect())
    if row < h - 2: row += draw_thermal(stdscr, row, 0, w, therm_c.collect())

    if feeder and show_raw:
        for line in feeder.recent_output():
            if row >= h - 2:
                break
            try:
                stdscr.addstr(row, 0, ("  " + line)[:w - 1], curses.color_pair(6))
                row += 1
            except curses.error:
                break

    draw_help(stdscr, h - 1, 0, w)
    stdscr.refresh()


def _main(stdscr, args):
    curses.curs_set(0)
    stdscr.nodelay(True)
    init_colors()

    cpu_c   = CPUCollector()
    mem_c   = MemoryCollector()
    therm_c = ThermalCollector()
    ddr_c   = DDRCollector()
    qnn_c   = QNNProfileCollector(log_path=args.qnn_log)
    npu_c   = NPUCollector()
    collectors = (cpu_c, mem_c, therm_c, ddr_c, qnn_c, npu_c)

    feeder   = None
    if args.wrap:
        feeder = SubprocessFeeder(args.wrap, qnn_c)
        feeder.start()

    show_raw  = False
    last_draw = 0.0

    while True:
        now = time.monotonic()
        if now - last_draw >= args.refresh:
            try:
                _draw(stdscr, collectors, feeder, show_raw)
            except curses.error:
                pass
            last_draw = now

        sleep_for = max(0.05, args.refresh - (time.monotonic() - last_draw))
        stdscr.timeout(int(sleep_for * 1000))
        key = stdscr.getch()

        if key in (ord('q'), ord('Q')):
            if feeder: feeder.terminate()
            break
        elif key in (ord('r'), ord('R')):
            show_raw = not show_raw
        elif key in (ord('c'), ord('C')):
            qnn_c.last.update({
                "tps_prompt": None, "tps_gen": None,
                "htp_latency_ms": None, "decode_ms": None,
                "ops": {}, "run_count": 0, "last_updated": None,
            })
            qnn_c._ops.clear()
            qnn_c._run_history.clear()
            qnn_c._run_count = 0
        elif key == curses.KEY_RESIZE:
            curses.resizeterm(*stdscr.getmaxyx())


def main():
    parser = argparse.ArgumentParser(
        description="nputop — NPU + System Monitor for Qualcomm IQ8 (QCS8300)"
    )
    parser.add_argument("--qnn-log", metavar="PATH")
    parser.add_argument("--wrap",    metavar="CMD")
    parser.add_argument("--refresh", type=float, default=1.0, metavar="SEC")
    args = parser.parse_args()

    if args.qnn_log and args.wrap:
        print("Error: use --qnn-log OR --wrap, not both.", file=sys.stderr)
        sys.exit(1)

    try:
        curses.wrapper(_main, args)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
