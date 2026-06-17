"""Live save/list/load/delete check using a TEMP profiles dir.

Saves the CURRENT devices as a profile then loads it — so the "switch" is a no-op
(current device -> same device) and your real default audio device is not changed.
Profiles are written under a temp APPDATA, so your real Flow config is untouched.

    python tests/inspect_actions.py
"""
import os
import sys
import json
import shutil
import tempfile
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, "FlowLauncher"))  # forces profiles into temp APPDATA
    env = os.environ.copy()
    env["APPDATA"] = tmp
    env["PYTHONIOENCODING"] = "utf-8"

    def call(method, params):
        req = {"method": method, "parameters": params, "settings": {}}
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), json.dumps(req)],
                              capture_output=True, env=env)
        out = proc.stdout.decode("utf-8")
        err = proc.stderr.decode("utf-8", "replace")
        if err.strip():
            print("  !! stderr:", err.strip())
        try:
            return json.loads(out)
        except ValueError:
            print("  !! unparseable:", repr(out[:200]))
            return {}

    def msg(obj):
        if obj.get("method") == "Flow.Launcher.ShowMsg":
            return "ShowMsg: %s — %s" % (obj["parameters"][0], obj["parameters"][1])
        return json.dumps(obj, ensure_ascii=False)

    try:
        print("save_profile('NoOpTest'):   ", msg(call("save_profile", ["NoOpTest"])))

        obj = call("query", ["p"])
        print("query 'ac p':")
        for r in obj.get("result", []):
            print("   -", r["Title"], "|", r["SubTitle"])

        print("load_profile('NoOpTest'):   ", msg(call("load_profile", ["NoOpTest"])))
        print("delete_profile('NoOpTest'): ", msg(call("delete_profile", ["NoOpTest"])))
        print("load_profile('Ghost'):      ", msg(call("load_profile", ["Ghost"])))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
