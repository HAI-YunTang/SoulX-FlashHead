# Runbook: nurse avatar video-call demo

A patient on the local Mac video-calls a nurse avatar. Snow runs the conversation, including voice detection, speech recognition (Deepgram Nova-3), the agent, and TTS (ElevenLabs, Rebecka voice). SoulX-FlashHead Pro runs on a GPU pod and lip-syncs `avatar_demo/figures/nurse_image3.png` to the agent's speech.

Status (2026-10-22): working end to end. A 7-minute call ran with no drops, at a median turn latency of 1.5 s, and the avatar played at about 25 fps. **Network setup matters:** read step 0 and `network_and_frame_drops.md`.

```
Mac Chrome  /dev/call?avatar=1 (VOIP)
  |  localhost:5173 / 3000 / 4000  (Colima port forwarding, or ssh -L to the devbox)
  v
devbox container (Docker --network host, inside the Colima VM)
  demo_portal (Vite)  :5173   AvatarPanel: idle loop clip <-> live frames, crossfade
  snow_web            :4000
  snow_call           :3000   VAD -> ASR -> agent -> TTS
     |  devtools/avatar_forwarder.py: TTS 44.1 kHz -> 16 kHz, "end" after 0.4 s of silence,
     |  "flush" only on interrupt_tts_audio; reconnects with backoff; "avatarstatus" to the browser
     |  ws://127.0.0.1:8767
     |  ssh -L 8767:localhost:8766  (container -> SkyPilot proxy -> pod)
     v
GPU pod (SkyPilot yuntang-avatar-h200: 1x H200 on the reserved cw-usw4 speech node; alternative: yuntang-avatar-2gpu)
  avatar_demo/demo/gpu_server.py  :8766   FlashHead Pro, one client at a time; JPEG (q70) + 640 PCM samples per 1/25 s frame
     |
     +--> frames go back up the same link; snow_call emits them as socket.io "avatarframe"
          to the call's room; the browser plays the audio inside the frames, synced to video
```

## Where things are

Everything for the demo lives in the SoulX-FlashHead fork (`git@github.com:HAI-YunTang/SoulX-FlashHead.git`, branch `yuntang/nurse-avatar-demo`), checked out at `/home/source_codes/SoulX-FlashHead`, under `avatar_demo/`. Paths below are relative to the repo root unless noted. The pod runs the same checkout (`~/sky_workdir`), so `sky exec` ships code changes; there is no separate copy step.

| What | Path |
|---|---|
| GPU server, its parts and unit tests | `avatar_demo/demo/`: `gpu_server.py`, `playback_buffer.py`, `avatar_engine.py`, `audio_chunker.py`, `wire.py`, `start_gpu_server.sh`, `test_*.py` |
| Smoke and end-to-end tests | `avatar_demo/demo/test_client.py` (prints fps and Mbit/s), `test_flush_e2e.py` (barge-in flush), `test_one_client.py` |
| Attention benchmark | `avatar_demo/demo/bench_attention.sh` |
| Idle clip tools | `avatar_demo/demo/render_idle_clip.py` (renders frames from near-silence), `avatar_demo/demo/make_idle_loop.sh` (builds the ping-pong loop mp4) |
| Nurse image | `avatar_demo/figures/nurse_image3.png` |
| SkyPilot configs | `avatar_demo/configs/`: `skypilot_avatar_h200_cw_usw4_speech.yaml` (current), `skypilot_avatar_2gpu_rtxp6000_use15.yaml`, `skypilot_avatar_h200_do_atl1.yaml` |
| Local ops scripts | `avatar_demo/ops/`: `start_services.sh` (Postgres, Redis), `start_snow.sh`, `gpu_tunnel.sh` (watchdog), `net_probe.sh`, `demo_settings.sh`, `avatar_demo/ops/demo_url.txt`. Logs go to `avatar_demo/ops/logs/` (git-ignored). |
| DB snapshot of the demo rows | `avatar_demo/ops/demo_settings/` (git-ignored: it holds a test patient record) |
| Docs | `avatar_demo/docs/`: this runbook, `demo_system.html` (system description), `network_and_frame_drops.md`, `container_packages.md` and `container_request.md` (the devbox), plus history: `task_integrate.md` (the original brief), `pro_2gpu_working_config_benchmark.md` |
| FlashHead change | `flash_head/src/modules/flash_head_model.py`, `flash_head/src/pipeline/flash_head_pipeline.py`: the `FH_*` switches |
| Snow changes (snow repo, branch `yuntang/nurse-avatar-demo`) | `devtools/avatar_forwarder.py`, `devtools/snow_devtools_main.py`; page: `demo_portal/src/services/AvatarPlayer.ts` (+ test), `views/call_dev/AvatarPanel.tsx`, hooks in `CallManager.ts`, `AudioHandler.ts`, `CallDevDialerView.tsx`; `public/avatar/nurse.png`, `nurse_idle.mp4` |
| Results and idle-clip frames (not in git) | the old work dir `/home/works/2026/video_avatar/20261021_soulX-FlashHead/results/` on the devbox |

