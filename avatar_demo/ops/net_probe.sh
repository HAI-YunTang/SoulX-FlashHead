#!/usr/bin/env bash
# Log model-API latency over each VM interface every 30 s, to see which path degrades and when.
#   setsid nohup ./net_probe.sh > /dev/null 2>&1 < /dev/null &
# Output: logs/net_probe.log, one line per request: time iface connect_s total_s
# eth0 is Colima's user-mode NAT (default route); col0 is vzNAT (colima start --network-address).
cd "$(dirname "$0")" && mkdir -p logs
URL=https://api.model.hippocraticai.com/prod/ge4sdb300/v1/models
while true; do
  for IF in eth0 col0; do
    for i in 1 2 3; do
      r=$(curl -s -o /dev/null -m 12 --interface "$IF" -w '%{time_connect} %{time_total}' "$URL" || echo "12 12")
      echo "$(date +%FT%T) $IF $r"
    done
  done >> logs/net_probe.log
  sleep 30
done
