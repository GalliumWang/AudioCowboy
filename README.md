# AudioCowboy 🤠🔊

This fork of [True347/AudioCowboy](https://github.com/True347/AudioCowboy) adds an
optional **Boom3D compatibility mode**. Install the fork's release, then enable
**Boom3D compatibility mode** in Flow Settings → Plugins → AudioCowboy.

From **v1.0.9**, selecting an output, input, communication device, or profile hides
Flow immediately. Audio switching and verification continue, then Flow displays
the result notification. Finishing a switch does not hide a window you have reopened.
The plugin uses the `Python_v2` protocol supported by Flow 2.1.4.

From **v1.0.10**, use **`ac v`** (`ac vol`, `ac volume`, or `ac 音量`) to choose
**0%, 20%, 40%, 60%, 80%, or 100%** in that order. Click or press Enter to set the
Windows master volume of the current default output. Positive presets also unmute
the output. With Boom3D running, this controls the Windows volume of its default
virtual output. The menu shows the current volume and a checkmark for a matching
preset. Selecting a preset hides Flow first, then verifies and reports the result.

A [Flow Launcher](https://www.flowlauncher.com/) plugin to **quickly switch the default audio input/output device** and **save/load device profiles** — a rofi-style multi-layer menu under a single keyword.

```
ac            →  🔊 Output   🎤 Input   🔊 Volume   📁 Profiles   💾 Save
ac o [filter] →  pick the default output (playback) device
ac i [filter] →  pick the default input  (recording) device
ac v          →  set output volume: 0 / 20 / 40 / 60 / 80 / 100%
ac s <name>   →  save the current input+output as a named profile
ac p [filter] →  list profiles → Enter applies; right-click → Apply / Rename / Delete
ac r [filter] →  rename a profile (pick one, then type the new name)
ac d [filter] →  delete profiles (Enter removes; the list stays open)
```

Switching sets **all three audio roles** (Console + Multimedia + Communications), so apps like Teams / Discord / Zoom follow the change too.

---

## How it works

Flow Launcher's plugin model has no native nested menu, so AudioCowboy fakes the rofi
multi-layer experience by **rewriting the search box** (`Flow.Launcher.ChangeQuery`)
to drill down a level while keeping the window open. One keyword (`ac`), several
sub-commands.

There is no public Windows API to *set* the default device — every tool wraps the
undocumented `IPolicyConfig` COM interface. AudioCowboy uses **`pycaw`** (pure Python),
so the plugin needs **no external executable** and no admin rights.

Profiles store each device by its **MMDevice endpoint ID** (stable across reboots and
unique even for two identical headsets), not by name — so a profile re-selects the
right device even when friendly names collide.

---

## Install

The Flow Launcher plugin store installs the **upstream** version of AudioCowboy.
For this fork's Boom3D fix, install the fork release zip below.

**From a release zip** (or to test before the store listing):
```
pm install https://github.com/GalliumWang/AudioCowboy/releases/latest/download/Flow.Launcher.Plugin.AudioCowboy.zip
```
The release zip bundles the pure-Python backend (`lib/`), so it works out of the box —
no setup step. Restart Flow after updating and type `ac`.

**Manual / from source** (developers): copy the folder into
`%APPDATA%\FlowLauncher\Plugins\AudioCowboy\`, then vendor the backend with
`pip install -r requirements.txt -t lib`. Restart Flow.

---

## Usage

| You type | What happens |
|---|---|
| `ac` | Top menu. Each item drills into the next layer; the current default devices are shown. |
| `ac o` | List active **output** devices. The current default is marked `✓`. Enter sets a new default. |
| `ac o hdmi` | Same, filtered to devices whose name contains "hdmi". |
| `ac i` | List active **input** devices; Enter sets the default. |
| `ac v` | List output volume presets in ascending order: **0 / 20 / 40 / 60 / 80 / 100%**. Click or Enter applies; nonzero levels unmute. Aliases: `ac vol`, `ac volume`, `ac 音量`. |
| `ac s Gaming` | Save the current output+input devices as a profile named "Gaming" (overwrites if it exists). |
| `ac p` | List saved profiles. Enter applies a profile; **Shift+Enter** opens its context menu (Apply / Rename / Delete). A `⚠` marks a profile whose device is currently unplugged. The list also offers **Rename** and **Delete** entries. |
| `ac r` | Pick a profile, then type a new name (`Gaming → Streaming`) and press Enter. Renaming onto a name already in use is refused. |
| `ac d` | List profiles; Enter deletes the highlighted one. The list stays open so you can remove several in a row. |

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
| `show_disconnected` | off | Also list unplugged / disabled endpoints. |
| `boom3d_compatibility` | off | Accept an acknowledged output-switch request when the requested device is active and Windows defaults back to Boom3D's active virtual output. Input switches and backend errors retain normal checks. |

### Using Boom3D

Boom3D can switch the physical output and immediately restore **Speakers (Boom Audio)**
as the Windows default to preserve global effects. Normal default-device verification
then reports "Output device may not have changed" even though Boom switched outputs.

Enable **Boom3D compatibility mode** to handle this case for both direct output
switches and profile loading. The virtual default must have `Boom Audio`, `Boom3D`,
or `Boom 3D` in its endpoint name. Other defaults, unavailable targets, failed backend
requests, input failures, and unreadable defaults still receive normal diagnostics.
The confirmation says **switch requested (Boom3D)**: Windows exposes Boom's virtual
default, so AudioCowboy cannot independently verify Boom's final physical output.
The menu's default checkmark and saved snapshots continue to reflect the Windows
default (Boom's virtual device), rather than guessing the physical output.

Use **v1.0.8 or later**: v1.0.6 did not load saved settings for Flow's V1 action
requests, and v1.0.7 looked in Flow's executable installation directory instead of
its user-data directory. Both could leave compatibility mode off when selecting a
device even after enabling it in Flow's settings. Saved settings now come from the
user-data root containing the installed plugin, with the roaming directory as a fallback.

---

## Troubleshooting

- **"⚠ Audio backend unavailable"** — the bundled pycaw backend (in `lib/`) failed to load;
  reinstall the plugin. Running from source? Vendor it with `pip install -r requirements.txt -t lib`.
- **A device won't switch** — make sure it's *Active* (plugged in / enabled) in Windows Sound settings.
- **Nothing happens / errors** — check Flow's logs at `%APPDATA%\FlowLauncher\Logs\`.

---

## Backend

**pycaw** ([`pycaw`](https://github.com/AndreMiras/pycaw) `>= 20251023`, which added
`SetDefaultDevice`, plus `comtypes`) — pure Python, vendored into `lib/`. It's the only
backend, needs no external executable, and is what ships in the release.

To publish to the Flow plugin store, see [publish/PUBLISHING.md](publish/PUBLISHING.md).

---

## Development

```
plugin.json          # manifest (keyword: ac, Language: Python_v2)
main.py              # JSON-RPC entry + router + actions
audio.py             # pycaw backend
profiles.py          # profiles.json CRUD (atomic, update-safe path)
SettingsTemplate.yaml
Images/              # icon set
tools/gen_icons.py   # regenerate icons (Pillow)
tests/               # smoke_test.py (offline) + inspect_live.py / inspect_actions.py
docs/RESEARCH.md     # design + feasibility research report
```

Run the offline tests (no Flow needed):

```powershell
python tests\smoke_test.py
python -m unittest discover -s tests -p "test_*.py"
```

Inspect live output against your real devices:

```powershell
python tests\inspect_live.py        # read-only: menus + device lists
python tests\inspect_actions.py     # save/load/delete in a temp dir (no-op switch)
```

### Why one keyword instead of `aci`/`aco`/`acs`/`acp`?

The original V1 Python protocol did not include which action keyword fired, so
AudioCowboy used one keyword with sub-commands (`ac o`, `ac i`, …). Version 1.0.9
moves to `Python_v2` to hide Flow before audio operations finish, while preserving
the existing single-entry menu and commands.

---

## Credits

- [pycaw](https://github.com/AndreMiras/pycaw) — the pure-Python Core Audio backend that powers the plugin.
- [Flow Launcher](https://github.com/Flow-Launcher/Flow.Launcher) — the launcher and plugin API.
- Inspired by [SoundSwitch](https://github.com/Belphemur/SoundSwitch) and rofi audio-menu workflows.
