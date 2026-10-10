#!/usr/bin/env bash
# Builds dist/Vivid-x86_64.AppImage. Needs: python3 with PySide6 and pyinstaller, appimagetool in PATH.
set -euo pipefail
cd "$(dirname "$0")/.."

pyinstaller --noconfirm --clean --windowed --name vivid \
    --add-data vivid/assets:vivid/assets \
    vivid.py

APPDIR=build/AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR"
cp -r dist/vivid/. "$APPDIR/"
cp packaging/vivid.desktop "$APPDIR/vivid.desktop"
cp vivid/assets/vivid.svg "$APPDIR/vivid.svg"
cp vivid/assets/vivid.svg "$APPDIR/.DirIcon"
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/vivid" "$@"
RUN
chmod +x "$APPDIR/AppRun"

ARCH=x86_64 appimagetool --no-appstream "$APPDIR" dist/Vivid-x86_64.AppImage
