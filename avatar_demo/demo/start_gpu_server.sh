#!/usr/bin/env bash
# Start the FlashHead GPU server on the pod, in the foreground.
# Uses every visible GPU: 1 GPU runs plain python, 2+ GPUs run torchrun (sequence parallel).
# Env (defaults in brackets): MODEL_TYPE [pro], COND_IMAGE [avatar_demo/figures/nurse_image3.png],
#   GPU_SERVER_PORT [8766], NUM_GPUS [all visible], AVATAR_JPEG_QUALITY [70], GPU_SERVER_DEBUG [unset],
#   FAKE=1 for no model.
# Run from the FlashHead repo root (~/sky_workdir).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_TYPE="${MODEL_TYPE:-pro}"
COND_IMAGE="${COND_IMAGE:-$HERE/../figures/nurse_image3.png}"
PORT="${GPU_SERVER_PORT:-8766}"
NUM_GPUS="${NUM_GPUS:-$(nvidia-smi -L | wc -l)}"
ARGS=(--model_type "$MODEL_TYPE" --cond_image "$COND_IMAGE" --port "$PORT")
[ "${FAKE:-0}" = "1" ] && ARGS+=(--fake)

[ -f flash_head/inference.py ] || { echo "run from the FlashHead repo root" >&2; exit 1; }

if [ "$NUM_GPUS" -gt 1 ]; then
  # From the 2-GPU working config: preloaded NCCL 2.27.3, torch efficient attention (no flash_attn).
  export LD_PRELOAD=/root/nccl227/nvidia/nccl/lib/libnccl.so.2
  export FH_USP_ATTN="${FH_USP_ATTN:-TORCH_EFFICIENT}"
  export NCCL_MIN_NCHANNELS="${NCCL_MIN_NCHANNELS:-4}"
  echo "starting gpu_server on ${NUM_GPUS} GPUs (torchrun), port ${PORT}"
  exec torchrun --nproc_per_node="$NUM_GPUS" "$HERE/gpu_server.py" "${ARGS[@]}"
else
  echo "starting gpu_server on 1 GPU, port ${PORT}"
  exec python "$HERE/gpu_server.py" "${ARGS[@]}"
fi
