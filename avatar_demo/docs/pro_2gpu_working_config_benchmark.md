> Historical: the 2026-10-20 report that found the working 2x RTX Pro 6000 setup. Its config is now `avatar_demo/configs/skypilot_avatar_2gpu_rtxp6000_use15.yaml`.

# Pro 2-GPU: working configuration, optimizations, benchmarks

Date: 2026-10-21
Context: [pro_2gpu_nccl_crash.md](pro_2gpu_nccl_crash.md) (original crash report), [pro_2gpu_nccl_debug_status.md](pro_2gpu_nccl_debug_status.md) (debug log).

---

## 1. Current working configuration

### Hardware and cluster

- SkyPilot cluster `flashhead-debug`, `k8s/hai-cw-use15-cks`.
- 2x NVIDIA RTX PRO 6000 Blackwell Server Edition, driver 595.71.05.
- GPU0 and GPU1 are PIX-connected. Peer access 0→1 is True.
- Launch spec: `configs/skypilot_flashhead_debug_rtxp6000_use15.yaml`, started with `configs/launch_flashhead_debug.sh`.
- SkyPilot client: `~/source_codes/skypilot-infra/.venv/bin/sky` (0.12.3.post1, matches the server).

### Software on the pod

| Package | Version |
|---|---|
| Python | 3.10.12 (venv `/root/flashhead-venv`) |
| torch | 2.7.1+cu128 |
| torchvision | 0.22.1+cu128 |
| NCCL (bundled with torch) | 2.26.2 (not used at runtime; see below) |
| NCCL (preloaded at runtime) | 2.27.3+cuda12.9, from `/root/nccl227` |
| xfuser | 0.4.3 |
| yunchang | 0.6.4 |
| sageattention | 1.0.6 (installed; not used by the working run) |
| xformers | 0.0.31 |
| diffusers | 0.39.0 |
| transformers | 4.57.3 |
| triton | 3.3.1 |
| flash_attn | not installed |

Repo: SoulX-FlashHead at commit `9bc03de`, plus the uncommitted env-switch edits listed below.

### Runtime settings for the working run

Environment:

```bash
FH_USP_ATTN=TORCH_EFFICIENT
CUDA_VISIBLE_DEVICES=0,1
NCCL_MIN_NCHANNELS=4
NCCL_DEBUG=VERSION
LD_PRELOAD=/root/nccl227/nvidia/nccl/lib/libnccl.so.2
```

Command, run from `~/sky_workdir`:

```bash
torchrun --nproc_per_node=2 generate_video.py \
  --ckpt_dir models/SoulX-FlashHead-1_3B --wav2vec_dir models/wav2vec2-base-960h \
  --model_type pro --cond_image examples/girl.png \
  --audio_path examples/podcast_sichuan_16k.wav --audio_encode_mode stream
```

Submit with `--gpus RTXPRO-6000-BLACKWELL-SERVER-EDITION:2`. Without it, a `sky exec` job gets no GPUs.

Default feature flags (unchanged from the repo): `COMPILE_MODEL=1`, `COMPILE_VAE=1`, `USE_PARALLEL_VAE=1`.

### Repo changes

Uncommitted, in `/home/source_codes/SoulX-FlashHead`:

- `flash_head/src/pipeline/flash_head_pipeline.py`: `FH_COMPILE_MODEL`, `FH_COMPILE_VAE`, `FH_PARALLEL_VAE` env switches (default `1`).
- `flash_head/src/modules/flash_head_model.py`: `FH_USP_ATTN` env switch, plus `import os`.

`git diff` also shows `flash_head_model.py` mode changed from `100755` to `100644`. This was not from my edits, and I have not reverted it.

### What is not yet reproducible from the YAML

The working run depends on steps done by hand on the pod. These are not yet in the SkyPilot YAML:

1. `pip install xfuser==0.4.3` (the YAML installs 0.7.0 from `requirements.txt`, which fails).
2. `pip install --no-deps --target /root/nccl227 nvidia-nccl-cu12==2.27.3`, plus the `LD_PRELOAD` in the run command.
3. `examples/` copied with `scp`. SkyPilot's workdir sync skipped it.

---

## 2. Optimizations done

These changes made the 2-GPU run work. None of them is a speed optimization. Speed has not been measured against the alternatives.

| # | Change | Why | Effect |
|---|---|---|---|
| 1 | NCCL 2.27.3 preloaded (`LD_PRELOAD`) instead of bundled 2.26.2 | Bundled version hangs on default transport and crashes with `illegal memory access` when P2P is off | Fixes the crash for both the bare NCCL test and FlashHead |
| 2 | `xfuser==0.4.3` instead of 0.7.0 | 0.7.0 imports `update_npu_out`, which yunchang 0.6.4 does not provide | Fixes the import error |
| 3 | `FH_USP_ATTN=TORCH_EFFICIENT` | `flash_attn` is not installed, so yunchang's default flash path fails in `ring_flash_attn` | Run completes. Speed compared to other kernels is unmeasured |
| 4 | `FH_*` env switches for compile, parallel VAE, and attention | Needed to bisect the crash and to test speed options without code edits | No effect on the default path. Not yet used for a timing comparison |
| 5 | `NCCL_MIN_NCHANNELS=4` (carried over from the original report) | Setting from the original run command | Not isolated. Effect unknown |

---

## 3. Benchmark results

### 3a. NCCL soak test (`nccl_soak.py`, no FlashHead code)

Two GPUs, bf16 tensors of `[4096, 1536]`, loop of all_reduce + all_gather + all_to_all_single.

