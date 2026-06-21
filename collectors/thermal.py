import glob
import time

_TYPE_MAP = [
    ("cpu",     "CPU"),
    ("npu",     "NPU"),
    ("gpu",     "GPU"),
    ("ddr",     "DDR"),
    ("mdm",     "Modem"),
    ("lmh",     "LMH"),
    ("pmic",    "PMIC"),
    ("aoss",    "AOSS"),
    ("skin",    "Skin"),
    ("cdsp",    "CDSP"),
    ("camera",  "Cam"),
    ("display", "Disp"),
    ("tsens",   "tSens"),
]

_INTERVAL = 3.0


def _label(type_str, zone_id):
    lower = type_str.lower()
    for fragment, friendly in _TYPE_MAP:
        if fragment in lower:
            return friendly
    return f"zone-{zone_id}"


class ThermalCollector:
    def __init__(self):
        self._zone_paths = sorted(
            glob.glob("/sys/class/thermal/thermal_zone*"),
            key=lambda p: int(p.split("thermal_zone")[-1])
        )
        self._zones_meta = []
        for z in self._zone_paths:
            zone_id = int(z.split("thermal_zone")[-1])
            try:
                with open(f"{z}/type") as f:
                    type_str = f.read().strip()
            except Exception:
                type_str = f"zone-{zone_id}"
            self._zones_meta.append({
                "id":    zone_id,
                "type":  type_str,
                "label": _label(type_str, zone_id),
                "path":  z,
            })
        self._cached    = []
        self._last_read = 0.0

    def collect(self):
        now = time.monotonic()
        if now - self._last_read < _INTERVAL and self._cached:
            return self._cached
        zones = []
        for z in self._zones_meta:
            try:
                with open(f"{z['path']}/temp") as f:
                    temp_c = int(f.read().strip()) / 1000.0
            except Exception:
                temp_c = None
            if temp_c is not None:
                zones.append({**z, "temp_c": temp_c})
        self._cached    = zones
        self._last_read = now
        return zones
