"""Manual live check: invoke main.py the way Flow does and pretty-print results.

    python tests/inspect_live.py
"""
import os
import sys
import json
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def call(method, params, settings=None):
    req = {"method": method, "parameters": params, "settings": settings or {}}
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), json.dumps(req)],
                          capture_output=True)
    out = proc.stdout.decode("utf-8")
    err = proc.stderr.decode("utf-8", "replace")
    if err.strip():
        print("  !! stderr:", err.strip())
    try:
        return json.loads(out)
    except ValueError:
        print("  !! could not parse:", repr(out[:200]))
        return {"result": []}


def show(label, method, params):
    print("\n=== %s ===" % label)
    obj = call(method, params)
    for r in obj.get("result", []):
        act = r.get("JsonRPCAction", {})
        extra = ""
        if act.get("method") == "Flow.Launcher.ChangeQuery":
            extra = "   [drill -> %r keepOpen=%s]" % (act["parameters"][0], act.get("DontHideAfterAction"))
        elif act.get("method"):
            extra = "   [%s%s]" % (act["method"], tuple(act.get("parameters", [])))
        print("  - %s | %s%s" % (r["Title"], r["SubTitle"], extra))


if __name__ == "__main__":
    show("top menu (ac)", "query", [""])
    show("output list (ac o)", "query", ["o"])
    show("input list (ac i)", "query", ["i"])
    show("save menu (ac s Gaming)", "query", ["s Gaming"])
    show("profiles (ac p)", "query", ["p"])
