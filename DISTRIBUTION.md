# JobTracker desktop distribution

JobTracker is a desktop application with its own window, icon, menu, bundled Python runtime, and local SQLite database. Python, Node.js, and a browser are not prerequisites for recipients. Ollama remains optional and is installed separately. Models are never bundled or downloaded automatically.

## Recipient packages
- Windows x64: `JobTracker-Setup-1.0.0-x64.exe`. Per-user installer with Start menu and optional desktop shortcut. Uninstall leaves user data intact.
- Linux x64: `.AppImage` portable desktop app and `.deb` installer for Debian/Ubuntu. AppImage use depends on the distribution's FUSE/user-namespace support. Do not disable Chromium sandboxing to work around host restrictions; use the Debian package where applicable.
- Apple Silicon Mac: `JobTracker-1.0.0-arm64-mac.zip`. Unzip and move JobTracker.app to Applications. A DMG target is also available to native build hosts.

These initial builds do not carry a publisher signing certificate or Apple notarization. The Mac app uses a local ad-hoc signature for executable integrity. Windows may display an unknown-publisher warning; wider public distribution should use trusted publisher signing. No automatic updates are enabled.

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

## Build verification for this delivery
Windows NSIS installer and Linux Debian package were built on Apple Silicon using native packaging tools. Their payloads have not been executed on Windows or Linux. The Mac bundle signature and bundled backend were verified; native GUI inspection was unavailable. AppImage and DMG generation were blocked by host tooling; those formats are not included in this delivery. The GitHub workflow remains available for native builds.
