> Historical: the original plan from 2026-10-21. For the current setup see `runbook.md`; open work is in `TODO.md`.

# Plan: nurse avatar video call on top of snow

Goal: from the local Mac, video-call a nurse avatar. Snow handles VAD, ASR, the agent and TTS (Rebecka voice). SoulX-FlashHead Pro runs on 2 RTX Pro 6000 GPUs and lip-syncs `nurse_image3.png` to snow's TTS audio.

**Status 2026-10-22:** phases 1–4 are done, and phase 5 is mostly done (`runbook.md`). The demo runs on 1x H200 instead of 2 RTX Pro 6000s, which had no capacity. The main risk turned out to be the devbox network, not the avatar. It is now fixed; see `network_and_frame_drops.md`.

## Architecture

```
Mac browser (demo_portal /dev/call, VOIP mode + new avatar panel)
  | mic -> socket.io "humanvoice" ---------------------> snow_call :3000 (VAD -> ASR -> agent -> TTS)
  |                                                          | VOICE_STREAM_OUTGOING (pubsub tap)
  |                                                          v
  |                                                 avatar forwarder (inside snow_call)
  |                                                 resample 44.1k -> 16k, utterance start/end, cancel -> flush
  |                                                          v
  | <- WS video+audio frames ---- bridge.py :8765 (container) <-> SSH tunnel <-> gpu_server.py :8766 (pod, 2 GPUs)
  |                                                  frames = JPEG + 640 PCM samples @ 25 fps
  idle nurse clip loops whenever no frames are arriving
```

Key choices:
- **Snow is the source of truth for speech.** The forwarder subscribes to `SnowMessageTopics.VOICE_STREAM_OUTGOING` (`audio/snow_voice_core_main.py:~783`, `common/messages.py:569`). It keeps only `sender == VOICE_CORE`, so hold music and DTMF are dropped. No new TTS or ASR code.
- **Lip-sync comes from playing the audio that travels with the frames.** The avatar page mutes snow's own `machinevoice` playback and plays the PCM embedded in each frame. The browser still acks `machinevoicestart` and `utterances_chunk_finalized`, so snow's turn-taking keeps working.
- **Barge-in:** on `UTTERANCES_CANCELED` / `interrupt_tts_audio`, the forwarder sends `flush` to the GPU server, and the client drops its buffer and goes back to the idle clip.
- **Gap filling:** between replies and before the first frame, the client loops a pre-rendered idle or nod clip of the nurse. A still image is the fallback. The clip is rendered offline once with FlashHead from silence or soft breathing audio.
- **Voice:** ElevenLabs voice `pMGVep9K6NsbHTohrjzi` ("Rebecka v2", already cloned from `rebecka_conv_ref_short_norm.wav`), set through `ELEVEN_LABS_VOICE_ID`. Snow asks for `pcm_44100` on web sessions.

## What to reuse from `20261020_soulX-FlashHead/demo/`

| File | Reuse |
|---|---|
| `audio_chunker.py`, `playback_buffer.py`, `wire.py`, `avatar_engine.py` + tests | As is |
| `gpu_server.py` | Extend to 2 GPUs: run under torchrun; rank 0 serves the WebSocket and broadcasts each chunk with `dist.broadcast`; both ranks call `run_pipeline`. Keep `--fake`. |
| `bridge.py` | Base for the Mac-facing WS on :8765. It now takes audio from the snow forwarder instead of `tts_to_server.py`. |
| `client.html` | Port its video, audio-sync and idle-clip logic into a demo_portal avatar panel, or keep it as a page the panel embeds. |
| `test_client.py` | End-to-end smoke test against the GPU server |
| `tts_to_server.py`, `token_server.py`, `scribe_test.py`, `relay.py` | Superseded, because snow now does TTS and ASR. Keep them for debugging only. |

## Phases

### Phase 0: prerequisites (blockers found)