## Demo defaults

These settings are the demo's defaults; each is pinned by a file in `avatar_demo/ops/`:

| Setting | Value | Pinned by |
|---|---|---|
| Agent | "Stacy" (`240330eb-8274-405c-86b1-931203191157`) | `avatar_demo/ops/demo_url.txt` (link) + `avatar_demo/ops/demo_settings/` (DB row) |
| Voice / TTS | ElevenLabs voice `BzE3m5hwd6OqXT6Gg2Vg`, model `eleven_v3_conversational`, speed 1.13 | Stacy's `call_settings` in `avatar_demo/ops/demo_settings/agent.agents.json` |
| ASR | context-aware ASR, URL `https://eval-api.model.hippocraticai.com/asrv3/v1` | Stacy's `call_settings` (`CONTEXT_AWARE_ASR_API_URL`) |
| Script | "[Demo] Simplified Discharge: CHF — thinkv3, Engines Off" (`67a8386a-c8d5-4166-ac11-2476e8ec7441`), version `v1.617.1-27-g997197dce` | `avatar_demo/ops/demo_url.txt` + `avatar_demo/ops/demo_settings/call_script.*.json` |
| Patient | Jane Anderson (`826cf739-fc8d-45d7-a536-d6ad1aa740eb`), **date of birth October 8, 1950** | `avatar_demo/ops/demo_url.txt` + `avatar_demo/ops/demo_settings/patient.patients.json` |
| Call method | VOIP | `avatar_demo/ops/demo_url.txt` |
| Avatar page | `avatar=1&avatar_delay_ms=2550`, with a 500 ms browser buffer (the code default since 2026-10-22). Line 2 sets `avatar_jitter_ms=500` explicitly; it behaves the same. | `avatar_demo/ops/demo_url.txt` |
| Snow environment | `MAX_ENGINE_SYNC_TIMEOUTS_ALLOWED=5`, `AVATAR_GPU_WS_URL=ws://127.0.0.1:8767`, `AVATAR_PREBUFFER_S=0.3`, `AVATAR_REPLY_GAP_S=1.0` | `start_snow.sh` |

- **Demo link.** `avatar_demo/ops/demo_url.txt` line 1 is the demo link. Its `config=` value is base64url JSON (`{"method":"voip","patientId":…,"callConfig":{"agent_id":…,"script_id":…}}`), which `/dev/call` reads instead of the selection your browser remembered. The browser buffer now defaults to 500 ms in the code (`DEFAULT_JITTER_S` in `AvatarPlayer.ts`; it was 150 ms). That rides out the 0.22–0.35 s gaps between frames through the tunnel to the usw4 H200. Line 2 sets the same value explicitly. `avatar_delay_ms=2550` is tuned for the H200's first frame of about 2.2 s plus the 0.5 s buffer; on 2x RTX use about 2850.
- **DB rows.** `make sync-data` can overwrite the agent, script and patient. Put them back with `avatar_demo/ops/demo_settings.sh restore`. After you change them on purpose, take a new snapshot with `avatar_demo/ops/demo_settings.sh save`.
- **The older agent.** The first demo calls used agent "Rachel" (`ed9ca802…`), with the Rebecka voice and `context-aware-asr-v3` (one-time setup, step 7). It's still configured, but it isn't the default any more.

## Starting the demo

Follow these steps in order each time. Step 0 runs on the Mac, steps 1–4 in the devbox container, and step 5 on the Mac.

### 0. Colima network (Mac, after every `colima start`)

Colima's default user-mode NAT drops connections, and the vzNAT link needs a smaller MTU for the Tailscale path. See `network_and_frame_drops.md` for the evidence. Once per Colima VM:

```bash
colima start --network-address
```

After every Colima start, unless the provision script in `network_and_frame_drops.md` is installed:

```bash
colima ssh -- sudo ip route replace default via 192.168.64.1 dev col0 metric 50
```

```bash
colima ssh -- sudo ip link set col0 mtu 1280
```

Check from the container: `ip route | grep default` should list `col0 metric 50` first, `ip link show col0` should show `mtu 1280`, and `sky api info` should answer within seconds. To undo, delete the route with `ip route del default via 192.168.64.1 dev col0 metric 50`, or restart Colima.

Start the container with:

```bash
make run IMAGE=snow:latest CONTAINER=snow HOSTKEY_VOLUME=snow-ssh-hostkeys DOCKER_RUN_ARGS='--init --network host --cpus 8 --memory 16g --memory-swap 24g'
```

### 1. Postgres and Redis

The container has no systemd, so run this after every container restart:

```bash
/home/source_codes/SoulX-FlashHead/avatar_demo/ops/start_services.sh
```

It should print `postgres: ok 15.x` and `redis: PONG`. Also run `git update-index --refresh` in `/home/source_codes/snow` and `/home/source_codes/igloo`, to stop the `git-lfs` CPU storm from the Claude app's diff watcher.

