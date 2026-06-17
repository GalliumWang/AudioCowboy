# AudioCowboy — Flow Launcher Audio Device & Profile Switcher: Development Research Report

> A consolidated, implementation-ready research report for building **AudioCowboy**, a Flow Launcher plugin that switches the default audio input/output device and supports named profiles. Synthesized from five research streams and three adversarial fact-check verdicts. Where a verdict conflicts with a researcher, the verdict is treated as authoritative.

---

## 1. Executive Summary & Feasibility Verdict

**Verdict: Buildable cleanly, and the user's exact UX (`aci`/`aco`/`acs`/`acp`) maps well onto Flow Launcher with no native blockers.** Every capability required already exists in shipping tools; the only genuinely hard part — *setting* the Windows default device — has a well-encapsulated solution (`pycaw`) that does not require admin rights.

What makes it tractable:
- **Listing + reading current defaults** is fully supported by Microsoft's documented Core Audio API (`IMMDeviceEnumerator`) for both render (output) and capture (input).
- **Setting the default** has no public API, but a single, battle-tested mechanism (`IPolicyConfig::SetDefaultEndpoint`) is used by *every* tool in the ecosystem, and `pycaw` wraps it natively in Python via `AudioUtilities.SetDefaultDevice()`.
- **The multi-layer rofi menu** can be approximated faithfully using `Flow.Launcher.ChangeQuery` to rewrite the search box (drill-down) plus context menus (one secondary level).
- **Profiles** are a genuine gap in the existing Flow Launcher audio plugins — both shipping plugins are output-only, flat-list, no profiles. This is the differentiation opportunity.

**Biggest risks (in priority order):**

