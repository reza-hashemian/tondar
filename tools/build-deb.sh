#!/bin/sh
# Builds build/tondar_<version>_all.deb plus the browser extensions.
set -eu
cd "$(dirname "$0")/.."
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' src/tondar/__init__.py)
CHROME_ID=beoabpicfajnboiblppakbnbmlhbkgpf
FIREFOX_ID=tondar@tondar.dm
APP_ID=io.github.tondar.Tondar
B=build
PKG=$B/pkg

rm -rf "$B"

# --- browser extensions ---------------------------------------------------------
python3 tools/build-extension.py "$B/extension"

# --- package tree -----------------------------------------------------------------
mkdir -p "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/share/tondar" "$PKG/usr/lib/tondar" \
         "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/scalable/apps" \
         "$PKG/usr/share/doc/tondar"

cp -r src/tondar "$PKG/usr/share/tondar/"
find "$PKG/usr/share/tondar" -name __pycache__ -prune -exec rm -rf {} +
cp -r "$B/extension" "$PKG/usr/share/tondar/extension"
install -m 755 native-host/tondar_native_host.py "$PKG/usr/lib/tondar/tondar-native-host"
install -m 644 "data/$APP_ID.desktop" "$PKG/usr/share/applications/"
install -m 644 "data/$APP_ID.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/"

cat > "$PKG/usr/bin/tondar" <<'SH'
#!/bin/sh
export PYTHONPATH="/usr/share/tondar${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m tondar "$@"
SH
chmod 755 "$PKG/usr/bin/tondar"

# Native messaging manifests (let the browser extension talk to the app)
chrome_manifest() {
    printf '{\n  "name": "com.tondar.host",\n  "description": "Tondar Download Manager",\n  "path": "/usr/lib/tondar/tondar-native-host",\n  "type": "stdio",\n  "allowed_origins": ["chrome-extension://%s/"]\n}\n' "$CHROME_ID"
}
for dir in etc/opt/chrome/native-messaging-hosts etc/chromium/native-messaging-hosts etc/opt/edge/native-messaging-hosts; do
    mkdir -p "$PKG/$dir"
    chrome_manifest > "$PKG/$dir/com.tondar.host.json"
    echo "/$dir/com.tondar.host.json" >> "$PKG/DEBIAN/conffiles"
done
mkdir -p "$PKG/usr/lib/mozilla/native-messaging-hosts"
printf '{\n  "name": "com.tondar.host",\n  "description": "Tondar Download Manager",\n  "path": "/usr/lib/tondar/tondar-native-host",\n  "type": "stdio",\n  "allowed_extensions": ["%s"]\n}\n' "$FIREFOX_ID" \
    > "$PKG/usr/lib/mozilla/native-messaging-hosts/com.tondar.host.json"

cat > "$PKG/usr/share/doc/tondar/copyright" <<'TXT'
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: tondar

Files: *
License: GPL-3+
TXT

SIZE=$(du -sk "$PKG/usr" "$PKG/etc" | awk '{s+=$1} END {print s}')
cat > "$PKG/DEBIAN/control" <<CTRL
Package: tondar
Version: $VERSION
Section: net
Priority: optional
Architecture: all
Installed-Size: $SIZE
Depends: python3 (>= 3.11), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.6)
Recommends: ffmpeg
Suggests: yt-dlp
Maintainer: Tondar <maintainer@tondar.invalid>
Description: Fast download manager with browser integration
 Multi-connection, resumable downloads with a download list, categories,
 queue and speed limit. The browser extension takes over downloads and adds
 a download button to videos on web pages (videos are fetched with yt-dlp).
CTRL

cat > "$PKG/DEBIAN/postrm" <<'SH'
#!/bin/sh
set -e
if [ "$1" = purge ]; then
    rm -f /etc/opt/chrome/native-messaging-hosts/com.tondar.host.json \
          /etc/chromium/native-messaging-hosts/com.tondar.host.json \
          /etc/opt/edge/native-messaging-hosts/com.tondar.host.json
fi
SH
chmod 755 "$PKG/DEBIAN/postrm"

dpkg-deb --root-owner-group --build "$PKG" "$B/tondar_${VERSION}_all.deb"
echo
echo "Built $B/tondar_${VERSION}_all.deb"
echo "Install with:  sudo apt install ./$B/tondar_${VERSION}_all.deb"