Optional: start the network probe, so you can match any slow turns to network stalls later:

```bash
cd /home/source_codes/SoulX-FlashHead/avatar_demo/ops && setsid nohup ./net_probe.sh > /dev/null 2>&1 < /dev/null &
```

### 2. GPU server

**Current (2026-10-22 20:52): `yuntang-avatar-h200`**, 1x H200 on the reserved cw-usw4 speech node `gd942bc`, in SkyPilot workspace **`speech`**. Every `sky` command for this cluster needs `--config active_workspace=speech`:

```bash
source /home/source_codes/skypilot-infra/.venv/bin/activate
cd /home/source_codes/SoulX-FlashHead
sky status --config active_workspace=speech
sky launch -c yuntang-avatar-h200 --config active_workspace=speech \
  avatar_demo/configs/skypilot_avatar_h200_cw_usw4_speech.yaml --workdir . -y -d
sky logs yuntang-avatar-h200 <job id> --no-follow --config active_workspace=speech | tail -3
```

- **The config.** `avatar_demo/configs/skypilot_avatar_h200_cw_usw4_speech.yaml` is the node's template (`infra: k8s/hai-cw-usw4-cks-speech`, the `hai/reserved: yuntang-sa` nodeSelector, the `hai/reserved` and `workload/gpu` tolerations) plus the avatar setup and run sections.
- **Resources.** It sets `cpus: 16+` and `memory: 64+`. Without them SkyPilot gives 4 CPUs and 16 GB, too little for FlashHead.
- **Timing.** On 2026-10-22, launch to `listening` took 10 minutes, including a cold warm-up of 164 s.
- **Measured.** On the pod: 24.9 fps, gaps of at most 0.08–0.12 s, first frame after 1.92 s. Through the tunnel: 24.4–25.0 fps and a first frame after 2.15–2.26 s, but gaps of up to 0.22–0.35 s, so use demo link 2. The very first request after warm-up had a single 3.8 s stall, so run one smoke test before the demo.
- **Releasing the node.** When done, remove its reservation with the two `kubectl` commands in the config header.

Run the tunnel watchdog with this host: `avatar_demo/ops/gpu_tunnel.sh yuntang-avatar-h200` (step 3).

**Alternative: 2x RTX Pro 6000.** The rest of this section describes it.

The 2x RTX alternative is **`yuntang-avatar-2gpu`**: 2x RTX Pro 6000 (Blackwell) on `hai-cw-use15-cks`, using the working setup from `20261020_soulX-FlashHead/reports/pro_2gpu_working_config_benchmark.md`. The 1x H200 (`yuntang-avatar-h200`, do-atl1) is the alternative; it was taken down on 2026-10-22 (see "Alternative: 1x H200" below).

Use the SkyPilot client from `skypilot-infra`:

```bash
source /home/source_codes/skypilot-infra/.venv/bin/activate
cd /home/source_codes/SoulX-FlashHead
sky status
sky queue yuntang-avatar-2gpu
```

**If the cluster is not up**, check capacity, then launch it. On 2026-10-22 there were 10 of 80 free on use15.

```bash
sky gpus list RTXPRO-6000-BLACKWELL-SERVER-EDITION --infra kubernetes
```

```bash
sky launch -c yuntang-avatar-2gpu avatar_demo/configs/skypilot_avatar_2gpu_rtxp6000_use15.yaml \
  --workdir . -y -d
```

- **What the config includes.** It folds in the three manual steps from the 2-GPU report:
  - xfuser 0.4.3 instead of 0.7.0
  - NCCL 2.27.3 installed to `/root/nccl227` (the bundled 2.26.2 hangs or crashes)
  - `examples/` and `flash_head/ltx_video/models` mounted (the workdir sync drops them)

  It also installs torch 2.7.1, sageattention 1.0.6 and flash-attn 2.7.4.post1, and downloads the models.
- **Setup time.** Provisioning plus setup took about 10 minutes on 2026-10-22, and worked on the first try.
- **How it runs.** The `run` section starts `avatar_demo/demo/start_gpu_server.sh`. On 2 or more GPUs it runs `torchrun --nproc_per_node=2` with these settings:
  - `LD_PRELOAD=/root/nccl227/nvidia/nccl/lib/libnccl.so.2`
  - `FH_USP_ATTN=TORCH_EFFICIENT`
  - `NCCL_MIN_NCHANNELS=4`

  Rank 0 serves the WebSocket and broadcasts each chunk to rank 1 (`RankLink`, a gloo group).
- **Startup time.** Warm-up takes about 81 s; both ranks log `warmup done`, then `gpu_server listening on 0.0.0.0:8766`.

Wait for the server:

```bash
sky logs yuntang-avatar-2gpu <job id> --no-follow | grep -E 'warmup done|listening' | tail -3
```