| Setting | NCCL 2.26.2 | NCCL 2.27.3 |
|---|---|---|
| Default transport, 10,000 iters | Hangs at first collective (90 s timeout, no `iter 0`) | **PASS**, 10,000 iters |
| `NCCL_P2P_DISABLE=1`, 500 iters | `illegal memory access` on iter 0 | not run |
| `NCCL_SHM_DISABLE=0 NCCL_P2P_DISABLE=1`, 500 iters | `illegal memory access` on iter 0 | not run |

The soak script's final `PASS` line prints `torch.cuda.nccl.version()`, which reports the bundled 2.26.2 even when 2.27.3 is preloaded. The version actually loaded is shown by the `NCCL version` line in the log.

### 3b. Per-collective test (P2P disabled, 200 iters each)

| Collective | NCCL 2.26.2 | NCCL 2.27.3 |
|---|---|---|
| broadcast | `illegal memory access` | PASS |
| allreduce | `illegal memory access` | PASS |
| alltoall | `illegal memory access` | PASS |
| allgather | `illegal memory access` | not run |

### 3c. FlashHead Pro, 2 GPUs

| Run | xfuser | Attention | NCCL | Outcome |
|---|---|---|---|---|
| A | 0.7.0 | default | 2.27.3 | `ImportError: update_npu_out` |
| B | 0.4.3 | default | 2.27.3 | `ValueError: not enough values to unpack` in `ring_flash_attn` |
| **C (working)** | **0.4.3** | **TORCH_EFFICIENT** | **2.27.3** | **Completed, `rc=0`, 59 chunks, 66 s video** |

Timing for run C, from `/root/fh_eff.log`:

| Phase | Time |
|---|---|
| Data preparation done | 19:38:47 |
| `chunk-0` (includes `torch.compile` warmup) | 79.6 s |
| `chunk-1` to `chunk-58` (58 chunks), per chunk | ~1.135 s |
| Chunks 1–58, total | ~66 s |
| Video saved | 19:41:17 (150 s from data prep to save) |

Derived numbers:
- Steady state: about 1.135 s per chunk. If each chunk is 28 frames (assumed from the report, not checked in the code), that is about 24.7 fps, roughly real-time.
- Real-time factor after warmup: 66 s of video in about 66 s of compute.
- Warmup overhead: about 80 s before the first chunk.

Output: `outputs/fh_pro_2gpu_nccl227_torch_efficient.mp4`, 512x512, 25 fps, 66 s, 3.9 MB.

### 3d. Baseline (not measured here)

- The original report gives 1-GPU Pro at about 1.55 s per 28-frame chunk (about 18 fps). That was measured on a different machine and is not a like-for-like comparison.
- A 1-GPU run on this pod has not been done.

### What is not benchmarked

- Repeat runs. Only one successful 2-GPU run.
- Output quality. The 2-GPU video has not been compared frame-by-frame with 1-GPU output.
- Per-stage timing (DiT, VAE encode/decode, audio encoder, NCCL). No breakdown yet.
- Speed of each attention kernel (`TORCH_EFFICIENT` vs SAGE vs others).

---

## 4. Optimizations to explore

Ordered by expected payoff for the demo. Expected effects are estimates, not measurements.

1. **Remove the ~80 s warmup from the live path.** Keep one process alive and pre-warm the compile before the call starts, or serve from a long-lived worker. This is the largest latency item for the demo. Measure: time to first frame, with and without a warm process.
2. **Per-stage timing breakdown.** Add timers around the DiT forward, VAE encode and decode, the audio encoder, and the all-gather. This is needed before choosing among the items below. Measure: ms per chunk per stage.
3. **Better attention kernel.** Test SAGE (`SAGE_AUTO` path) and flash-attn builds with sm_120 support against `TORCH_EFFICIENT`. Sage 2 and flash-attn need nvcc, which the pod lacks, so this needs a CUDA-devel image. Measure: steady-state ms per chunk and output match against TORCH_EFFICIENT.
4. **Parallel VAE on/off.** Run with `FH_PARALLEL_VAE=0` and compare. The VAE communicates across GPUs, so it may cost more than it saves on 2 GPUs. Measure: ms per chunk.
5. **VAE and DiT compile on/off.** Run `FH_COMPILE_VAE=0` and `FH_COMPILE_MODEL=0`. Compile adds the warmup cost, so the question is whether steady-state speed differs enough to justify it. Measure: warmup time and steady-state ms per chunk.
6. **NCCL tuning.** Vary `NCCL_MIN_NCHANNELS` and check the transport in the NCCL log. The TTS launcher found SHM and P2P settings matter on these pods, so test `NCCL_SHM_DISABLE=0` with P2P on and off. Measure: ms per chunk.
7. **Batch or stream granularity.** Check whether larger chunks (more frames per call) increase throughput at the cost of latency. Relevant to the lag budget in the demo. Measure: frames per second and latency per chunk.
8. **1-GPU Lite as a fallback.** The README reports 96 FPS for Lite on one RTX 4090, and Lite on 1 GPU may meet real-time without the NCCL and xfuser risk. Measure: FPS and visual quality on this pod, against 2-GPU Pro.

### Immediate next steps

1. Record a 1-GPU Pro baseline on this pod (same audio and image) for FPS.
2. Repeat run C twice to check repeatability.
3. Move the three manual steps (xfuser pin, NCCL preload, examples copy) into the YAML setup so the config is reproducible.
4. Tear down `flashhead-debug` when finished. It bills while up.