| Risk | Severity | Mitigation |
|---|---|---|
| `IPolicyConfig` is **undocumented & unsupported** by Microsoft; could break in a future Windows build. Every switcher depends on it. | High (but low probability) | Wrap all SET ops in try/except, log failures, and keep **bundled `svcl.exe` as a fallback path**. |
| **`pycaw`/`comtypes` ship native/compiled code** that is sensitive to Flow's *embedded* Python version. | Medium | Vendor deps into `lib/` built against a known Python version; document fallback to `svcl.exe`. |
| **Setting only one of three audio "roles"** is the classic bug — apps like Teams/Discord keep the old device. | Medium | Always set **all three roles** (Console, Multimedia, Communications). |
| **Device identity drift** — friendly names collide, indices renumber. | Medium | Persist the **opaque MMDevice endpoint ID string**, never the friendly name. |
| **No data must live in the install folder** (wiped on update). | Low | Persist profiles under `…\Settings\Plugins\<Name>\`. |

---

## 2. Flow Launcher Plugin Fundamentals

### 2.1 What a plugin is

A Flow Launcher plugin is just a **folder** containing a `plugin.json` manifest plus an entry point, installed under `%APPDATA%\FlowLauncher\Plugins\<Name>-<Version>\`. ([plugin.json.md](https://github.com/Flow-Launcher/docs/blob/main/plugin.json.md))

### 2.2 `plugin.json` schema (tailored to AudioCowboy)

Required fields: `ID` (32-hex UUID), `ActionKeyword`, `Name`, `Description`, `Author`, `Version` (semver — drives update detection), `Language`, `Website`, `IcoPath`, `ExecuteFileName`. `ActionKeyword: "*"` means "no keyword / global." ([plugin.json.md](https://github.com/Flow-Launcher/docs/blob/main/plugin.json.md))

> **Important:** the manifest declares a **single** default `ActionKeyword` (singular). Multiple keywords (`aci`/`aco`/`acs`/`acp`) are added **at runtime** via the `AddActionKeyword` API / user settings, *not* via a manifest array (per verdict #3). See §3 for how this affects the design.

```json
{
  "$schema": "https://www.flowlauncher.com/schemas/plugin.schema.json",
  "ID": "a1b2c3d4e5f64758697a8b9cad0eb1f2",
  "ActionKeyword": "ac",
  "Name": "AudioCowboy",
  "Description": "Switch and save audio input/output device profiles",
  "Author": "yourname",
  "Version": "1.0.0",
  "Language": "python",
  "Website": "https://github.com/yourname/Flow.Launcher.Plugin.AudioCowboy",
  "IcoPath": "Images\\app.png",
  "ExecuteFileName": "main.py"
}
```

> The `$schema` line gives IDE autocomplete/validation. `IcoPath` uses escaped backslashes in JSON; at runtime in Python results, forward slashes (`Images/app.png`) work too and are simpler. `ExecuteFileName` must be `main.py` for Python (the `.dll` for C#).

### 2.3 Languages & runtimes

Documented `Language` values: `csharp`, `fsharp`, `python`, `javascript`, `typescript`, `executable`. ([plugin.json.md](https://github.com/Flow-Launcher/docs/blob/main/plugin.json.md))

> ⚠️ Do **not** use `python_v2`/`pythonV2` in `Language` — the canonical value is `python`. The "v2" naming comes from the community `pyflowlauncher` library and the manifest repo's `plugin_api_v2` branch, not the manifest schema.

| Model | How it talks to Flow | Best for |
|---|---|---|
| **.NET (C#/F#)** | In-process, no protocol; implement `IPlugin`/`IAsyncPlugin` | Lowest latency, rich settings UI, in-process API |
| **Python** | Out-of-process JSON-RPC over stdio | Fastest to build small utilities |
| **JS/TS** | Out-of-process JSON-RPC | JS shops |
| **`executable`** | Generic out-of-process JSON-RPC | Any other language |

### 2.4 Recommended language: **Python** (primary recommendation) — with a strong C# alternative

**Recommend Python** for AudioCowboy:

1. **Audio control is trivially native in Python.** `pycaw` lists render+capture devices, reads current defaults, *and* sets defaults (`AudioUtilities.SetDefaultDevice`) — wrapping the undocumented COM for you. No bundled EXE, no subprocess parsing required for the happy path.
2. **Dev speed.** No compiler/SDK; the official `HelloWorldPython` sample is a complete scaffold.
3. **The tool is I/O-light** — per-query latency of an out-of-process plugin is acceptable for "type keyword → pick device."

**When to reconsider C#:** if you want the *lowest* latency, a native settings UI (`ISettingProvider`), or to reuse the proven `AudioSwitcher.AudioApi.CoreAudio` NuGet library that both existing Flow audio plugins use (it auto-selects the right `IPolicyConfig` variant per Windows build — a maintenance win on the single riskiest dependency). **This is the main open language decision (see §8).** The rest of this report assumes Python but flags C# deltas where they matter.

---

## 3. Interaction Model & Approximating the rofi Multi-Layer Menu

### 3.1 The core facts (verified)

Flow Launcher has **no native nested-menu primitive** — `query` returns a flat `List<Result>`. But you can fake drill-down (verdict #1, *confirmed*):

- **`Flow.Launcher.ChangeQuery(query, requery)`** rewrites the search-box text. Pass `requery: true` so the new prefix re-fires even if Flow thinks the text is unchanged. ([ChangeQuery.md](https://github.com/Flow-Launcher/docs/blob/main/API-Reference/Flow.Launcher.Plugin/IPublicAPI/ChangeQuery.md))
- **Keep the window open** by *not* hiding Flow after the action. In C#, `Result.Action` returns `false`. In JSON-RPC/Python plugins, the result carries `"DontHideAfterAction": true`. `ChangeQuery` rewrites & re-shows; the "don't hide" flag prevents the close — *they work together*.
- **Context menus (Shift+Enter / right-click)** give exactly **one** secondary level: Python `context_menu(self, data)` receives the selected result's `ContextData`. ([develop-dotnet-plugins.md](https://github.com/Flow-Launcher/docs/blob/main/develop-dotnet-plugins.md))

### 3.2 The Python wire contract (corrected per verdict #3)

- Flow runs the plugin as a process and exchanges JSON-RPC. **Results must be wrapped in a top-level `result` array** — `{"result": [ {...}, {...} ]}` — not a bare object.
- A result item: `{"Title", "SubTitle", "IcoPath", "Score", "ContextData": [...], "JsonRPCAction": {"method": "<handler>", "parameters": [...]}}`. `JsonRPCAction.method` **must name a real method** on your plugin class — a typo silently does nothing.
- Plugins call back into Flow with `{"method": "Flow.Launcher.ChangeQuery", "parameters": ["new query", true]}`. Methods starting with `Flow.Launcher.` dispatch to the built-in API, not your class.
- **Settings arrive only in query params, not at init** (open issue #3090). Don't expect config before the first query.

### 3.3 Recommended UX: four keywords (matches the user's request directly)

This is the cleanest mapping of the user's stated UX and the primary recommendation:

| Keyword | Behavior |
|---|---|
| `aco` | List all **output** (render) devices → Enter sets default output (all 3 roles). Active device highlighted in `SubTitle`. |
| `aci` | List all **input** (capture) devices → Enter sets default input. |
| `acs <name>` | Save current {default input, default output} as a named profile. |
| `acp` | List saved profiles → Enter **loads/applies**. Context menu (Shift+Enter) offers **Load / Delete**. |

Register `ac` as the manifest `ActionKeyword`; add `aci`/`aco`/`acs`/`acp` at runtime via `AddActionKeyword`, **or** simply ship `ac` as the single keyword and parse the next token as the sub-command (`ac out`, `ac in`, `ac save X`, `ac profile`). Parsing one keyword into sub-commands is the lowest-friction approach and avoids multi-keyword registration entirely.

**Context-menu enrichment** (one level, the rofi "secondary action" feel):
- On an output/input device: *Set as Communication device only*, *Set for all roles*.
- On a profile: *Load*, *Delete*, *Overwrite with current devices*.

### 3.4 Optional: single-keyword multi-layer menu (`ac` → In/Out/Profile → …)

This replicates the original rofi *top-level menu* most faithfully, using `ChangeQuery` drill-down. Top level:

```
ac            →  [In]  [Out]  [Profile]
ac out        →  list of output devices
ac in         →  list of input devices
ac profile    →  [Load] [Save] [Delete]
ac profile load    →  list of profiles → apply
```

Selecting "Out" doesn't act — it **rewrites the query to `ac out `** and re-queries, showing the next layer. This is the drill-down pattern.

### 3.5 Concrete drill-down code (Python, official `flowlauncher` lib)

```python
# main.py  (entry; sys.path bootstrap omitted here — see §6.4)
from flowlauncher import FlowLauncher

