# JobTracker desktop distribution

JobTracker is a desktop application with its own window, icon, menu, bundled Python runtime, and local SQLite database. Python, Node.js, and a browser are not prerequisites for recipients. Ollama remains optional and is installed separately. Models are never bundled or downloaded automatically.

## Recipient packages
Installers are published as assets on GitHub Releases (`gh release view --web`), each with a `JobTracker-<version>-SHA256.txt` checksum file. They are not committed to Git.
- Windows x64: `JobTracker-Setup-<version>-x64.exe`. Per-user installer with Start menu and desktop shortcuts. Uninstalling leaves user data intact. SmartScreen shows "Windows protected your PC" for unsigned builds: choose More info → Run anyway.
- Linux x64: `JobTracker-<version>-amd64.deb` for Debian/Ubuntu: `sudo apt install ./JobTracker-<version>-amd64.deb`.
- Apple Silicon Mac: `JobTracker-<version>-arm64.dmg` (drag to Applications) or the equivalent `-arm64-mac.zip`. Without a Developer ID signature and notarization, macOS blocks the first launch: open System Settings → Privacy & Security → Open Anyway.

No automatic updates are enabled. To upgrade, recipients install the newer release over the existing one.

## Data and privacy
The desktop app uses its OS user profile directory, under `JobTracker/data` (the exact path is available in Profile & data and File → Open data folder). Application updates do not write over that directory. Each friend starts with an empty database. The packaging allowlist excludes your applications, résumé, logs, backups, tests, work files, and source-control metadata.

To migrate from the earlier local web version, export its full JSON backup, then restore it from Profile & data in the desktop app. Keep the original backup until you verify the import. SQLite snapshots retain complete state; JSON exports omit cached AI reports, which can be regenerated.

The bundled local server listens on a random loopback port and requires a per-launch secret for all desktop requests. Renderer Node.js access is off; context isolation and renderer sandboxing are on. External HTTPS links open in the default browser. App UI scripts, map code and icons are bundled; internet access is still required for job-page retrieval, map tiles, geocoding, and model downloads.

## Recommended local model
Start with `ollama pull qwen3.5:9b` on a machine with comfortable memory headroom. This is a practical starting recommendation, not a benchmark result for this application. The Ollama tag currently has roughly 6.6–7.6 GB variants; inference needs additional memory. Try `qwen3.5:4b` on smaller machines. The app's Local AI panel links to model details and discovers installed models.

References: https://ollama.com/library/qwen3.5:9b and https://ollama.com/library/qwen3.5:4b.

## Reproducible builds
Requires Node.js 24 and npm. The Python runtime archives are pinned by HTTPS source URL and SHA-256 in `scripts/runtimes.json`. They come from Astral's python-build-standalone release 20261026. Their upstream licenses are retained inside the bundled runtime. Electron and Leaflet licenses are included in their distributed files.

```
npm ci
npm test
python3 -B -m unittest discover -s tests -v
npm run dist:win
npm run dist:linux
npm run dist:mac
```

Run the corresponding command on its target OS for the most reliable builds. `.github/workflows/desktop-build.yml` builds the three platforms on native GitHub-hosted runners and uploads the installer artifacts. It runs on manual dispatch or a version tag; it does not publish releases. No account, repository, or remote workflow has been created automatically.

Do not build multiple targets simultaneously in the same checkout: `build/runtime` holds the current target's verified runtime. The package script replaces that directory when switching targets. The local `work/` directory contains caches and is not shipped.

Signing can be configured later using electron-builder's certificate/environment settings. This repository intentionally contains no signing credentials.

## Releasing from an Apple Silicon Mac
`npm run dist:win` fails on Apple Silicon because electron-builder's bundled `makensis` is an Intel binary. Build the Windows app folder with electron-builder and then run a native `makensis` against `scripts/installer.nsi`. The Linux `.deb` is assembled by `scripts/deb.py`. Both take the version from `package.json`:

```
npm run dist:mac
npm run smoke
node scripts/runtime.mjs win-x64
node node_modules/electron-builder/out/cli/cli.js --win dir --x64 --publish never
makensis -DVERSION=<version> scripts/installer.nsi
node scripts/runtime.mjs linux-x64
node node_modules/electron-builder/out/cli/cli.js --linux dir --x64 --publish never
python3 scripts/deb.py
gh release create v<version> release/JobTracker-<version>-arm64.dmg release/JobTracker-<version>-arm64-mac.zip release/JobTracker-Setup-<version>-x64.exe release/JobTracker-<version>-amd64.deb release/JobTracker-<version>-SHA256.txt
```

`npm run smoke` launches the packaged app for the current OS in smoke mode (throwaway profile, no dialogs) and fails unless the backend starts and the interface renders. The GitHub workflow runs it on native Windows, Linux and macOS runners after each build.

## Mac signing and notarization
Gatekeeper warnings go away only with a **Developer ID Application** certificate and Apple notarization. An "Apple Development" certificate is only for running builds on your own registered devices, and cannot be used for either. To set up:
1. In Xcode → Settings → Accounts → Manage Certificates, add a Developer ID Application certificate (this requires the account's Account Holder role).
2. Create an app-specific password at account.apple.com, then store it for notarytool: `xcrun notarytool store-credentials jobtracker-notary --apple-id <apple id> --team-id <team id>`.
3. Set `"identity"` in the `mac` build config to the Developer ID name, enable `hardenedRuntime` with entitlements that permit the bundled Python runtime, and configure notarization.
