#!/bin/sh
# Build Tondar-<version>-macos-<arch>.dmg on macOS (GitHub Actions or a Mac with Homebrew).
#   brew install gtk4 libadwaita pygobject3 adwaita-icon-theme librsvg
#   tools/build-macos.sh
set -eu
cd "$(dirname "$0")/.."
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' src/tondar/__init__.py)
ARCH=$(uname -m)
PY=${PYTHON:-$(brew --prefix)/bin/python3}

"$PY" -m pip install --break-system-packages --quiet pyinstaller pyinstaller-hooks-contrib

# App icon
mkdir -p build/Tondar.iconset
for s in 16 32 128 256 512; do
  rsvg-convert -w $s -h $s data/io.github.tondar.Tondar.svg -o build/Tondar.iconset/icon_${s}x${s}.png
  rsvg-convert -w $((s * 2)) -h $((s * 2)) data/io.github.tondar.Tondar.svg -o build/Tondar.iconset/icon_${s}x${s}@2x.png
done
iconutil -c icns build/Tondar.iconset -o build/Tondar.icns

"$PY" tools/build-extension.py
"$PY" -m PyInstaller --noconfirm macos/tondar.spec

APP=dist/Tondar.app
mkdir -p "$APP/Contents/MacOS/tools/ffmpeg"
[ -x build/ffmpeg/ffmpeg ] || tools/build-ffmpeg.sh build/ffmpeg
cp build/ffmpeg/ffmpeg build/ffmpeg/ffprobe "$APP/Contents/MacOS/tools/ffmpeg/"
curl -fsSL -o "$APP/Contents/MacOS/tools/yt-dlp" https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos
chmod +x "$APP/Contents/MacOS/tools/yt-dlp"
rm -rf "$APP/Contents/Resources/extension"
cp -R build/extension "$APP/Contents/Resources/extension"

# Files were added after PyInstaller signed the bundle: sign it again (ad hoc, no Apple ID).
codesign --force --deep --sign - "$APP"
codesign --verify --deep "$APP"

# Smoke test: the bridge must answer a ping from the browser.
"$PY" -c "import json,struct,subprocess; d=json.dumps({'cmd':'ping'}).encode(); o=subprocess.run(['$APP/Contents/MacOS/tondar-native-host'],input=struct.pack('=I',len(d))+d,capture_output=True,timeout=60).stdout; print(o[4:]); assert b'\"ok\": true' in o"

DMG="build/Tondar-$VERSION-macos-$ARCH.dmg"
rm -rf build/dmg "$DMG"
mkdir -p build/dmg
cp -R "$APP" build/dmg/
ln -s /Applications build/dmg/Applications
hdiutil create -volname "Tondar $VERSION" -srcfolder build/dmg -ov -format UDZO "$DMG"
ls -lh "$DMG"