class AudioCowboy(FlowLauncher):

    def query(self, query):
        parts = (query or "").strip().split()
        sub = parts[0].lower() if parts else ""
        rest = " ".join(parts[1:])

        if sub == "":
            # TOP-LEVEL MENU — each result drills down via ChangeQuery
            return {"result": [
                self._drill("Output devices", "Pick the default playback device", "ac out "),
                self._drill("Input devices",  "Pick the default recording device", "ac in "),
                self._drill("Profiles",        "Load / Save / Delete profiles",     "ac profile "),
            ]}

        if sub == "out":
            return {"result": self._device_results("render", rest)}
        if sub == "in":
            return {"result": self._device_results("capture", rest)}
        if sub == "profile":
            return {"result": self._profile_menu(rest)}

        return {"result": []}

    # A result that REWRITES the search box and keeps Flow open (drill-down).
    def _drill(self, title, sub, new_query):
        return {
            "Title": title,
            "SubTitle": sub,
            "IcoPath": "Images/app.png",
            "DontHideAfterAction": True,                 # keep window open
            "JsonRPCAction": {
                "method": "Flow.Launcher.ChangeQuery",   # built-in API
                "parameters": [new_query, True],         # requery=True so it re-fires
            },
        }

    # A result that performs the actual switch and closes Flow.
    def _device_result(self, friendly, endpoint_id, kind):
        return {
            "Title": friendly,
            "SubTitle": f"Set as default {kind} device (all roles)",
            "IcoPath": "Images/app.png",
            "ContextData": [kind, endpoint_id, friendly],  # feeds context_menu()
            "JsonRPCAction": {
                "method": "set_default",                   # real method on this class
                "parameters": [endpoint_id, "all"],
            },
        }

    def set_default(self, endpoint_id, role):
        # see §4 for the pycaw implementation
        ...

