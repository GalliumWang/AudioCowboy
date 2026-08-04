"""Offline smoke tests for AudioCowboy — no Flow Launcher or real audio required.

Exercises: profiles CRUD round-trip, device helpers, and the JSON-RPC wire layer
(main.py invoked as a subprocess, the way Flow invokes it).

    python tests/smoke_test.py
"""
import os
import sys
import json
import shutil
import tempfile
import importlib
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_profiles():
    tmp = tempfile.mkdtemp()
    os.environ["APPDATA"] = tmp
    os.makedirs(os.path.join(tmp, "FlowLauncher"))
    import profiles
    importlib.reload(profiles)

    assert profiles.list_profiles() == []
    profiles.save_profile(
        "Gaming",
        output={"id": "{0.0.0.x}.{out}", "friendly": "Speakers (Realtek)"},
        input={"id": "{0.0.1.x}.{in}", "friendly": "Mic (HyperX)"},
    )
    p = profiles.get_profile("gaming")  # case-insensitive lookup
    assert p and p["output"]["endpointId"] == "{0.0.0.x}.{out}"
    assert p["input"]["friendlyName"] == "Mic (HyperX)"
    assert p["output"]["friendlyName"] == "Speakers (Realtek)"

    # overwrite keeps created, adds updated, and can clear a side
    profiles.save_profile("Gaming", output={"id": "X", "friendly": "New"}, input=None)
    p = profiles.get_profile("Gaming")
    assert p["output"]["endpointId"] == "X" and p["input"] is None
    assert "created" in p and "updated" in p
    assert len(profiles.list_profiles()) == 1

    assert profiles.delete_profile("GAMING") is True
    assert profiles.list_profiles() == []
    assert profiles.delete_profile("nope") is False

    shutil.rmtree(tmp, ignore_errors=True)
    print("OK  profiles CRUD")


def test_corruption_backup():
    tmp = tempfile.mkdtemp()
    os.environ["APPDATA"] = tmp
    os.makedirs(os.path.join(tmp, "FlowLauncher"))
    import profiles
    importlib.reload(profiles)

    # seed a valid profile, then corrupt the file on disk
    profiles.save_profile("Keep", output={"id": "X", "friendly": "Spk"}, input=None)
    path = profiles.profiles_path()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{ this is not valid json ]")

    # load() must not raise, must back up the corrupt file, and must start fresh
    doc = profiles.load()
    assert doc["profiles"] == []
    assert os.path.exists(path + ".bak"), "corrupt file should be preserved as .bak"

    # a subsequent save works and does not resurrect corruption
    profiles.save_profile("Fresh", output={"id": "Y", "friendly": "New"}, input=None)
    assert [p["name"] for p in profiles.list_profiles()] == ["Fresh"]

    shutil.rmtree(tmp, ignore_errors=True)
    print("OK  corrupt-file backup + recovery")


def test_audio_helpers():
    import audio
    importlib.reload(audio)
    spk = {"id": "{0.0.0.00000000}.{guid}", "direction": "render", "is_default": True,
           "friendly": "Speakers (Realtek)", "state": "Active", "name": "Speakers",
           "device_name": "Realtek", "is_default_comm": False, "cmd_id": ""}
    mic = {"id": "a", "direction": "capture", "is_default": True, "friendly": "Mic",
           "state": "Active", "name": "Mic", "device_name": "", "is_default_comm": False, "cmd_id": ""}
    devs = [spk, mic]
    render, capture = audio.split_by_direction(devs)
    assert len(render) == 1 and len(capture) == 1
    assert audio.find_default(devs, "render")["friendly"] == "Speakers (Realtek)"
    assert audio.find_default(devs, "capture")["friendly"] == "Mic"
    assert audio.find_by_id(devs, "a")["direction"] == "capture"
    assert audio.find_by_id(devs, "missing") is None
    print("OK  audio helpers")


def test_pycaw_warning_suppressed():
    """A pycaw warning (as a quirky JBL/virtual endpoint triggers) must never escape
    get_devices() — Flow treats any plugin stderr as fatal (InvalidDataException)."""
    import warnings
    import audio
    importlib.reload(audio)

    def _warn_then_return(include_inactive=False):
        warnings.warn("COMError attempting to get property 67", UserWarning)
        return []

    audio._pycaw_ready = lambda: True
    audio._pycaw_devices = _warn_then_return

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        devices = audio.get_devices()
    assert devices == []
    assert not caught, "pycaw warning leaked past get_devices() (fatal to Flow)"
    print("OK  pycaw warning suppressed (stderr stays clean)")


def run_main(req):
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "main.py"), json.dumps(req)],
        capture_output=True,
    )
    return proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8", "replace")


def test_wire():
    out, err = run_main({"method": "query", "parameters": [""], "settings": {}})
    assert err.strip() == "", "stderr not empty:\n" + err
    obj = json.loads(out)
    assert "result" in obj and isinstance(obj["result"], list) and obj["result"], out

    # sub-menu routing returns valid JSON regardless of backend availability
    for q in ("o", "i", "s gaming", "p"):
        out_q, err_q = run_main({"method": "query", "parameters": [q], "settings": {}})
        assert err_q.strip() == "", "stderr for %r:\n%s" % (q, err_q)
        json.loads(out_q)

    # profile context menu -> Apply + Delete
    out_c, _ = run_main({"method": "context_menu", "parameters": [["profile", "Gaming"]], "settings": {}})
    objc = json.loads(out_c)
    assert len(objc["result"]) == 2
    assert objc["result"][0]["JsonRPCAction"]["method"] == "load_profile"
    assert objc["result"][1]["JsonRPCAction"]["method"] == "delete_profile"

    # device context menu -> all roles + comms only
    out_d, _ = run_main({"method": "context_menu",
                         "parameters": [["device", "render", "{id}", "Speakers"]], "settings": {}})
    objd = json.loads(out_d)
    assert objd["result"][0]["JsonRPCAction"]["method"] == "set_default_output"
    assert objd["result"][1]["JsonRPCAction"]["method"] == "set_default_comm"

    # drill-down result shape: ChangeQuery + keep-open flag
    top = json.loads(run_main({"method": "query", "parameters": [""], "settings": {}})[0])
    drill_items = [r for r in top["result"]
                   if r.get("JsonRPCAction", {}).get("method") == "Flow.Launcher.ChangeQuery"]
    # top menu has drill items only when a backend is present; if pycaw failed to load it's
    # a single "⚠ Audio backend unavailable" item — accept either, but validate any drills.
    for r in drill_items:
        act = r["JsonRPCAction"]
        assert act["parameters"][0].startswith("ac ")
        assert act["parameters"][1] is True
        assert act.get("DontHideAfterAction") is True

    # unknown method -> empty result, no crash
    out_u, err_u = run_main({"method": "bogus", "parameters": [], "settings": {}})
    assert err_u.strip() == ""
    assert json.loads(out_u) == {"result": []}
    print("OK  JSON-RPC wire layer (%d drill items in top menu)" % len(drill_items))


if __name__ == "__main__":
    test_profiles()
    test_corruption_backup()
    test_audio_helpers()
    test_pycaw_warning_suppressed()
    test_wire()
    print("\nALL PASS")