**To restart the server, or after a code change:** commit or just save the change in the checkout, then re-run the `run` section. `sky exec` re-syncs the repo, which includes `avatar_demo/`. A running server job holds the GPUs, so cancel it first:

```bash
sky cancel yuntang-avatar-2gpu <running job id> -y
sky exec yuntang-avatar-2gpu avatar_demo/configs/skypilot_avatar_2gpu_rtxp6000_use15.yaml --workdir . -d
```

**Alternative: 1x H200 on do-atl1.** This is faster: 1.4x real time with SageAttention, and the first frame comes about 0.3 s sooner. Use it when use15 has no 2 free RTX GPUs. Check with `sky gpus list H200`; on 2026-10-21, `do-atl1-hai-do-atl1-doks` had H200s free. All the commands above work with `-c yuntang-avatar-h200` and `avatar_demo/configs/skypilot_avatar_h200_do_atl1.yaml`. On 1 GPU the server runs plain `python`, and warm-up takes about 64 s.

```bash
sky launch -c yuntang-avatar-h200 avatar_demo/configs/skypilot_avatar_h200_do_atl1.yaml \
  --workdir . -y -d
```

Server settings are environment variables; the configs set the defaults in `envs:`, and `sky exec --env NAME=value` overrides them:

| Variable | Default | Effect |
|---|---|---|
| `AVATAR_JPEG_QUALITY` | 70 | 18.9 kB per frame, about 3.8 Mbit/s. Quality 85 is 27.9 kB, about 5.6 Mbit/s. |
| `FH_USP_ATTN` | `TORCH_EFFICIENT` (set by `start_gpu_server.sh` on 2+ GPUs) | Attention kernel for sequence parallel. The yunchang flash path needs `flash_attn` and is untested here. |
| `FH_ATTN` | SageAttention if installed | 1 GPU only: `SDPA`, `SAGE`, `FA2` or `FA3`. |
| `NUM_GPUS` | all visible | Set it to 1 to run on a single GPU. |
| `GPU_SERVER_DEBUG` | unset | Logs each chunk's render time. |

The server serves **one client at a time**: a new connection closes the previous one, so a stale link can't share the frames.

### 3. Tunnel from the container to the pod

The tunnel goes through the SkyPilot SSH proxy, which drops it now and then. It dropped twice on 2026-10-22, leaving the avatar stuck on its idle clip while snow logged `Avatar reconnect failed ... Connection refused`. So run it under the watchdog, which reopens it whenever `ssh` exits:

```bash
cd /home/source_codes/SoulX-FlashHead/avatar_demo/ops && setsid nohup ./gpu_tunnel.sh yuntang-avatar-h200 > /dev/null 2>&1 < /dev/null &
```

The log is `avatar_demo/ops/logs/gpu_tunnel.log`. To stop it, kill the `gpu_tunnel.sh` loop first, then its `ssh`; find them with `ps -eo pid,args | grep -E '[g]pu_tunnel|[s]sh -N'`. Pass `yuntang-avatar-2gpu` as the host for the 2x RTX cluster. Once the tunnel is back, snow reconnects on the nurse's next reply.

Check that `ss -ltnp | grep 8767` shows `ssh` listening, then smoke-test the server:

```bash
python avatar_demo/demo/test_client.py --url ws://127.0.0.1:8767 \
  --wav /home/works/2026/video_avatar/20261020_soulX-FlashHead/results/tts_rebecka_test.wav --prebuffer_s 0.3
```

Use `yuntang-avatar-h200` as the host if you run the H200. Expected output:
- 196 frames with `bad: 0`
- the first frame after about 2.5 s (2x RTX) or 2.2 s (H200)
- delivery at 24–25 fps, with a max gap of about 0.15 s
- `jpeg size: ~19 kB per frame = 3.8 Mbit/s`

Gaps of 0.5 s or more, or a rate below 23 fps, mean a network problem (step 0). To rule the network out, run the same test on the pod against `ws://127.0.0.1:8766`. `test_client.py` needs `numpy` and `websockets`.

After a route change or a server restart, the tunnel can go stale. Kill that `ssh` by its PID and reopen it.

### 4. Snow (call and web services) and the UI

Start snow_call, snow_web and the UI with the demo settings. The script starts only what isn't already running, and prints the demo link:

```bash
/home/source_codes/SoulX-FlashHead/avatar_demo/ops/start_snow.sh
```

`MAX_ENGINE_SYNC_TIMEOUTS_ALLOWED=5` is a demo-only setting. Snow's default is 0, which ends the call on the first safety-engine timeout. With 5, a stalled engine skips that turn, sometimes with a filler line. To override a setting, export it before running the script.

The script runs the equivalent of these two commands:

```bash
source ~/.bashrc
cd /home/source_codes/snow
MAX_ENGINE_SYNC_TIMEOUTS_ALLOWED=5 AVATAR_GPU_WS_URL=ws://127.0.0.1:8767 AVATAR_PREBUFFER_S=0.3 \
  setsid nohup make run-all-services RUN_UI=0 > /tmp/snow_services.log 2>&1 < /dev/null &
```