if __name__ == "__main__":
    AudioCowboy()
```

> The `flowlauncher` base class dispatches `JsonRPCAction.method` to the named method (e.g. `set_default`) or, for `Flow.Launcher.*`, back to Flow. `context_menu(self, data)` receives the result's `ContextData` list for the one-level secondary menu.

---

## 4. Audio Device Control Mechanism

### 4.1 The fundamental constraint (verified, verdict #2)

> Windows exposes a **documented** Core Audio API (`IMMDeviceEnumerator`) to **enumerate and READ** the default endpoint, but **no public API to CHANGE it**. Setting the default relies on the **undocumented `IPolicyConfig` COM interface** (`SetDefaultEndpoint(deviceId, eRole)`). Every tool — `pycaw`, `svcl`, `AudioDeviceCmdlets`, SoundSwitch, EarTrumpet — is a wrapper around this same interface. ([endpoint enumeration docs](https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nf-mmdeviceapi-immdeviceenumerator-enumaudioendpoints))

Switching the default **does not require admin rights** (it operates on the current user's session). *(Note: installing the `AudioDeviceCmdlets` module machine-wide does need elevation; `-Scope CurrentUser` or bundling the DLL avoids that.)*

### 4.2 Recommendation matrix

| Mechanism | Lists? | Sets render+capture? | Admin-free? | Bundling | Verdict |
|---|---|---|---|---|---|
| **`pycaw`** (pip, comtypes) | ✅ both | ✅ via `SetDefaultDevice` | ✅ | pip / vendored `lib/` | **PRIMARY** — native Python, no EXE |
| **NirSoft `svcl.exe`** | ✅ both (CSV/stdout) | ✅, incl. `all` role in one call | ✅ | single bundled EXE | **FALLBACK** — most battle-tested |
| **`AudioDeviceCmdlets`** (PS module DLL) | ✅ both | ✅, `-DefaultOnly`/`-CommunicationOnly` | ✅ (bundled DLL) | DLL + `Import-Module` | Alternative; needs `Unblock-File` (MOTW) |
| **NirCmd** | ❌ no enumeration | render-only, name-based | ✅ | EXE | **AVOID** — documented Vista/7 only, unreliable on Win10/11 (verdict #2) |

### 4.3 Chosen mechanism: `pycaw` primary, `svcl.exe` fallback

**Primary — `pycaw` (pure Python):**

```python
from pycaw.pycaw import AudioUtilities
from pycaw.constants import EDataFlow, DEVICE_STATE

# LIST output (render) devices for the user-facing list
def list_outputs():
    return AudioUtilities.GetAllDevices(
        data_flow=EDataFlow.eRender.value,
        device_state=DEVICE_STATE.ACTIVE.value,
    )  # each d -> d.id (stable endpoint ID), d.FriendlyName

# LIST input (capture) devices
def list_inputs():
    return AudioUtilities.GetAllDevices(
        data_flow=EDataFlow.eCapture.value,
        device_state=DEVICE_STATE.ACTIVE.value,
    )

# CURRENT defaults (persist d.id, not the name)
spk = AudioUtilities.GetSpeakers()     # default render
mic = AudioUtilities.GetMicrophone()   # default capture

# SET default for ALL roles (Console + Multimedia + Communications)
def set_default(endpoint_id, role="all"):
    AudioUtilities.SetDefaultDevice(endpoint_id)  # roles=None => all roles
    # internally calls IPolicyConfig.SetDefaultEndpoint(devId, role)
```

> **Always set all three roles.** Setting only one is the classic bug — communication apps (Teams/Discord/Zoom) keep the old device. `pycaw`'s `SetDefaultDevice(... roles=None)` covers all roles; expose a *separate* "Communication only" action in the context menu for power users.

> When **re-resolving a saved profile ID** that might be temporarily disconnected, enumerate with `DEVICE_STATE.MASK_ALL` rather than `ACTIVE`, so a disabled-but-present endpoint still matches.

**Fallback — bundled `svcl.exe`** (invoke by **absolute path**, since Flow's CWD is not guaranteed to be the plugin folder):

```python
import os, subprocess
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
SVCL = os.path.join(PLUGIN_DIR, "bin", "svcl.exe")

