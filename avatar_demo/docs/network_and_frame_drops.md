# Why traffic was slow and frames dropped (2026-10-22)

The avatar side (FlashHead on the H200) was never the bottleneck: on the pod it renders a steady 24.9 fps. All of the trouble came from two network faults in the devbox VM, plus one bug in how the GPU server handled clients.

## Symptoms

| Symptom | Seen as |
|---|---|
| Calls ended after 1–2 turns with "Unfortunately I'm having technical difficulties…" | Snow log: `Engine sync timeout exceeded for too many turns for RedTeamEngine`, then `system_ended_call_error` |
| Snow took 2–4 minutes to start | `TwilioSubAccount._fetch_phone_numbers` took 134 s |
| Avatar voice and video choppy and broken up | The stream reached only 8–22 fps instead of 25, with gaps of 0.6–0.9 s between frames |
| `sky` hung while `curl` to the same server worked | `sky api info` stuck in the TLS handshake |

## Cause 1: Colima's default network dropped new connections

The devbox is a Docker container (`--network host`) inside **Colima** (profile `default`, `vz`, 8 CPU, 20 GiB). By default Colima gives the VM only a user-mode NAT on `eth0` (gateway `192.168.5.2`): every TCP connection from the VM is re-created by a userspace process on the Mac.

That NAT dropped connection attempts (TCP SYNs) now and then. DNS answered in 3–40 ms, but connects stalled for 1, 3 or 10 s (the Linux SYN retry times) or never finished. It got worse with uptime: it was clean right after a VM restart, then within about an hour 11 of 21 probes timed out.

| From | Connect over 1 s | Timeouts (30 requests, same URL, same minute) |
|---|---|---|
| Mac | 0 | 0 (worst 0.69 s) |
| Container through `eth0` | 6 | 2 (12 s each) |

Effects:
- **Calls ended.** Snow calls safety engines such as `RedTeamEngine` on the `gemma31bv4itsd` model every turn. One stalled connect made a 4 s inference time out, the retries ran past the engine's 10 s limit, and snow's default `MAX_ENGINE_SYNC_TIMEOUTS_ALLOWED=0` ends the call on the **first** engine timeout.
- **Slow startup.** The Twilio phone-number lookups run at startup even with `DISABLE_TWILIO=true`, and they waited out the stalls.
- **A flaky GPU tunnel.** The SSH tunnel to the pod goes through the SkyPilot API server over the same path, so bursts of stalls also made the avatar stream stutter.

## Cause 2: vzNAT with a 1500 MTU into a 1280 MTU Tailscale path

`colima start --network-address` adds a vzNAT interface `col0` (`192.168.64.2`, gateway `192.168.64.1`). It is routed at the IP level by macOS, so it has no userspace NAT to drop connections. But two problems remained:
- The default route still used `eth0` (metric 200 vs 300 for `col0`).
- Once the route moved to `col0`, the internal `10.x` hosts are reached over the Mac's Tailscale, whose MTU is **1280**. The VM still sent 1500-byte packets, and the "packet too big" message never came back, so large packets just vanished (a path-MTU black hole).

How we proved it: TLS handshakes from Python (OpenSSL 3.5 sends a large post-quantum ClientHello) hung on `col0`. With the TCP segment size capped, they passed:

| TCP MSS | Handshake |
|---|---|
| 1220, 1240 | ok (about 0.5 s) |
| 1260 and up | hangs |

MSS 1240 + 40 bytes of headers = an MTU of 1280. Small requests like `curl` to `/health` fit in one packet and looked fine, which is why the fault was easy to miss. Bulk data, such as video frames and large handshakes, stalled.

## Cause 3: a stale avatar link shared the GPU server's frames

The GPU server keeps **one** shared session buffer, but gave each WebSocket client its own sender task. When a call ended with an error, its goodbye line arrived *after* `END_CALL_DETECTED`. The forwarder then opened a new link for the ended call, and that link stayed connected. During the next call, two senders popped alternate frames from the same buffer, so each stream got about half the frames, with their audio. That is the "both video and voice are not continuous" symptom.

## Fixes

| Fix | Where | Persistent? |
|---|---|---|
| `colima start --network-address` (vzNAT interface `col0`) | Mac | Yes (saved in `~/.colima/default/colima.yaml`) |
| `colima ssh -- sudo ip route replace default via 192.168.64.1 dev col0 metric 50` | Mac | **No**, until the next `colima` restart (see below) |
| `colima ssh -- sudo ip link set col0 mtu 1280` | Mac | **No**, until the next `colima` restart (see below) |
| `MAX_ENGINE_SYNC_TIMEOUTS_ALLOWED=5` when starting local snow | snow env, demo only | Per start command (`runbook.md` step 4) |
| GPU server: one client at a time, newest wins; a replaced client can't stop its successor's session | `demo/gpu_server.py` | Code (test: `demo/test_one_client.py`) |
| Forwarder: ignores audio for ended calls | `snow/devtools/avatar_forwarder.py` | Code (test: `demo/test_forwarder_reconnect.py`) |

To make the route and MTU survive a restart, add a provision script to `~/.colima/default/colima.yaml` (Colima runs `mode: system` scripts as root at every start), then check with `ip route` and `ip link show col0` after the next restart:

```yaml
provision:
  - mode: system
    script: |
      ip route replace default via 192.168.64.1 dev col0 metric 50
      ip link set col0 mtu 1280
```

## Result

On the 7-minute call at 05:47:
- **Agent and network.** 26 turns, with no engine timeouts, link drops or call end, and 1 of 72 network probes over 1 s.
- **Turn latency**, from the final patient transcript to the reply's TTS: median 1.5 s, p90 2.2 s, max 2.8 s. The patient hears the reply about 2.2 s later because of the avatar render.
- **Avatar stream.** Smoke test through the tunnel: 24.3–24.6 fps, with gaps of at most 0.15–0.17 s, against 8–22 fps with gaps of 0.6–0.9 s before.

## Checking it again

- `net_probe.sh` logs latency on `eth0` and `col0` every 30 s to `avatar_demo/ops/logs/net_probe.log`. Start it from `avatar_demo/ops/` with `setsid nohup ./net_probe.sh > /dev/null 2>&1 < /dev/null &`.
- Container vs Mac, same URL. Run this in both places and compare; the container should show no connect over 1 s:

  ```bash
  for i in $(seq 1 30); do curl -s -o /dev/null -m 12 -w '%{time_connect} %{time_total}\n' https://api.model.hippocraticai.com/prod/ge4sdb300/v1/models || echo TIMEOUT; sleep 0.3; done
  ```
- MTU black hole: `sky api info` should answer within seconds. If it hangs while `curl https://skypilot.dev.hippocraticdev.com/api/health` works, the `col0` MTU has been reset to 1500.
