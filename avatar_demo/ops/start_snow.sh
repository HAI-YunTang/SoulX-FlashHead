#!/usr/bin/env bash
# Start local snow (snow_call + snow_web) and the demo_portal UI with the demo settings, detached.
#   ./start_snow.sh          # start whatever is not running yet
# Logs: /tmp/snow_services.log (plus snow_call_service.log in the snow repo), /tmp/snow_ui.log
# Demo settings (defaults; override by exporting before running):
#   MAX_ENGINE_SYNC_TIMEOUTS_ALLOWED=5  snow ends a call on the first safety-engine timeout by default (0)
#   AVATAR_GPU_WS_URL=ws://127.0.0.1:8767  the GPU tunnel (gpu_tunnel.sh)
#   AVATAR_PREBUFFER_S=0.3
#   AVATAR_REPLY_GAP_S=1.0  silence that ends an avatar reply. TTS arrives in bursts 0.5-0.7 s apart within
#                           one turn; the old 0.4 s split turns and padded silence mid-sentence.
set -euo pipefail
source ~/.bashrc >/dev/null 2>&1 || true
SNOW=/home/source_codes/snow
export MAX_ENGINE_SYNC_TIMEOUTS_ALLOWED=${MAX_ENGINE_SYNC_TIMEOUTS_ALLOWED:-5}
export AVATAR_GPU_WS_URL=${AVATAR_GPU_WS_URL:-ws://127.0.0.1:8767}
export AVATAR_PREBUFFER_S=${AVATAR_PREBUFFER_S:-0.3}
export AVATAR_REPLY_GAP_S=${AVATAR_REPLY_GAP_S:-1.0}

listening() { ss -ltn | grep -q ":$1\b"; }

if listening 3000 || listening 4000; then
  echo "snow: already running (port 3000/4000 in use)"
else
  cd "$SNOW"
  setsid nohup make run-all-services RUN_UI=0 > /tmp/snow_services.log 2>&1 < /dev/null &
  echo "snow: starting (about 30-45 s until ports 3000 and 4000 listen)"
fi

if listening 5173; then
  echo "ui: already running (port 5173)"
else
  cd "$SNOW/demo_portal"
  GOMEMLIMIT=400MiB GOGC=50 BROWSER=none \
  VITE_HOOF_API_URL=https://hoof.snow.hippocraticdev.com VITE_PROXY_SERVER_URL=http://127.0.0.1:3000 \
  VITE_ROOT_URL=http://127.0.0.1:4000 VITE_IS_DEV=true VITE_CALL_SERVER_ROOT_URL=http://127.0.0.1:3000 \
    setsid nohup npx vite --port 5173 --host 0.0.0.0 > /tmp/snow_ui.log 2>&1 < /dev/null &
  echo "ui: starting"
fi
echo "demo link: $(cat "$(dirname "$0")/demo_url.txt" 2>/dev/null || echo 'see runbook')"