def svcl_set_default(device_id, role="all"):
    # device_id = svcl "Command-Line Friendly ID" or "Item ID"
    subprocess.run([SVCL, "/SetDefault", device_id, role], check=True)

def svcl_list_csv(path):
    subprocess.run([SVCL, "/scomma", path, "/Columns",
                    "Name,Type,Direction,Default,Command-Line Friendly ID,Item ID"],
                   check=True)
```

Gate the `svcl` path behind a `try/except` around the `pycaw` path so a future `pycaw`/Windows incompatibility doesn't brick the plugin.

> Note: NirSoft EXEs are closed-source freeware and **frequently trigger antivirus false positives**; bundling is fine for personal/internal use but adds friction for public store redistribution. This reinforces `pycaw` (permissive license) as primary.

### 4.4 Stable device-id strategy (critical for profiles)

Persist the **MMDevice endpoint ID string** — `pycaw` exposes it as `device.id` — **never** the friendly name. Microsoft documents it as a persistent, reboot-stable, globally-unique identifier; identical hardware (two of the same USB headset) yields **identical friendly names** but **distinct** endpoint IDs. ([endpoint-id-strings](https://learn.microsoft.com/en-us/windows/win32/coreaudio/endpoint-id-strings))

- Format: `{0.0.0.00000000}.{guid}` for render, `{0.0.1.00000000}.{guid}` for capture.
- Store friendly name **only** as a display label / fallback hint.
- On apply: re-resolve by endpoint ID; if absent (unplugged), show "device disconnected" rather than silently failing.
- Edge case: Windows may change the *system default* when a higher-ranking endpoint appears — so always set the saved device **explicitly by ID**, never rely on prior default state.

---

## 5. Profiles

### 5.1 Storage location (update-safe — critical)

The plugin's **install folder is wiped/replaced on every update**, so profiles must **not** live there. Flow stores per-plugin settings *outside* the install dir, under the roaming data root:

```
%APPDATA%\FlowLauncher\Settings\Plugins\<PluginName>\
```

This survives updates and reinstalls. Write `profiles.json` here, beside Flow's auto-managed `Settings.json`. ([settings-management](https://deepwiki.com/Flow-Launcher/Flow.Launcher/2.4-settings-management))

```python
import os

PLUGIN_NAME = "AudioCowboy"  # must match plugin.json "Name"

def profiles_path(plugin_dir: str) -> str:
    appdata = os.getenv("APPDATA")
    if appdata and os.path.isdir(os.path.join(appdata, "FlowLauncher")):
        cand = os.path.join(appdata, "FlowLauncher", "Settings", "Plugins", PLUGIN_NAME)
        os.makedirs(cand, exist_ok=True)
        return os.path.join(cand, "profiles.json")
    # Portable fallback: plugin_dir is .../UserData/Plugins/<Name>-<ver>
    user_data = os.path.dirname(os.path.dirname(plugin_dir))
    cand = os.path.join(user_data, "Settings", "Plugins", PLUGIN_NAME)
    os.makedirs(cand, exist_ok=True)
    return os.path.join(cand, "profiles.json")
