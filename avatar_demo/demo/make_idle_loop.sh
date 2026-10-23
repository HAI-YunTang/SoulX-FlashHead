#!/usr/bin/env bash
# Build the browser's idle loop from frames saved by render_idle_clip.py.
#   bash make_idle_loop.sh <frames_dir> <out.mp4>
# Ping-pong (forward, then reversed) loops seamlessly: the pose drifts over a render, so no
# forward-only cut point matched closely. The first second is skipped (motion settles there).
set -euo pipefail
FRAMES=${1:?frames dir}
OUT=${2:?output mp4}
START=25
N=$(ls "$FRAMES"/*.jpg | wc -l)
LEN=$((N - START))                 # forward frames
TOTAL=$((2 * LEN - 2))             # reverse without its first and last frame
ffmpeg -loglevel error -y -framerate 25 -start_number $START -i "$FRAMES/%05d.jpg" -filter_complex \
  "[0]split[f][r0];[r0]reverse,trim=start_frame=1,setpts=PTS-STARTPTS[r];[f][r]concat=n=2:v=1,trim=end_frame=$TOTAL,setpts=PTS-STARTPTS[v]" \
  -map "[v]" -c:v libx264 -crf 18 -g 50 -preset slow -pix_fmt yuv420p -movflags +faststart -an "$OUT"
echo "wrote $OUT ($TOTAL frames)"
