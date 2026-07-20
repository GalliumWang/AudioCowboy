"""Read-only diagnostic: compare the plugin's is_default detection against raw svcl.

Requires the OPTIONAL svcl.exe (see setup.ps1) — it diffs our parsing against raw svcl
output, so it cannot run on a pycaw-only install (which is what the release ships).

    python tests/diag_default.py
"""
import os
import sys
import json
import tempfile
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import audio

print("=== plugin get_devices(include_inactive=True) ===")
for d in audio.get_devices(include_inactive=True):
    print("  default=%-5s comm=%-5s state=%-10s %-7s ...%s  %s" % (
        d["is_default"], d["is_default_comm"], d["state"], d["direction"],
        d["id"][-10:], d["friendly"]))

print("\n=== raw svcl 'Device' rows ===")
exe = audio.find_svcl()
if not exe:
    print("  svcl.exe not found — this diagnostic needs the optional svcl backend "
          "(setup.ps1). The plugin itself runs fine on pycaw alone.")
    sys.exit(0)
fd, tmp = tempfile.mkstemp(suffix=".json")
os.close(fd)
subprocess.run([exe, "/sjson", tmp, "/Columns",
                "Name,Type,Direction,Default,Default Multimedia,Default Communications,Device State,Item ID"],
               creationflags=0x08000000)
with open(tmp, "rb") as f:
    raw = json.loads(f.read().decode("utf-8-sig"))
os.remove(tmp)
for e in raw:
    if e.get("Type") == "Device":
        print("  Default=%-8r Multimedia=%-8r Comm=%-8r %-7s %-9s %s" % (
            e.get("Default"), e.get("Default Multimedia"), e.get("Default Communications"),
            e.get("Direction"), e.get("Device State"), e.get("Name")))
