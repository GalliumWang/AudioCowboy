"""Audio backend for AudioCowboy.

Backend: ``pycaw`` (>= 20251023, which added ``AudioUtilities.SetDefaultDevice``),
vendored into ``lib/`` and shipped in the release — pure Python, no external executable.
There is no public Windows API to *set* the default device, so every tool wraps the
undocumented ``IPolicyConfig`` COM interface; pycaw does it in-process. It is
feature-detected and fully guarded, so a missing/old pycaw degrades to the "backend
missing" path rather than raising.

Device identity is the Windows MMDevice endpoint ID string (pycaw ``device.id``),
e.g. ``{0.0.0.00000000}.{guid}`` — stable across reboots and unique even for two
identical devices. Profiles persist this id, never the name.
"""
import warnings


class AudioError(Exception):
    """A backend operation failed."""


class AudioBackendUnavailable(AudioError):
    """No usable backend — the pycaw backend failed to load."""


# --------------------------------------------------------------------------- #
# pycaw backend — the only backend (guarded / feature-detected)
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
                "is_default_comm": False,  # pycaw can't read the communications default
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
        # classify it as a hard failure rather than an unverified success.
        raise AudioError("pycaw could not set the default device: %s" % exc)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def get_devices(include_inactive=False):
    """Return all render+capture endpoint devices (one backend call)."""
    if _pycaw_ready():
        # pycaw warns (to stderr) when an endpoint's properties raise a COMError — seen
        # with some JBL / virtual-audio devices. Flow treats ANY stderr as fatal, so
        # contain those warnings here (main.py also suppresses globally as a backstop).
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return _pycaw_devices(include_inactive)
    raise AudioBackendUnavailable("pycaw backend unavailable")


def set_default(item_id, role="all"):
    """Set the default device (role 'all' = Console+Multimedia+Communications)."""
    if _pycaw_ready():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return _pycaw_set_default(item_id, role)
    raise AudioBackendUnavailable("pycaw backend unavailable")


def _output_volume_endpoint():
    """Resolve the current multimedia output each time, including virtual outputs."""
    from pycaw.pycaw import AudioUtilities
    device = AudioUtilities.GetSpeakers()
    if device is None:
        raise AudioError("No default output device is available")
    return device, device.EndpointVolume


def _volume_state(device, endpoint):
    return {"id": _pycaw_device_id(device),
            "friendly": getattr(device, "FriendlyName", None) or _pycaw_device_id(device),
            "percent": float(endpoint.GetMasterVolumeLevelScalar()) * 100.0,
            "muted": bool(endpoint.GetMute())}


def get_output_volume():
    """Read Windows master volume (0-100) and mute state for the current output."""
    if not _pycaw_ready():
        raise AudioBackendUnavailable("pycaw backend unavailable")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            device, endpoint = _output_volume_endpoint()
            return _volume_state(device, endpoint)
        except Exception as exc:
            raise AudioError("Could not read output volume: %s" % exc) from exc


def set_output_volume(percent):
    """Set a percentage, unmute positive levels, and read back the same endpoint.

    Resolve at action time so a default changed since opening the menu is respected.
    Zero lowers the scalar to zero; it does not change the endpoint's mute flag.
    """
    if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not 0 <= percent <= 100:
        raise ValueError("Volume must be a number between 0 and 100")
    if not _pycaw_ready():
        raise AudioBackendUnavailable("pycaw backend unavailable")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            device, endpoint = _output_volume_endpoint()
            endpoint.SetMasterVolumeLevelScalar(percent / 100.0, None)
            if percent > 0:
                endpoint.SetMute(0, None)
            return _volume_state(device, endpoint)
        except Exception as exc:
            raise AudioError("Could not set or verify output volume: %s" % exc) from exc


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
