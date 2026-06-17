# Publishing AudioCowboy to the Flow Launcher plugin store

One **manual PR** for the first listing, then **automatic updates** forever.

> The repo is **`True347/AudioCowboy`** and the URLs below already point at it. The release
> **zip asset** keeps the conventional name `Flow.Launcher.Plugin.AudioCowboy.zip` (an asset
> filename, independent of the repo name). If you ever rename the repo, update the URLs in
> `plugin.json` `Website` and `publish/AudioCowboy-*.json` to match.

## 0. Prerequisites
- A GitHub account.
- `git` (installed) and optionally `gh` (`gh auth login` to use the CLI shortcuts).
- The store build uses the **pycaw** backend — no `svcl.exe` is shipped. `bin/svcl.exe`
  and `lib/` are git-ignored; CI rebuilds `lib/` from `requirements.txt`.

## 1. Create the GitHub repo and push
```powershell
cd D:\REPO\FL-AudioCowboy
git init -b main
git add .
git commit -m "AudioCowboy v1.0.0"

# with gh:
gh repo create AudioCowboy --public --source . --remote origin --push
# …or manually: create the repo on github.com, then:
#   git remote add origin https://github.com/True347/AudioCowboy.git
#   git push -u origin main
```
Pushing to `main` triggers the **Publish Release** workflow (`.github/workflows/Publish Release.yml`).

## 2. Confirm the release
- Actions tab → "Publish Release" run is green.
- Releases → `v1.0.0` exists with **`Flow.Launcher.Plugin.AudioCowboy.zip`** attached.
- Open the zip and confirm `plugin.json` is at the **root** and a `lib/` folder
  (pycaw, comtypes, psutil) is present.

## 3. Smoke-test the real artifact on a clean profile (recommended)
In Flow: `pm install https://github.com/True347/AudioCowboy/releases/download/v1.0.0/Flow.Launcher.Plugin.AudioCowboy.zip`
Restart Flow, type `ac`, confirm switching works **without** svcl.exe present.

## 4. Submit the manifest PR (first time only)
1. Fork **https://github.com/Flow-Launcher/Flow.Launcher.PluginsManifest** and branch off
   its default branch (`main`).
2. Add the file **`plugins/AudioCowboy-54dcf7b098df441ab7c2ad6b11c047cc.json`** — copy
   it from `publish/AudioCowboy-54dcf7b098df441ab7c2ad6b11c047cc.json` in this repo.
   Verify every URL resolves (the release zip and the jsdelivr icon URL must be live).
3. Open a PR. CI validates it; the Flow Launcher team approves and merges.
4. After merge, store/CDN propagation to all users can take a few days to a week.
   Meanwhile anyone can install via the `pm install <release-url>` above.

## 5. Future updates (no more PRs)
1. Bump `Version` in `plugin.json` (e.g. `1.0.1`).
2. Commit + push to `main`.
3. The workflow cuts `vX.Y.Z`; the manifest auto-updater detects the higher version
   (~every 3 hours) and updates the store entry automatically.

## Checklist
- [ ] GitHub username / repo name correct in `plugin.json`, workflow, and `publish/*.json`
- [ ] Repo pushed; "Publish Release" workflow green
- [ ] Release `v1.0.0` has the zip with `plugin.json` at root + `lib/`
- [ ] Icon URL `https://cdn.jsdelivr.net/gh/True347/AudioCowboy@main/Images/app.png` loads
- [ ] Manifest PR opened against `Flow.Launcher.PluginsManifest`