```

> Write atomically (temp file → `os.replace`) — the same pattern Flow uses — to avoid corruption if the process is killed mid-write.

### 5.2 Recommended `profiles.json` schema

A SoundSwitch-style profile bundles input + output. Versioned for future migration. Each device = `{endpointId, friendlyName}`.

```json
{
  "schemaVersion": 1,
  "activeProfile": "Gaming",
  "profiles": [
    {
      "name": "Gaming",
      "created": "2026-06-17T10:32:00Z",
      "output": {
        "endpointId": "{0.0.0.00000000}.{e6327cad-dcec-4949-ab8a-1f1f3c1b2d4e}",
        "friendlyName": "Speakers (Realtek High Definition Audio)"
      },
      "input": {
        "endpointId": "{0.0.1.00000000}.{b1c2d3e4-5678-90ab-cdef-1234567890ab}",
        "friendlyName": "Microphone (HyperX QuadCast)"
      }
    }
  ]
}
```

> **Optional extension** (SoundSwitch parity): add `commsOutput`/`commsInput` fields if you later let users pin a separate Communications device per profile.

### 5.3 Save / List / Load / Delete flow

Drive **all CRUD through query results + JsonRPCAction callbacks** — *not* the settings panel (`SettingsTemplate.yaml` cannot model an unbounded named list). Python plugins have **no API to write back into Flow's `Settings.json`**, which is exactly why the profiles file is plugin-owned. ([issue #3291](https://github.com/Flow-Launcher/Flow.Launcher/issues/3291))

| Action | Query | Behavior |
|---|---|---|
| **Save** | `acs Gaming` | Read current defaults (`GetSpeakers`/`GetMicrophone`), capture both `endpointId`+`friendlyName`, append/overwrite in `profiles.json`. |
| **List** | `acp` | Read `profiles.json`, render one result per profile; `SubTitle` shows the two device names + a ⚠ if either is currently absent. |
| **Load** | Enter on a profile (or `acp` + Shift+Enter → *Load*) | Re-resolve both IDs, `SetDefaultDevice` for each (all roles); notify via `Flow.Launcher.ShowMsg`. Skip + warn if a device is missing. |
| **Delete** | Shift+Enter → *Delete* | Remove from `profiles.json`, atomic write. |

A flat `SettingsTemplate.yaml` is still worth shipping for *scalar* options only (e.g. "apply input+output together" toggle, "match strategy" dropdown) — Flow renders/persists it for free.

---

## 6. Recommended Architecture

### 6.1 Components

```
┌──────────────────────────────────────────────────────────┐
│ Flow Launcher (host)                                       │
│   user types: ac / aci / aco / acs / acp                   │
└───────────────┬────────────────────────────────────────────┘
                │ JSON-RPC over stdio  (query / context_menu / action)
                ▼
┌──────────────────────────────────────────────────────────┐
│ main.py  (AudioCowboy(FlowLauncher))                       │
│   • router: parse sub-command, build {"result":[...]}      │
│   • drill-down via Flow.Launcher.ChangeQuery               │
└───────┬───────────────────────────┬───────────────────────┘
        ▼                           ▼
┌────────────────┐         ┌──────────────────────────────┐
│ audio.py       │         │ profiles.py                  │
│  list/get/set  │         │  load/save/delete profiles   │
│  via pycaw     │         │  atomic JSON in              │
│  (svcl fallback)│        │  …\Settings\Plugins\<Name>\  │
└───────┬────────┘         └──────────────────────────────┘
        ▼ (fallback only)
┌────────────────┐
│ bin/svcl.exe   │  (optional bundled NirSoft CLI)
└────────────────┘
```

### 6.2 Data flow (apply a profile)

1. `acp` → `profiles.py` reads `profiles.json` → router renders results.
2. User Enter → `JsonRPCAction.method = "load_profile"`, param = profile name.
3. `load_profile` → for output+input: `audio.py` re-resolves `endpointId` (MASK_ALL), calls `pycaw SetDefaultDevice` (all roles). On `pycaw` exception → `svcl.exe /SetDefault <id> all`.
4. `Flow.Launcher.ShowMsg` confirms; missing devices reported, not thrown.

### 6.3 Dependency / bundling plan

- **Ship in `lib/`** (vendored, since Flow does **not** install `requirements.txt` and most users run Flow's *isolated embedded Python*): `pycaw`, `comtypes`, `flowlauncher`. Build with `pip install -r requirements.txt -t ./lib` in a GitHub Action.
- **`comtypes` caveat:** it contains compiled/native code sensitive to the embedded Python version — build against the version Flow ships and test on a clean machine. This is the main reason to keep the `svcl.exe` fallback.
- **Optional `bin/svcl.exe`** for the fallback path (accept the AV-false-positive tradeoff, or omit for the public store and document a manual fallback).

### 6.4 File / folder layout

```
Flow.Launcher.Plugin.AudioCowboy/
├─ plugin.json                 # manifest (§2.2)
├─ main.py                     # entry: sys.path bootstrap + router
├─ audio.py                    # pycaw list/get/set + svcl fallback
├─ profiles.py                 # profiles.json CRUD (atomic)
├─ requirements.txt            # pycaw, comtypes, flowlauncher
├─ SettingsTemplate.yaml       # OPTIONAL flat scalar options only
├─ Images/
│   └─ app.png
├─ bin/
│   └─ svcl.exe                # OPTIONAL fallback CLI
├─ lib/                        # VENDORED deps (built in CI, zipped into release)
└─ .github/workflows/
    └─ Publish Release.yml     # pip -t lib, zip incl. lib/, attach to Release
