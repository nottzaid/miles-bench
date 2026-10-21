"""GPU clock offsets and power limit through NVML (works on Wayland, where nvidia-settings cannot).

    python3 tools/gpuclk.py                      # show offsets, their ranges, power limit
    sudo python3 tools/gpuclk.py set <core MHz> <mem MHz> [power W]
    sudo python3 tools/gpuclk.py reset           # 0 / 0 / default power limit

Offsets do not survive a reboot or a driver reload. <mem MHz> is NVML's memory clock offset
(nvidia-smi's "Memory" clock scale)."""
import ctypes
import sys

nv = ctypes.CDLL("libnvidia-ml.so.1")


def ok(r, what):
    if r:
        nv.nvmlErrorString.restype = ctypes.c_char_p
        sys.exit(f"{what}: {nv.nvmlErrorString(r).decode()}")


ok(nv.nvmlInit_v2(), "init")
dev = ctypes.c_void_p()
ok(nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev)), "device")


def show():
    lo, hi, cur = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
    for name in ("Gpc", "Mem"):
        ok(getattr(nv, f"nvmlDeviceGet{name}ClkMinMaxVfOffset")(dev, ctypes.byref(lo), ctypes.byref(hi)), name)
        r = getattr(nv, f"nvmlDeviceGet{name}ClkVfOffset")(dev, ctypes.byref(cur))
        print(f"{name.lower()} offset {cur.value if not r else '?'} MHz (range {lo.value}..{hi.value})")
    lim, dflt, mn, mx = (ctypes.c_uint() for _ in range(4))
    nv.nvmlDeviceGetPowerManagementLimit(dev, ctypes.byref(lim))
    nv.nvmlDeviceGetPowerManagementDefaultLimit(dev, ctypes.byref(dflt))
    nv.nvmlDeviceGetPowerManagementLimitConstraints(dev, ctypes.byref(mn), ctypes.byref(mx))
    print(f"power limit {lim.value / 1000:.0f} W (default {dflt.value / 1000:.0f}, range {mn.value / 1000:.0f}..{mx.value / 1000:.0f})")


if len(sys.argv) == 1:
    show()
elif sys.argv[1] == "set":
    ok(nv.nvmlDeviceSetGpcClkVfOffset(dev, int(sys.argv[2])), "core offset")
    ok(nv.nvmlDeviceSetMemClkVfOffset(dev, int(sys.argv[3])), "memory offset")
    if len(sys.argv) > 4:
        ok(nv.nvmlDeviceSetPowerManagementLimit(dev, int(float(sys.argv[4]) * 1000)), "power limit")
    show()
elif sys.argv[1] == "reset":
    dflt = ctypes.c_uint()
    nv.nvmlDeviceGetPowerManagementDefaultLimit(dev, ctypes.byref(dflt))
    ok(nv.nvmlDeviceSetGpcClkVfOffset(dev, 0), "core offset")
    ok(nv.nvmlDeviceSetMemClkVfOffset(dev, 0), "memory offset")
    ok(nv.nvmlDeviceSetPowerManagementLimit(dev, dflt.value), "power limit")
    show()
