#!/bin/sh
# Build a small ffmpeg + ffprobe for the Windows and macOS packages.
#   tools/build-ffmpeg.sh OUT_DIR
# yt-dlp only uses ffmpeg to merge and remux streams (no re-encoding), so everything
# else is left out: ~10 MB instead of the ~200 MB of a full build.
set -eu

VERSION=7.1.5
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
WORK=${TMPDIR:-/tmp}/tondar-ffmpeg
mkdir -p "$WORK"
cd "$WORK"
[ -f "ffmpeg-$VERSION.tar.xz" ] || curl -fsSL -o "ffmpeg-$VERSION.tar.xz" "https://ffmpeg.org/releases/ffmpeg-$VERSION.tar.xz"
rm -rf "ffmpeg-$VERSION"
tar xf "ffmpeg-$VERSION.tar.xz"
cd "ffmpeg-$VERSION"

case "$(uname -s)" in
  MINGW*|MSYS*|UCRT*|CLANG*) EXTRA="--enable-schannel --extra-ldflags=-static"; EXE=.exe ;;
  Darwin)       EXTRA="--enable-securetransport"; EXE= ;;
  *)            EXTRA=""; EXE= ;;
esac

# shellcheck disable=SC2086
./configure \
  --disable-everything --disable-autodetect --disable-debug --disable-doc \
  --disable-ffplay \
  --disable-shared --enable-static --disable-x86asm --enable-small \
  --disable-avdevice --disable-swscale --disable-postproc \
  --enable-parsers --enable-bsfs \
  --enable-protocol=file,pipe,http,https,tcp,tls,crypto,hls,data \
  --enable-demuxer=mov,matroska,mpegts,hls,aac,mp3,flv,ogg,wav,concat,h264,hevc,webvtt \
  --enable-muxer=mp4,mov,ipod,matroska,webm,mpegts,adts,mp3,ogg,opus,flv,webvtt \
  --enable-decoder=aac,mp3,opus,vorbis,ac3,h264,hevc,vp9,webvtt \
  --enable-filter=null,anull,copy,acopy,aformat,format,aresample \
  $EXTRA

make -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"
strip "ffmpeg$EXE" "ffprobe$EXE" 2>/dev/null || true
cp "ffmpeg$EXE" "ffprobe$EXE" "$OUT/"
"$OUT/ffmpeg$EXE" -hide_banner -version | head -1
ls -l "$OUT"
