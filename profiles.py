"""Profile persistence for AudioCowboy.

A profile is a named snapshot of {default output device, default input device},
each stored as {endpointId, friendlyName}. The endpoint id (MMDevice id) is the
source of truth when applying a profile; the friendly name is only a display label.

Profiles live OUTSIDE the plugin install folder (which Flow wipes on every update),
under the roaming settings root:

    %APPDATA%\\FlowLauncher\\Settings\\Plugins\\AudioCowboy\\profiles.json

Writes are atomic (temp file + os.replace) so a crash mid-write can't corrupt the file.
"""
import os
import json
import tempfile
from datetime import datetime, timezone

PLUGIN_NAME = "AudioCowboy"  # must match plugin.json "Name"
SCHEMA_VERSION = 1

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _settings_dir():
    """Update-safe directory for this plugin's data."""
    appdata = os.getenv("APPDATA")
    if appdata and os.path.isdir(os.path.join(appdata, "FlowLauncher")):
        base = os.path.join(appdata, "FlowLauncher", "Settings", "Plugins", PLUGIN_NAME)
    else:
        # Portable install: plugin dir is .../<root>/Plugins/<Name>-<ver>; settings
        # live at .../<root>/Settings/Plugins/<Name>.
        root = os.path.dirname(os.path.dirname(_PLUGIN_DIR))
        base = os.path.join(root, "Settings", "Plugins", PLUGIN_NAME)
    os.makedirs(base, exist_ok=True)
    return base


def profiles_path():
    return os.path.join(_settings_dir(), "profiles.json")


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_doc():
    return {"schemaVersion": SCHEMA_VERSION, "profiles": []}


def load():
    """Return the profiles document; never raises (returns an empty doc on error)."""
    path = profiles_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return _empty_doc()
    except ValueError:
        # Corrupt JSON: preserve it as a .bak so a subsequent save can't silently
        # destroy the user's profiles, then start fresh.
        _backup_corrupt(path)
        return _empty_doc()
    except OSError:
        # Unreadable (locked / permissions): degrade without clobbering the file.
        return _empty_doc()
    if not isinstance(data, dict):
        _backup_corrupt(path)
        return _empty_doc()
    if not isinstance(data.get("profiles"), list):
        # Schema-invalid: back it up too, so the next save can't silently clobber it.
        _backup_corrupt(path)
        return _empty_doc()
    data.setdefault("schemaVersion", SCHEMA_VERSION)
    return data


def _backup_corrupt(path):
    try:
        if not os.path.exists(path):
            return
        bak = path + ".bak"
        if os.path.exists(bak):
            # Keep the first .bak; timestamp later ones so we don't lose forensic copies.
            bak = "%s.%s.bak" % (path, datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))
        os.replace(path, bak)
    except OSError:
        pass


def _save(data):
    path = profiles_path()
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".profiles-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def list_profiles():
    return load().get("profiles", [])


def get_profile(name):
    name_l = (name or "").strip().lower()
    for p in load().get("profiles", []):
        if (p.get("name") or "").strip().lower() == name_l:
            return p
    return None


def save_profile(name, output=None, input=None):
    """Create or overwrite a profile. ``output``/``input`` are {id, friendlyName} dicts."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Profile name cannot be empty")
    data = load()
    entry = {
        "name": name,
        "created": _now_iso(),
        "output": _device_record(output),
        "input": _device_record(input),
    }
    profs = data["profiles"]
    for i, p in enumerate(profs):
        if (p.get("name") or "").strip().lower() == name.lower():
            entry["created"] = p.get("created", entry["created"])
            entry["updated"] = _now_iso()
            profs[i] = entry
            break
    else:
        profs.append(entry)
    _save(data)
    return entry


def delete_profile(name):
    name_l = (name or "").strip().lower()
    data = load()
    before = len(data["profiles"])
    data["profiles"] = [p for p in data["profiles"]
                        if (p.get("name") or "").strip().lower() != name_l]
    removed = len(data["profiles"]) < before
    if removed:
        _save(data)
    return removed


def _device_record(device):
    if not device:
        return None
    dev_id = device.get("id") or device.get("endpointId")
    if not dev_id:
        return None
    return {
        "endpointId": dev_id,
        "friendlyName": device.get("friendly") or device.get("friendlyName") or "",
    }