| Item | Status |
|---|---|
| `snow/.env` | **Missing.** It normally comes from 1Password (`op read ...`), and `op` is not installed in the container. You need to supply it, or an `OP_SERVICE_ACCOUNT_TOKEN`. |
| `snow/demo_portal/.env` | Missing. Copy it from `.env.example`. |
| `docker` | **Not in the container.** Postgres (pgvector pg15) and Redis need another home (see question 1). |
| `npm`, `psql`, `ngrok`, `tailscale`, `op` | Not found on PATH. `uv` is present. |
| Shell exports | Not set: `SNOW_HOME`, `IGLOO_HOME`, `HAI_EMAIL`, `HAI_GIVEN_NAME`, `HAI_FAMILY_NAME`, `HAI_SUB_UUID`, `SNOW_DATABASE_NAME/USER`. `HAI_SUB_UUID` comes from snow.hippocraticdev.com/admin/users. |
| API keys snow needs for this demo | `DEEPGRAM_API_KEY` (only if we switch ASR to Deepgram), `ELEVEN_LABS_API_KEY` (in `~/.bashrc`; snow's `.env` needs it too), LLM keys (`LLM_MODEL_API_KEY` / `ANTHROPIC_API_KEY` / `OPEN_AI_API_KEY`), `APP_SECRET_KEY`, `HAI_JWT_TOKEN_SECRETS`, `AUTH0_*`. I'll run `tools/validate_env.py` once `.env` exists. |
| Tailscale | Not needed in the container: traffic already goes through the Mac's Tailscale. Checked 2026-10-21: `api.model.hippocraticai.com`, `deepgram.staging.hippocraticdev.com` and `100.100.100.100` all answer. `emotivox.dev.hippocraticdev.com` and `dg-e1.hippocraticdev.com` don't resolve here; if either is needed, run `dig` on the Mac and add an `/etc/hosts` entry. |
| Nurse image | It lives in `20261020_.../figures/nurse_image3.png` (958x636), not in the 20261021 folder. Copy it over. |
| SkyPilot | RESUME.md says the FlashHead cluster's workspace is only visible to `uvx --from "skypilot==0.12.3.post1" sky`, not to `skypilot-infra/.venv`. Confirm which one to use. |

### Phase 1: local snow up (VOIP voice only, no avatar)
1. Install the Linux equivalents of the brew packages: npm/node, postgresql-client-15, portaudio, ffmpeg, git-lfs. Run `git lfs pull` in snow and igloo.
2. Start Postgres and Redis (where depends on question 1), then `make db-create-local-db`, then `make alembic-upgrade db-insert-self-as-superadmin db-enable-sso`.
3. `make all`, then `make run-all-services`. That starts snow_call :3000, snow_web :4000 and demo_portal :5173.
4. Forward ports 5173, 3000 and 4000 from the container to the Mac (`localhost` on the Mac must match for Okta SSO). Log in through the Okta app "Hippocratic AI Dev - Localhost".
5. Skip ngrok: browser VOIP calls don't need it.
6. Pick a nurse scenario or patient in igloo and set the Rebecka voice ID.
7. **Exit check:** a VOIP call at `localhost:5173/dev/call` from the Mac works by voice.

### Phase 2: GPU server on 2 GPUs
1. Bring up the RTX Pro 6000 x2 cluster from `configs/skypilot_flashhead_debug_rtxp6000_use15.yaml`.
2. Fold the manual pod steps into the YAML: xfuser 0.4.3, NCCL 2.27.3 + `LD_PRELOAD`, copy `examples/` and `ltx_video/models`.
3. Make `gpu_server.py` run on 2 ranks, warm up at startup (about 80 s compile), and call `reset_person_name()` on each session.
4. Use `nurse_image3.png` as the cond image.
5. **Exit check:** `test_client.py` through the SSH tunnel shows about 25 fps steady and a measured first-frame latency (target under 2 s after warmup).
6. If the 2 GPUs don't hold up, fall back to the proven 1-GPU setup with prebuffer ≈ 0.4 × reply length.

### Phase 3: snow → avatar forwarder
1. Add a small module in snow, e.g. `devtools/avatar_forwarder.py`. Enable it with `AVATAR_GPU_WS_URL` and start it with the call session in snow_call.
2. It subscribes to `VOICE_STREAM_OUTGOING`, decodes the L16 44.1k chunks, resamples them to 16 kHz, and streams them to the bridge/GPU server tagged with `call_id` and `utterance_ids`.
3. It maps `is_first`/`is_final` to reply start/end, and maps cancel to `flush`.
4. **Exit check:** during a VOIP call, the GPU server log shows renders for every agent utterance.

### Phase 4: Mac avatar client
1. Add an avatar panel to the demo_portal call page: a `<video>` or canvas, an "avatar mode" toggle that mutes `machinevoice` audio, a WS to the bridge, synced A/V playback, the idle clip loop, and flush on interrupt.
2. As an alternative, iterate on `client.html` first and embed it later.
3. **Exit check:** a full conversation with the avatar talking in sync, idle between turns, and interrupts working.

### Phase 5: tune, runbook, review
1. Measure each stage: ASR endpointing, agent turn, TTS first byte, render, network. Tune the prebuffer against the idle-clip handoff.
2. Write `runbook.md`: cluster up, tunnel, services, URLs, and `sky down`.
3. Review the quality of a full conversation.

## Decisions (2026-10-21)
1. Postgres 15 + pgvector and Redis run natively in the container. No docker.
2. You will copy `snow/.env` into place. I will validate it with `tools/validate_env.py` and report any missing keys.
3. The avatar UI goes into demo_portal as a panel on `/dev/call`.