It takes about 30–45 s until ports 3000 and 4000 listen. Confirm the forwarder is on:

```bash
grep -a 'Avatar forwarder enabled' snow_call_service.log | tail -1
```

To restart snow, kill its process group. Find the group with `ps -eo pgid,args | grep 'make run-all-services'`, check that the group contains `snow_call`, then run `kill -TERM -- -<pgid>`.

For the UI, Vite must listen on all interfaces and not try to open a browser. `GOMEMLIMIT` keeps esbuild's memory down.

```bash
cd /home/source_codes/snow/demo_portal
GOMEMLIMIT=400MiB GOGC=50 BROWSER=none \
VITE_HOOF_API_URL=https://hoof.snow.hippocraticdev.com VITE_PROXY_SERVER_URL=http://127.0.0.1:3000 \
VITE_ROOT_URL=http://127.0.0.1:4000 VITE_IS_DEV=true VITE_CALL_SERVER_ROOT_URL=http://127.0.0.1:3000 \
  setsid nohup npx vite --port 5173 --host 0.0.0.0 > /tmp/snow_ui.log 2>&1 < /dev/null &
```

Use this command instead of `make run-ui`. `make run-ui` binds only to localhost, tries to open a browser, and deletes Vite's dependency cache.

Check the services from the container:

```bash
for u in http://127.0.0.1:3000/ http://127.0.0.1:4000/ http://127.0.0.1:5173/dev/call; do curl -s -o /dev/null -w "%{http_code} $u\n" $u; done
```

Expect `302`, `302` and `200`.

### 5. On the Mac

Open the **demo link**, line 1 of `avatar_demo/ops/demo_url.txt` (`start_snow.sh` prints it). It selects the demo agent, script, patient and VOIP. A plain `http://localhost:5173/dev/call?avatar=1` also works, but it uses whatever agent and script your browser last chose. If the page doesn't load, forward the ports over SSH and leave this running:

```bash
ssh -N -L 5173:localhost:5173 -L 3000:localhost:3000 -L 4000:localhost:4000 devbox
```

Then:
1. If prompted, log in through the Okta app **"Hippocratic AI Dev - Localhost"**.
2. Check that the dialer shows agent Stacy, the CHF demo script, Jane Anderson and VOIP. Click **Start Call once**. Wait 10–20 s for the first line; don't click again, because two calls overlapping is what caused a stale link.
3. If there is no sound, click the nurse panel once to enable browser audio.
4. **Test patient:** Jane Anderson, date of birth **October 8, 1950** (say "October eighth, nineteen fifty"). With the older agent's patient, James Rodriguez, it's January 1, 1960.

What to expect:
- **Each reply.** The avatar starts speaking about 2.5 s after snow's TTS starts on 2x RTX, or 2.2 s on the H200. Snow's own playback is muted and delayed 2 s by default, so its turn-taking roughly matches what the patient hears. On 2x RTX, try `?avatar=1&avatar_delay_ms=2500` to match the longer render.
- **Browser buffer.** `avatar_jitter_ms` (default 500) is how much audio the browser buffers before playing. A larger buffer smooths network gaps but delays the nurse by the same amount, so change `avatar_delay_ms` by that amount too.
- **Between replies.** A 15.8 s idle loop plays (head sway and blinks, mouth closed) and crossfades over 150 ms to the live frames when the nurse speaks. The caption shows Speaking or Listening.
- **If the GPU link drops.** The caption shows "Video paused (voice only)", and snow's own voice is unmuted so the call continues. The forwarder reconnects with a backoff from 0.5 s up to 5 s, and the avatar comes back on the next reply.
- **Interruptions.** When the patient barges in, the nurse stops at once:
  - The page crossfades to the idle clip.
  - The forwarder flushes the GPU server on snow's `UTTERANCES_CANCELED` and drops frames still in flight until the server answers `flushed`.
  - The server discards the chunk it was rendering and resets motion to the reference image and the audio context to silence.
  - About 1.5 s later, fresh idle frames (mouth closed) bring the live canvas back. The next turn starts from new audio.
  - The snow log shows `Avatar flush (barge-in): … utterance_ids=[…]` and then `Avatar flushed: … stale_frames_dropped=N`.
- **Plain voice call.** Without `?avatar=1`, the page is the normal voice-only call.

### 6. Shutting down

The GPU clusters bill while they are up. Take `yuntang-avatar-2gpu` down only when development stops (relaunching takes about 12 minutes):

```bash
source /home/source_codes/skypilot-infra/.venv/bin/activate
sky down yuntang-avatar-2gpu
```

Kill the tunnel `ssh` too (find its PID with `ss -ltnp | grep 8767`).

To stop the local services, kill them by PID or process group (see "Process gotchas"). Postgres and Redis can stay running. Their data is in `/home/pgdata` and `/home/redisdata`, which survive container rebuilds.