```

`main.py` must bootstrap `sys.path` so vendored deps import under Flow's embedded Python, and resolve paths from `__file__` (CWD is not guaranteed — issue #2299):

```python
import sys
from pathlib import Path
plugindir = Path(__file__).parent.absolute()
sys.path = [str(plugindir / p) for p in (".", "lib", "plugin")] + sys.path
```

---

## 7. Prior Art to Reference

| Repo / source | What it is | What to borrow |
|---|---|---|
| **[Flow HelloWorldPython](https://github.com/Flow-Launcher/Flow.Launcher.Plugin.HelloWorldPython)** | Official Python sample | `plugin.json` + `main.py` shape, `sys.path` bootstrap, the GitHub release workflow |
| **[Flow PythonTemplate](https://github.com/Flow-Launcher/Flow.Launcher.Plugin.PythonTemplate)** | Official template | Project structure, `requirements.txt` convention |
| **[attilakapostyak/AudioDeviceSelector](https://github.com/attilakapostyak/Flow.Launcher.Plugin.AudioDeviceSelector)** | The Flow store audio plugin (C#, keyword `ad`) | Reference UX for the device list; note it's **output-only, flat, no profiles** — the gap you're filling. v1.0.3 (2023), treat as reference not upstream. |
| **[yhdsl/AudioDeviceSelector](https://github.com/yhdsl/Flow.Launcher.Plugin.AudioDeviceSelector)** | Variant (archived Apr 2025, read-only) | Same; confirms output-only flat-list pattern |
| **[Belphemur/SoundSwitch](https://github.com/Belphemur/SoundSwitch)** | Gold-standard standalone switcher (C#) | **Profile model** (playback+recording+comms bundle); the **set-all-three-roles** pattern ([AudioSwitcher.cs](https://github.com/Belphemur/SoundSwitch/blob/dev/SoundSwitch.Audio.Manager/AudioSwitcher.cs)); "Force profile" re-apply idea; foreground-app routing (roadmap) |
| **[AndreMiras/pycaw](https://github.com/AndreMiras/pycaw)** | The Python audio lib | Primary backend — `GetAllDevices`, `GetSpeakers`/`GetMicrophone`, `SetDefaultDevice` |
| **[NirSoft svcl](https://www.nirsoft.net/articles/set_default_audio_device_command_line.html)** | CLI switcher | Fallback `/SetDefault … all`, `/scomma` listing, Command-Line Friendly ID |
| **[xenolightning/AudioSwitcher.AudioApi.CoreAudio](https://github.com/xenolightning/AudioSwitcher)** | NuGet lib (for the C# alternative) | If you go C#: it abstracts per-Windows `IPolicyConfig` variants behind `.SetAsDefault()` — verify it works on current Win11 (last stable 3.0.3) |
| **[frgnca/AudioDeviceCmdlets](https://github.com/frgnca/AudioDeviceCmdlets)** | PS module | Alternative shell-out fallback; `-DefaultOnly`/`-CommunicationOnly` role separation |
| **[CIAvash rofi gist](https://gist.github.com/CIAvash/c78612b7015180c9ed071381e0a2318d)** | The Linux rofi UX origin | Confirms "pre-highlight active device" UX nicety to replicate in `SubTitle` |

---

## 8. Open Questions / Decisions for the User

1. **Language: Python vs C#?** Python is recommended (native audio via `pycaw`, fastest to build). C# buys lowest latency, a native settings UI, and the proven `AudioSwitcher.AudioApi.CoreAudio` library (offloads the riskiest dependency). **Decision needed before scaffolding.**
2. **UX shape:** four discrete keywords (`aci`/`aco`/`acs`/`acp`, matches your stated request) **or** the single-keyword multi-layer `ac → In/Out/Profile` rofi-style menu — or both (single keyword that also accepts the four as sub-commands)? My default recommendation: single `ac` keyword parsed into sub-commands, since it sidesteps multi-keyword registration and still supports drill-down.
3. **Communications role:** always set all three roles (recommended default), and additionally expose a "set Communication device only" context action? Confirm whether you want per-profile separate comms devices (SoundSwitch parity) or keep profiles simple (just default input+output).
4. **Bundle `svcl.exe` fallback?** Improves robustness against a future `pycaw`/Windows break, but it's closed-source freeware that **triggers AV false positives** and complicates public-store redistribution. Bundle for personal use; reconsider for the store.
5. **Distribution target:** personal/manual install only (zip → extract → restart, or `pm install <url>`; no auto-update), or full **store listing** (PR to `Flow.Launcher.PluginsManifest` + CI release workflow; auto-updates on Version bump)? This affects whether the AV-flagged EXE bundle is acceptable.
6. **"Force profile" feature?** SoundSwitch re-applies a profile whenever Windows changes the default externally. Powerful but requires an `IMMNotificationClient`-style watcher — likely out of scope for v1; flag as a roadmap item.

---

## 9. Suggested Implementation Roadmap

**Phase 0 — Decisions & scaffold (½ day)**
Lock §8 decisions. Generate a fresh 32-hex UUID (`uuid.uuid4().hex`). Clone `HelloWorldPython`/`PythonTemplate`, set `plugin.json`, get an empty `query` returning `{"result":[...]}` loading in Flow.

**Phase 1 — List + switch (core, 1–2 days)**
`audio.py` with `pycaw`: list render/capture, read current defaults, `SetDefaultDevice` (all roles). Wire `aco`/`aci` (or `ac out`/`ac in`). Highlight the currently-active device in `SubTitle`. Verify a standard (non-admin) user can switch.

**Phase 2 — Profiles (1–2 days)**
`profiles.py` with the §5.2 schema, atomic writes to the §5.1 update-safe path. Implement `acs <name>` (save), `acp` (list), load on Enter, delete via context menu. Handle missing-device-on-apply gracefully.

**Phase 3 — UX polish & multi-layer menu (1 day)**
Add the optional `ac → In/Out/Profile` drill-down via `ChangeQuery(... requery=True)` + `DontHideAfterAction`. Context-menu secondary actions (comms-only, overwrite). `Flow.Launcher.ShowMsg` confirmations. Optional flat `SettingsTemplate.yaml`.

**Phase 4 — Robustness (½–1 day)**
Wrap all SET ops in try/except with logging (check `%APPDATA%\FlowLauncher\Logs`). Add the `svcl.exe` fallback behind the `pycaw` path. Test device unplug/replug and two-identical-devices cases.

**Phase 5 — Packaging & release (½–1 day)**
`requirements.txt` + GitHub Action that `pip install -t ./lib`, zips incl. `lib/` (and `bin/` if bundling), attaches to a Release tagged to `plugin.json` Version. Test a clean-machine install under Flow's embedded Python.

**Phase 6 — Store submission (optional)**
PR to `Flow.Launcher.PluginsManifest`; thereafter Version bumps auto-publish. Allow several days for CDN propagation.

---

### Appendix — Top gotchas checklist
- ☐ Wrap results in `{"result": [...]}`, not a bare object.
- ☐ Set **all three** ERoles on every switch.
- ☐ Persist **endpoint ID**, never friendly name.
- ☐ Never write profiles into the install folder.
- ☐ Resolve paths from `__file__`, not CWD.
- ☐ `JsonRPCAction.method` must name a real class method.
- ☐ Vendor deps into `lib/` (Flow won't pip-install).
- ☐ Use `requery=True` + `DontHideAfterAction` for drill-down.
- ☐ Avoid NirCmd (unreliable on Win10/11); prefer `pycaw`/`svcl`.
- ☐ `Language: "python"` — never `python_v2`.
