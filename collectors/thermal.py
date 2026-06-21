"""
Thermal collector: reads all /sys/class/thermal/thermal_zone* entries.
Attempts to label zones by type; zones without useful names are shown as "zone-N".
"""

import os
import glob


# Known type string fragments → friendly label
_TYPE_MAP = [
    ("cpu",     "CPU"),
    ("npu",     "NPU"),
    ("gpu",     "GPU"),
    ("ddr",     "DDR"),
    ("mdm",     "Modem"),
    ("nss",     "NSS"),
    ("lmh",     "LMH"),
    ("pmic",    "PMIC"),
    ("pa",      "PA"),
    ("tsens",   "tSens"),
    ("pm",      "PMIC"),
    ("aoss",    "AOSS"),
    ("camera",  "Cam"),
    ("display", "Disp"),
    ("skin",    "Skin"),
]


def _label(type_str, zone_id):
    lower = type_str.lower()
    for fragment, friendly in _TYPE_MAP:
        if fragment in lower:
            return f"{friendly}"
    return f"zone-{zone_id}"


def _read_zone(zone_path):
    zone_id = int(zone_path.split("thermal_zone")[-1])
    try:
        with open(os.path.join(zone_path, "type")) as f:
            type_str = f.read().strip()
    except Exception:
        type_str = f"zone-{zone_id}"

    try:
        with open(os.path.join(zone_path, "temp")) as f:
            temp_mc = int(f.read().strip())
            temp_c  = temp_mc / 1000.0
    except Exception:
        temp_c = None

    return {
        "id":       zone_id,
        "type":     type_str,
        "label":    _label(type_str, zone_id),
        "temp_c":   temp_c,
    }


class ThermalCollector:
    def __init__(self):
        self._zones = sorted(
            glob.glob("/sys/class/thermal/thermal_zone*"),
            key=lambda p: int(p.split("thermal_zone")[-1])
        )

    def collect(self):
        zones = []
        for z in self._zones:
            info = _read_zone(z)
            if info["temp_c"] is not None:
                zones.append(info)
        return zones

    def max_temp(self, zones):
        temps = [z["temp_c"] for z in zones if z["temp_c"] is not None]
        return max(temps) if temps else 0.0