## One-time setup (already done on this devbox)

Repeat these steps only on a new container.

1. **Colima.** Profile `default`, `vz`, 8 CPU, 20 GiB, started with `--network-address` (step 0).
2. **Packages.** `container_packages.md` lists what to add to the Dockerfile:
   - the PGDG `postgresql-15` packages with pgvector
   - Redis, and Node 24 from NodeSource
   - git-lfs, ffmpeg and `make`
   - `libportaudio2` (snow_call and snow_web crash without it)
   - the weasyprint, audio and geos libraries
3. **Postgres and Redis.** Postgres 15 runs as the container user, with its data in `/home/pgdata/15` on port 5432. The superuser is `postgres` with password `postgres`, and `~/.pgpass` holds that password. Redis runs on port 6379 with its data in `/home/redisdata`.
4. **Snow `.env`.** Copy the team `.env` from 1Password to `/home/source_codes/snow/.env`, then apply the container fixes:
   - `IGLOO_HOME=/home/source_codes/igloo`
   - `SNOW_API_URL=http://localhost:5173`
   - `SNOW_TELEPHONE_URL=localhost:3000` (only phone calls use this)
   - `DEVTOOLS_LOCAL_FILE_UPLOAD_PATH=/home/source_codes/snow/devtools/uploads` (replaces a Mac path)
   - `USE_PROXY_SERVER=False`, `DISABLE_TWILIO=true`, `SNOW_DATABASE_PASSWORD=postgres`

   The original file is backed up as `.env.bak.20261021`. Copy `demo_portal/.env` from `.env.example`.
5. **`~/.bashrc`.** Set `SNOW_HOME`, `PYTHONPATH=$SNOW_HOME`, `IGLOO_HOME`, `HAI_EMAIL`, `HAI_GIVEN_NAME`, `HAI_FAMILY_NAME`, `HAI_SUB_UUID`, `SNOW_DATABASE_NAME=hippocraticai` and `SNOW_DATABASE_USER=postgres`.

   `HAI_SUB_UUID` is the "Sub" from https://snow.hippocraticdev.com/admin/users. For Auth0 logins it looks like `samlp|okta-dev-hai|<email>`, and that value works because Auth0 logins match users by email.
6. **Snow install and database.**
   - Run `git lfs pull` in snow and igloo.
   - Create the databases. `make db-create-local-db` uses docker, so run the equivalent commands directly:

     ```bash
     createdb -h 127.0.0.1 -U postgres hippocraticai
     createdb -h 127.0.0.1 -U postgres hippocraticai_test
     createuser -h 127.0.0.1 -U postgres hippocraticai_test_db_user -i -s -d -e -r
     ```

   - Then run `make install`, `make alembic-upgrade db-insert-self-as-superadmin db-enable-sso`, and `make sync-data`.
7. **Agent settings for the demo.** These are stored in the local DB only, and `make sync-data` may overwrite them.

   ```sql
   -- psql -h 127.0.0.1 -U postgres -d hippocraticai
   update agent.agents set call_settings = '{"en": {"asr_service": "dg-nova-3-general",
     "voice_settings": {"tts_service": "eleven_labs", "eleven_labs_voice_id": "pMGVep9K6NsbHTohrjzi",
       "eleven_labs_stability": 0.5, "eleven_labs_similarity": 0.9, "eleven_labs_speed": 1.13,
       "fallback_tts_service": "emotivox"},
     "eleven_labs_voice_id": "pMGVep9K6NsbHTohrjzi"}, "other_settings": {}}'::jsonb
   where agent_id = 'ed9ca802-fb12-46d8-8298-dae2d2e7f81c';
   ```

   Why these settings:
   - **Speech recognition.** The default in-house `context-aware-asr-v3` took 8–31 s per turn over the Mac's Tailscale route. Deepgram cloud Nova-3 takes about 0.2 s, using `DEEPGRAM_API_KEY`.
   - **Voice.** The voice ID must sit inside `voice_settings`. The top-level `eleven_labs_voice_id` alone is ignored.
8. **Idle clip.** This is already built. To rebuild it, for example for a new nurse image, run these against the live server (with no call active), then copy the mp4 to `snow/demo_portal/public/avatar/nurse_idle.mp4`:

   ```bash
   python avatar_demo/demo/render_idle_clip.py --url ws://127.0.0.1:8767 --seconds 8 --out_dir results/idle_frames
   bash avatar_demo/demo/make_idle_loop.sh results/idle_frames results/nurse_idle.mp4
   ```

   The loop plays forward and then reversed (ping-pong). The pose drifts over a render, so no forward-only cut point matched closely.

## Measured performance

The test used FlashHead Pro, 512x512 at 25 fps, with 28-frame chunks of 1.12 s each.

