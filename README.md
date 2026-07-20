# AudioCowboy 🤠🔊

A [Flow Launcher](https://www.flowlauncher.com/) plugin to **quickly switch the default audio input/output device** and **save/load device profiles** — a rofi-style multi-layer menu under a single keyword.

```
ac            →  🔊 Output   🎤 Input   📁 Profiles   💾 Save
ac o [filter] →  pick the default output (playback) device
ac i [filter] →  pick the default input  (recording) device
ac s <name>   →  save the current input+output as a named profile
ac p [filter] →  list profiles → Enter applies; right-click → Apply / Delete
```

Switching sets **all three audio roles** (Console + Multimedia + Communications), so apps like Teams / Discord / Zoom follow the change too.

---

## How it works

Flow Launcher's plugin model has no native nested menu, so AudioCowboy fakes the rofi
multi-layer experience by **rewriting the search box** (`Flow.Launcher.ChangeQuery`)
to drill down a level while keeping the window open. One keyword (`ac`), several
sub-commands.

There is no public Windows API to *set* the default device — every tool wraps the
undocumented `IPolicyConfig` COM interface. AudioCowboy uses **`pycaw`** (pure Python)
as its default backend, so the released plugin needs **no external executable**. If a
NirSoft **`svcl.exe`** is present (in `bin\` or on `PATH`), it's used instead. No admin
rights are required either way.

Profiles store each device by its **MMDevice endpoint ID** (stable across reboots and
unique even for two identical headsets), not by name — so a profile re-selects the
right device even when friendly names collide.

---

## Install

**From the Flow Launcher plugin store** (once listed): open Flow, type
`pm install AudioCowboy`, or find it in Settings → Plugin Store.

**From a release zip** (or to test before the store listing):
```
pm install https://github.com/True347/AudioCowboy/releases/latest/download/Flow.Launcher.Plugin.AudioCowboy.zip
```
The release zip bundles the pure-Python backend (`lib/`), so it works out of the box —
no setup step. Restart Flow (or reload plugins) and type `ac`.

**Manual / from source** (developers): copy the folder into
`%APPDATA%\FlowLauncher\Plugins\AudioCowboy\`, then vendor the backend with
`pip install -r requirements.txt -t lib`. Restart Flow.
Optional: `powershell -File setup.ps1` adds `bin\svcl.exe`, which is used in preference
to pycaw when present.

---

## Usage

| You type | What happens |
|---|---|
| `ac` | Top menu. Each item drills into the next layer; the current default devices are shown. |
| `ac o` | List active **output** devices. The current default is marked `✓`. Enter sets a new default. |
| `ac o hdmi` | Same, filtered to devices whose name contains "hdmi". |
| `ac i` | List active **input** devices; Enter sets the default. |
| `ac s Gaming` | Save the current output+input devices as a profile named "Gaming" (overwrites if it exists). |
| `ac p` | List saved profiles. Enter applies a profile; **Shift+Enter** opens its context menu (Apply / Delete). A `⚠` marks a profile whose device is currently unplugged. |

On a device, **Shift+Enter** offers *Set for all roles* and *Set as Communication device only*.

---

## Profiles & data

Profiles are stored as JSON **outside** the plugin folder (so they survive plugin updates):

```
%APPDATA%\FlowLauncher\Settings\Plugins\AudioCowboy\profiles.json
```

```jsonc
{
  "schemaVersion": 1,
  "profiles": [
    {
      "name": "Gaming",
      "created": "2026-06-17T10:32:00Z",
      "output": { "endpointId": "{0.0.0.00000000}.{guid}", "friendlyName": "Speakers (Realtek)" },
      "input":  { "endpointId": "{0.0.1.00000000}.{guid}", "friendlyName": "Mic (HyperX QuadCast)" }
    }
  ]
}
```

Writes are atomic (temp file + `os.replace`), so a crash mid-write can't corrupt the file.

---

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `svcl_path` | *(empty)* | Path to an optional `svcl.exe`. Empty = auto-detect: `bin\svcl.exe`, then the plugin folder, then `PATH`. If none is found, the bundled pycaw backend is used. |
| `show_disconnected` | off | Also list unplugged / disabled endpoints. |

---

## Troubleshooting

- **"⚠ Audio backend unavailable"** — the bundled pycaw backend (in `lib/`) failed to load;
  reinstall the plugin. Running from source? Vendor it with `pip install -r requirements.txt -t lib`.
- **Antivirus flags `svcl.exe`** — it's a NirSoft false positive; allow it, or just don't install
  it (it's optional — the release doesn't ship it).
- **A device won't switch** — make sure it's *Active* (plugged in / enabled) in Windows Sound settings.
- **Nothing happens / errors** — check Flow's logs at `%APPDATA%\FlowLauncher\Logs\`.

---

## Backends

| Backend | When used | Notes |
|---|---|---|
| **pycaw** (default) | always, unless svcl.exe is present | [`pycaw`](https://github.com/AndreMiras/pycaw) `>= 20251023` (added `SetDefaultDevice`) + `comtypes`. Pure Python — vendored into `lib/`. This is what ships in the release. |
| **svcl.exe** (optional) | if `bin\svcl.exe` exists or it's on `PATH`, or `svcl_path` is set | NirSoft SoundVolumeCommandLine. Add it manually, or run `setup.ps1` from the source repo (it isn't in the release zip). Not redistributed (AV false positives). |

Both produce the same MMDevice endpoint IDs, so profiles are interchangeable between them.

To publish to the Flow plugin store, see [publish/PUBLISHING.md](publish/PUBLISHING.md).

---

## Development

```
plugin.json          # manifest (keyword: ac, Language: python)
main.py              # JSON-RPC entry + router + actions
audio.py             # pycaw backend (+ optional svcl.exe backend)
profiles.py          # profiles.json CRUD (atomic, update-safe path)
SettingsTemplate.yaml
setup.ps1            # downloads the optional bin/svcl.exe (not shipped in the release)
Images/              # icon set
tools/gen_icons.py   # regenerate icons (Pillow)
tests/               # smoke_test.py (offline) + inspect_live.py / inspect_actions.py
docs/RESEARCH.md     # design + feasibility research report
```

Run the offline tests (no Flow / svcl needed):

```powershell
python tests\smoke_test.py
```

Inspect live output against your real devices:

```powershell
python tests\inspect_live.py        # read-only: menus + device lists
python tests\inspect_actions.py     # save/load/delete in a temp dir (no-op switch)
```

### Why one keyword instead of `aci`/`aco`/`acs`/`acp`?

In Flow Launcher's V1 Python model (`Language: "python"`), the request the plugin
receives **does not include which action keyword fired** — only the search text after
it. So separate keywords couldn't be told apart on an empty query. A single keyword
with sub-commands (`ac o`, `ac i`, …) is the robust choice and faithfully reproduces
the original rofi single-entry, multi-layer menu. (Distinguishing keywords would
require the newer `Python_v2` protocol.)

---

## Credits

- [pycaw](https://github.com/AndreMiras/pycaw) — the pure-Python Core Audio backend that ships with the plugin.
- [NirSoft SoundVolumeView / svcl](https://www.nirsoft.net/utils/sound_volume_command_line.html) — optional alternative backend.
- [Flow Launcher](https://github.com/Flow-Launcher/Flow.Launcher) — the launcher and plugin API.
- Inspired by [SoundSwitch](https://github.com/Belphemur/SoundSwitch) and rofi audio-menu workflows.
