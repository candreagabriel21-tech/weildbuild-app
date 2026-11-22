# Push instructions — weildbuild-mobile (WeildBuild mobile v1.0.0)

This zip mirrors the repository root. The payload blobs are pre-encrypted
(WBENC1), so user machines never have to encrypt anything and the two
channels update independently.

```bash
git clone https://github.com/candreagabriel21-tech/weildbuild-mobile.git
cd weildbuild-mobile
unzip -o /path/to/weildbuild-mobile-repo-1.0.0.zip          # writes the repo root files
git add -A
git commit -m "WeildBuild mobile release 1.0.0"
git push origin main
```

## Verify after push

1. https://raw.githubusercontent.com/candreagabriel21-tech/weildbuild-mobile/main/wb_version.json
   -> version = "1.0.0"
2. https://raw.githubusercontent.com/candreagabriel21-tech/weildbuild-mobile/main/manifest.json
   -> JSON with 257 files
3. First user run (any machine with Python 3.9+):
   python weildbuild_installer.py
   (download it from https://raw.githubusercontent.com/candreagabriel21-tech/weildbuild-mobile/main/weildbuild_installer.py)
   The wizard installs to the chosen folder and creates the desktop shortcut.

## Notes

- The installer/launcher/updater .py files at the repo root are plain Python,
  stdlib only. Optional: build .exe wrappers with the kit's build-exe.bat and
  drop them next to the .py files; the installer prefers the .exe when present.
- jsDelivr only mirrors files up to 20 MiB; bigger blobs (the mobile APK) are
  served by raw.githubusercontent.com, which the tools try first anyway.
- Future releases: run weildbuild_publisher.py (in the launcher kit) against
  the new app build with --out-dir pointing at this repo checkout, commit, push.
