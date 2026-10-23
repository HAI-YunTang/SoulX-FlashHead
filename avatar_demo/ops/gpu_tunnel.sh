#!/usr/bin/env bash
# Keep the container -> GPU pod tunnel (localhost:8767 -> pod:8766) up; reopen it whenever ssh exits.
# The SkyPilot SSH proxy drops idle or long-lived tunnels, which leaves the avatar on its idle clip.
#   setsid nohup ./gpu_tunnel.sh yuntang-avatar-2gpu > /dev/null 2>&1 < /dev/null &
# Log: logs/gpu_tunnel.log
HOST=${1:-yuntang-avatar-2gpu}
cd "$(dirname "$0")" && mkdir -p logs
while true; do
  echo "$(date +%FT%T) opening tunnel to $HOST" >> logs/gpu_tunnel.log
  ssh -N -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
    -L 8767:localhost:8766 "$HOST" >> logs/gpu_tunnel.log 2>&1 < /dev/null
  echo "$(date +%FT%T) tunnel exited ($?)" >> logs/gpu_tunnel.log
  sleep 2
done
