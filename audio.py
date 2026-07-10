"""Audio backend for AudioCowboy.

Primary mechanism: NirSoft ``svcl.exe`` (SoundVolumeCommandLine) — lists devices as
JSON and sets the default render/capture device for all roles. There is no public
Windows API to *set* the default device, so every tool wraps the undocumented
``IPolicyConfig`` COM interface; svcl is the battle-tested wrapper we bundle.

Optional fallback: ``pycaw`` (>= 20251023, which added ``AudioUtilities.SetDefaultDevice``)
is used only when svcl.exe is unavailable *and* pycaw is importable. It is feature-detected
and fully guarded, so a missing/old pycaw simply degrades to the "backend missing" path.

Device identity is the Windows MMDevice endpoint ID string (svcl "Item ID",
pycaw ``device.id``), e.g. ``{0.0.0.00000000}.{guid}`` — stable across reboots and
unique even for two identical devices. Profiles persist this id, never the name.
"""
import os
import json
import tempfile
import subprocess
import warnings

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

# Windows: don't flash a console window when spawning svcl.exe.
_CREATE_NO_WINDOW = 0x08000000

# Columns we ask svcl to emit; the header strings become the JSON keys.
_COLUMNS = (
    "Name,Type,Direction,Device Name,Default,Default Multimedia,"
    "Default Communications,Item ID,Command-Line Friendly ID,Device State"
)

# Set by configure(); lets the user point at a non-bundled svcl.exe via settings.
_SVCL_OVERRIDE = None


class AudioError(Exception):
    """A backend operation failed."""


class AudioBackendUnavailable(AudioError):
    """No usable backend (no svcl.exe and no working pycaw)."""


_SVCL_CACHE = (False, None)  # (resolved?, path)


def configure(svcl_path=None):
    """Apply runtime settings (called from the plugin before each operation)."""
    global _SVCL_OVERRIDE, _SVCL_CACHE
    _SVCL_OVERRIDE = (svcl_path or "").strip() or None
    _SVCL_CACHE = (False, None)  # override may have changed; invalidate cache


# --------------------------------------------------------------------------- #
# svcl.exe discovery
# --------------------------------------------------------------------------- #
def find_svcl():
    """Return an absolute path to svcl.exe, or None if not found (memoized per process)."""
    global _SVCL_CACHE
    resolved, path = _SVCL_CACHE
    if resolved:
        return path
    candidates = []
    if _SVCL_OVERRIDE:
        candidates.append(_SVCL_OVERRIDE)
    candidates.append(os.path.join(PLUGIN_DIR, "bin", "svcl.exe"))
    candidates.append(os.path.join(PLUGIN_DIR, "svcl.exe"))
    found = None
    for c in candidates:
        if c and os.path.isfile(c):
            found = c
            break
    if found is None:
        from shutil import which  # last resort: rely on PATH
        found = which("svcl.exe")
    _SVCL_CACHE = (True, found)
    return found


def svcl_available():
    return find_svcl() is not None


def _run_svcl(args):
    exe = find_svcl()
    if not exe:
        raise AudioBackendUnavailable("svcl.exe not found")
    try:
        return subprocess.run(
            [exe] + list(args),
            capture_output=True,
            creationflags=_CREATE_NO_WINDOW,
            timeout=20,
        )
    except FileNotFoundError:
        raise AudioBackendUnavailable("svcl.exe not found at %s" % exe)
    except subprocess.TimeoutExpired:
        raise AudioError("svcl.exe timed out")


def _truthy(value):
    return bool((value or "").strip())


def _parse_entry(e):
    name = (e.get("Name") or "").strip()
    devname = (e.get("Device Name") or "").strip()
    direction_raw = (e.get("Direction") or "").strip().lower()
    if devname and devname.lower() != name.lower():
        friendly = "%s (%s)" % (name, devname)
    else:
        friendly = name
    return {
        "id": (e.get("Item ID") or "").strip(),
        "name": name,
        "device_name": devname,
        "friendly": friendly or name or "(unnamed device)",
        "direction": "render" if direction_raw == "render"
                     else ("capture" if direction_raw == "capture" else direction_raw),
        "is_default": _truthy(e.get("Default")) or _truthy(e.get("Default Multimedia")),
        "is_default_comm": _truthy(e.get("Default Communications")),
        "state": (e.get("Device State") or "").strip(),
        "cmd_id": (e.get("Command-Line Friendly ID") or "").strip(),
    }


