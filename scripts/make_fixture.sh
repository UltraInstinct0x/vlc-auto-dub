#!/usr/bin/env bash
# Build a reproducible, clearly-synthesized test video (ffmpeg test pattern +
# a 440 Hz tone). Test-only media: it is not real production footage.
#
# Usage: scripts/make_fixture.sh [output.mp4] [seconds]
set -euo pipefail

out="${1:-fixture.mp4}"
seconds="${2:-4}"
size="${3:-320x240}"

ffmpeg -y -v error \
  -f lavfi -i "testsrc=size=${size}:rate=15:duration=${seconds}" \
  -f lavfi -i "sine=frequency=440:duration=${seconds}" \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$out"

echo "wrote synthesized fixture: $out (${size}, ${seconds}s, tone audio)"
