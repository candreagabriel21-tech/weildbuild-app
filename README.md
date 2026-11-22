# WeildBuild mobile channel

This repository is the mobile distribution channel for WeildBuild.
The WeildBuild launcher downloads and verifies everything below; the
payload blobs are encrypted at rest (format WBENC1) and only the local
launcher can decrypt them in memory while the app is running.

## Layout

| Path | Role |
| --- | --- |
| `wb_version.json` | the live version marker (`version = "1.0.0"`) that the launcher and updater poll |
| `wb-version.json` | identical copy under the name the in-app updater fetches |
| `manifest.json` | every deliverable with its SHA-256 and size (format `wb-manifest-1`) |
| `payload/` | the encrypted application files, one `.wbenc` blob per file |
| `weildbuild_installer.py` / `weildbuild_launcher.py` / `weildbuild_updater.py` | the tool scripts (plain Python, stdlib only) |
| `pardon.txt` | local-only paths the updater must never delete (sessions, cache, browser profile) |
| `releases/WeildBuild-1.0.0.apk` | the plain Android APK for direct sideloading |

## Releasing a new version

1. Bump `--version` and re-run the publisher against the new app build:
   `python weildbuild_publisher.py --app-dir <build> --version <x.y.z> --out-dir <this repo checkout>`
2. Commit + push. Users get the update within one minute (background updater).