def _svcl_devices(include_inactive=False):
    # svcl does NOT honour the empty-filename "write to stdout" convention, so we
    # export to a temp file (UTF-8 with BOM) and read it back.
    fd, tmp = tempfile.mkstemp(prefix="acowboy-", suffix=".json")
    os.close(fd)
    try:
        proc = _run_svcl(["/sjson", tmp, "/Columns", _COLUMNS])
        try:
            with open(tmp, "rb") as fh:
                raw_bytes = fh.read()
        except OSError:
            raw_bytes = b""
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    text = raw_bytes.decode("utf-8-sig", errors="replace").strip()
    if not text:
        # NirSoft exit codes are unreliable, so empty output (not "[]") is our
        # real signal that svcl failed — surface it instead of faking "no devices".
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise AudioError("svcl produced no output (exit %s)%s"
                         % (proc.returncode, (": " + err) if err else ""))
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise AudioError("Could not parse svcl output: %s" % exc)
    out = []
    for e in raw:
        if (e.get("Type") or "").strip() != "Device":
            continue
        d = _parse_entry(e)
        if d["direction"] not in ("render", "capture") or not d["id"]:
            continue
        if not include_inactive and d["state"] and d["state"].lower() != "active":
            continue
        out.append(d)
    return out


def _svcl_set_default(item_id, role="all"):
    proc = _run_svcl(["/SetDefault", item_id, role])
    return proc.returncode == 0


# --------------------------------------------------------------------------- #
# pycaw fallback (optional, guarded — only used when svcl is unavailable)
# --------------------------------------------------------------------------- #
def _pycaw_ready():
    try:
        from pycaw.pycaw import AudioUtilities  # noqa: F401
        return hasattr(AudioUtilities, "SetDefaultDevice")
    except Exception:
        return False


def _pycaw_device_id(d):
    """pycaw devices expose `.id`; the default getters may return an IMMDevice (GetId())."""
    if d is None:
        return None
    return getattr(d, "id", None) or (d.GetId() if hasattr(d, "GetId") else None)


def _pycaw_devices(include_inactive=False):
    from pycaw.pycaw import AudioUtilities
    from pycaw.constants import EDataFlow, DEVICE_STATE

    state = DEVICE_STATE.MASK_ALL.value if include_inactive else DEVICE_STATE.ACTIVE.value
    default_ids = set()
    for getter in (AudioUtilities.GetSpeakers, AudioUtilities.GetMicrophone):
        try:
            default_ids.add(_pycaw_device_id(getter()))
        except Exception:
            pass
    default_ids.discard(None)

    out = []
    for flow, direction in ((EDataFlow.eRender.value, "render"),
                            (EDataFlow.eCapture.value, "capture")):
        try:
            devs = AudioUtilities.GetAllDevices(data_flow=flow, device_state=state)
        except Exception:
            devs = []  # GetAllDevices can COMError on some machines; degrade per-flow
        for dev in devs:
            dev_id = _pycaw_device_id(dev)
            if not dev_id:
                continue
            friendly = getattr(dev, "FriendlyName", None) or dev_id
            out.append({
                "id": dev_id,
                "name": friendly,
                "device_name": "",
                "friendly": friendly,
                "direction": direction,
                "is_default": dev_id in default_ids,
                "is_default_comm": False,
                "state": "Active",
                "cmd_id": "",
            })
    return out


def _pycaw_set_default(item_id, role="all"):
    from pycaw.pycaw import AudioUtilities
    try:
        from pycaw.constants import ERole
        roles = [ERole.eConsole, ERole.eMultimedia, ERole.eCommunications] if role == "all" \
            else [ERole.eCommunications] if role == "2" else None
        try:
            AudioUtilities.SetDefaultDevice(item_id, roles=roles)
        except TypeError:
            AudioUtilities.SetDefaultDevice(item_id)  # older pycaw signature (all roles)
        return True
    except Exception as exc:
        # A pycaw exception is a definite failure — raise (don't return False) so callers
        # classify it as a hard failure, matching how the svcl path signals failure.
        raise AudioError("pycaw could not set the default device: %s" % exc)


# --------------------------------------------------------------------------- #
# Public API (svcl first, pycaw fallback)
# --------------------------------------------------------------------------- #
def get_devices(include_inactive=False):
    """Return all render+capture endpoint devices (one backend call)."""
    if svcl_available():
        return _svcl_devices(include_inactive)
    if _pycaw_ready():
        # pycaw warns (to stderr) when an endpoint's properties raise a COMError — seen
        # with some JBL / virtual-audio devices. Flow treats ANY stderr as fatal, so
        # contain those warnings here (main.py also suppresses globally as a backstop).
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return _pycaw_devices(include_inactive)
    raise AudioBackendUnavailable("svcl.exe not found and pycaw unavailable")


def set_default(item_id, role="all"):
    """Set the default device (role 'all' = Console+Multimedia+Communications)."""
    if svcl_available():
        return _svcl_set_default(item_id, role)
    if _pycaw_ready():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return _pycaw_set_default(item_id, role)
    raise AudioBackendUnavailable("svcl.exe not found and pycaw unavailable")


def split_by_direction(devices):
    render = [d for d in devices if d["direction"] == "render"]
    capture = [d for d in devices if d["direction"] == "capture"]
    return render, capture


def find_default(devices, direction):
    for d in devices:
        if d["direction"] == direction and d["is_default"]:
            return d
    return None


def find_by_id(devices, item_id):
    for d in devices:
        if d["id"] == item_id:
            return d
    return None