| GPU | Attention | Seconds per chunk | fps | Notes |
|---|---|---|---|---|
| 1x H200 | SageAttention 1.0.6 (default when installed) | 0.773 | 36.2 | Demo GPU until 2026-10-22 06:00 |
| 1x H200 | FlashAttention 2.7.4 | 0.795 | 35.2 | |
| 1x H200 | torch SDPA | 0.807 | 34.7 | Reference output; Sage and FA2 differ from it by a mean of 5.6–6.0 out of 255 |
| 2x RTX Pro 6000 | TORCH_EFFICIENT (USP), NCCL 2.27.3 | about 1.13 | about 24.7 | **Demo GPU since 2026-10-22.** Warm-up 81 s; denoise about 0.155 s per step. Per-chunk time is from the 2026-10-20 report. |
| 1x RTX Pro 6000 | — | about 1.55 | about 18 | Slower than real time |

Re-run the attention benchmark on the pod with `bash avatar_demo/demo/bench_attention.sh SDPA SAGE FA2`.

End-to-end smoke tests through the tunnel (2026-10-22, after the network fixes):

| | 2x RTX Pro 6000 | 1x H200 |
|---|---|---|
| First frame after a reply starts | 2.45–2.57 s | 2.2 s (1.9 s on the pod itself) |
| Delivery during playback | 24.4–24.6 fps | 24.3–24.6 fps (24.9 on the pod itself) |
| Largest gap between frames | 0.08–0.16 s | 0.15–0.17 s |
| 31 s reply | 728 frames, 24.4 fps, gaps of at most 0.16 s: no drift | not tested |
| Headroom over real time | about 1.0x | about 1.4x |

The first frame waits 1.12 s for the first chunk of live audio, then rendering (about 1.1 s on 2x RTX, 0.8 s on the H200), plus the network. Bandwidth is 3.8 Mbit/s at JPEG quality 70; raw throughput from the pod over SSH is 9–12 Mbit/s.

Snow, on the 7-minute call of 2026-10-22 05:47 on the H200 (26 turns):

