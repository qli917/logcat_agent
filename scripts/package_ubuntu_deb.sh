#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/dist/logagent-linux-with-models"
PACKAGE_ROOT="$ROOT_DIR/dist/deb/logagent"
OUTPUT_DIR="$ROOT_DIR/dist"

PACKAGE_NAME="logagent"
VERSION="${LOGAGENT_DEB_VERSION:-1.0.0}"
ARCH="${LOGAGENT_DEB_ARCH:-amd64}"
INSTALL_DIR="/opt/logagent"

if [[ ! -x "$APP_DIR/LogAgent" ]]; then
    echo "Missing release bundle: $APP_DIR/LogAgent" >&2
    echo "Build dist/logagent-linux-with-models before packaging." >&2
    exit 1
fi

if [[ ! -x "$APP_DIR/ffmpeg" || ! -x "$APP_DIR/ffprobe" ]]; then
    echo "Missing bundled FFmpeg binaries in $APP_DIR: ffmpeg and ffprobe are required." >&2
    exit 1
fi

rm -rf "$PACKAGE_ROOT"
mkdir -p \
    "$PACKAGE_ROOT/DEBIAN" \
    "$PACKAGE_ROOT$INSTALL_DIR" \
    "$PACKAGE_ROOT/usr/bin" \
    "$PACKAGE_ROOT/usr/share/applications" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/512x512/apps"

cp -a "$APP_DIR/." "$PACKAGE_ROOT$INSTALL_DIR/"
cp "$ROOT_DIR/web/icons/Icon-512.png" "$PACKAGE_ROOT/usr/share/icons/hicolor/512x512/apps/logagent.png"

cat > "$PACKAGE_ROOT/DEBIAN/control" <<EOF
Package: $PACKAGE_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: LogAgent <logagent@example.local>
Depends: libc6, libgtk-3-0, libstdc++6
Description: LogAgent desktop log and video analysis tool
 LogAgent bundles the Flutter desktop app, Python runtime, OCR model, and FunASR model.
EOF

cat > "$PACKAGE_ROOT/usr/bin/logagent" <<'EOF'
#!/usr/bin/env bash
mkdir -p "${XDG_DATA_HOME:-$HOME/.local/share}/logagent"
cd "${XDG_DATA_HOME:-$HOME/.local/share}/logagent"
exec /opt/logagent/LogAgent "$@"
EOF
chmod 0755 "$PACKAGE_ROOT/usr/bin/logagent"

cat > "$PACKAGE_ROOT/usr/share/applications/logagent.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=LogAgent
Comment=Log and video analysis tool
Exec=/usr/bin/logagent
Icon=logagent
Terminal=false
Categories=Development;Utility;
StartupWMClass=LogAgent
EOF

find "$PACKAGE_ROOT" -type d -exec chmod 0755 {} +
fakeroot dpkg-deb --build "$PACKAGE_ROOT" "$OUTPUT_DIR/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"

echo "$OUTPUT_DIR/${PACKAGE_NAME}_${VERSION}_${ARCH}.deb"