| Stage | Time |
|---|---|
| Final patient transcript to the reply's TTS | median 1.5 s, p90 2.2 s, max 2.8 s |
| Plus the avatar render, for what the patient hears | about 2.2 s (H200; this call), about 2.5 s on 2x RTX |
| Agent LLM | usually 0.3–0.45 s |
| ElevenLabs TTS | 0.3–0.45 s |
| Snow start to ports up | 30–45 s (minutes when the network drops connections) |
| VAD cancels | 7 in 7 minutes |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Call ends with "Unfortunately I'm having technical difficulties…" | A safety engine (usually `RedTeamEngine`) timed out, and snow's default allows 0 timeouts. Start snow with `MAX_ENGINE_SYNC_TIMEOUTS_ALLOWED=5` (step 4), and fix the network (step 0). Check the snow_call log for `Engine sync timeout exceeded`. |
| Avatar voice and video choppy, as if every other frame is missing | Two clients were connected to the GPU server; a stale link from an earlier call shared the frames. Fixed: the server now keeps one client and the forwarder ignores ended calls. Start a call only once. On older code, restart the GPU server. |
| Avatar choppy with a smoke test below 23 fps or gaps over 0.5 s | Network. Check step 0: the route on `col0` with MTU 1280. Compare with the same test on the pod against `127.0.0.1:8766`. |
| `sky ...` hangs, or `ApiServerConnectionError`, while `curl` to the API server works | MTU black hole: `col0` is back to 1500 after a Colima restart. Run `colima ssh -- sudo ip link set col0 mtu 1280`. |
| snow_call slow to start (port 3000 not listening for minutes) | Startup retries the Twilio sub-account lookups over a bad network, even with `DISABLE_TWILIO=true`. Fix the network (step 0). |
| snow_call or snow_web crash: `libportaudio.so.2: cannot open shared object file` | Run `sudo apt-get install -y libportaudio2` (and `make` if `make` is missing). Both are in `container_packages.md`. |
| Mac browser: "localhost refused to connect" | Use the Mac `ssh -L` command from step 5. Vite must listen on `0.0.0.0` (`--host 0.0.0.0`). |
| Vite dies: `spawn xdg-open ENOENT` | The config has `server.open`. Start it with `BROWSER=none`. |
| Vite dies: `esbuild ... The service was stopped` | Out of memory. Check `oom_kill` in `/sys/fs/cgroup/memory.events`. Keep `GOMEMLIMIT=400MiB`, and don't use `make run-ui`, which wipes the cache. |
| `ssh`/`scp` to the pod: `timed out during opening handshake` | The SkyPilot websocket proxy is flaky, or the network needs step 0. Retry. |
| Phone call never rings | Twilio is disabled (`DISABLE_TWILIO=true`) and would also need ngrok. Use VOIP. |
| Agent slow to respond to the patient | Make sure the agent uses `dg-nova-3-general` (one-time setup, step 7). `dg-on-prem-*` services go to the staging Deepgram server, about 7 s. |
| Wrong voice ("Rachel" sound) | Set the voice ID in `en.voice_settings`. "Rachel" is also the script's persona name, so she still introduces herself as Rachel. |
| Avatar panel shows the idle loop but never speaks | Check the snow_call log for `Avatar link open`, `Avatar server unreachable` or `Avatar reconnect failed`. Check the tunnel with `ss -ltnp \| grep 8767`. If the tunnel has gone stale, kill that `ssh` and reopen it. If port 8767 is taken, a fake server or an old tunnel is still running. |
| Nurse pauses mid-sentence, with voice and mouth stopping together | The forwarder ended the reply early and the GPU server padded silence. TTS arrives in bursts 0.5–0.7 s apart within one turn (seen with `eleven_v3_conversational`), and the old 0.4 s `AVATAR_REPLY_GAP_S` split turns at those gaps. 1.0 is the default in the forwarder code (and `start_snow.sh` sets it too). The snow_call log has an `Avatar reply end: audio_s=… wall_s=… max_audio_gap_s=…` line per reply, and `Avatar frames` / `Avatar frame gap` lines for frame timing from the GPU. |
| After an interruption, the nurse picks up where she was cut off and finishes the old sentence | Old forwarder: it flushed only on `INTERRUPT_TTS_AUDIO`, which snow never sends on a barge-in (it sends `UTTERANCES_CANCELED`). The whole utterance was already on the GPU server. Fixed in snow commit `ac7f267e5b` (the forwarder flushes on every cancel of agent utterances), together with the GPU server's `flushed` reply. Check the snow log for `Avatar flush (barge-in)`. |
| `ssh`/`scp` to the pod fails with `…/bin/python: No such file or directory`, then `banner exchange: … Broken pipe` | Another session (for example a Cursor sandbox) ran `sky` and rewrote `~/.sky/generated/ssh/<cluster>` with its own temporary Python in `ProxyCommand`. Point the two paths (the interpreter and `sky/templates/websocket_proxy.py`) back at `/home/source_codes/skypilot-infra/.venv`. The tunnel watchdog and `scp` deploys fail silently until then. |
| Caption shows "Video paused (voice only)", or the video stays on the idle clip | The forwarder lost the GPU link and is retrying; the log shows `Avatar reconnect failed ... Connection refused`. Usually the tunnel died. Check `ss -ltn \| grep 8767` and `avatar_demo/ops/logs/gpu_tunnel.log`, and run the tunnel under `gpu_tunnel.sh` (step 3). Check the server job with `sky queue`. |
| 2-GPU server hangs or crashes with `illegal memory access` in NCCL | The bundled NCCL 2.26.2 was used. Check that the job log's `NCCL version` line says 2.27.3 and that `start_gpu_server.sh` set `LD_PRELOAD` (2+ GPUs). See the 2-GPU report. |
| 2-GPU import error: `update_npu_out` | xfuser 0.7.0 is installed; the config pins 0.4.3. |
| Pod setup fails at the very end: `xfuser has no attribute __version__` | Old config. It is fixed in both configs (uses `importlib.metadata`). Everything before that line succeeded, so just run `sky exec`. |
| `diffusers` import error: `Requires Flash-Attention version >=2.7.1,<=2.8.0` | Install flash-attn 2.7.4.post1, not 2.8.x. The configs install the release wheel URL directly, because the pod image has no nvcc. |

### Process gotchas

- **Don't use `pkill -f <pattern>` in a shell whose own command line contains the pattern.** It kills that shell (exit 144). This also applies inside `ssh host '...'`. Find PIDs with `ss -ltnp` or `ps -eo pid,cmd` and `kill <pid>`.
- **Kill the right process group.** A shell that only launched `setsid` can have its own group; check that the group contains `snow_call` before killing it.
- **The SSH tunnel and the Vite and snow processes run detached** (`setsid`/`ssh -f`). They keep running after the terminal closes. Redirect `ssh -f`'s output (`> /dev/null 2>&1 < /dev/null`), or the calling command waits on it.

## Known gaps and next steps

- **Network fixes don't persist.** The `col0` route and MTU are lost on the next Colima restart. Install the provision script in `network_and_frame_drops.md`, or redo step 0.
- **Snow start-up.** The Twilio lookups run even with `DISABLE_TWILIO=true`. Skipping them would cut start-up time on a bad network. This touches snow's telephony setup, so it needs a separate change.
- **Turn-taking timing.** Snow's playback acknowledgements track its own muted audio, delayed 2 s to match the avatar, so turn-taking is only approximately right.
- **Single session.** The GPU server handles one conversation at a time; a second client replaces the first.
- **2x RTX has no headroom.** It runs at about 1.0x real time, compared with 1.4x on the H200, so live idle rendering (`IDLE_TARGET_S`) is not an option, and replies start about 0.3 s later. A faster USP attention kernel (the yunchang flash path with `flash_attn`) is untested.
- **Quality check.** Compare the 2x RTX output (`TORCH_EFFICIENT`) by eye with the H200's SageAttention output.
