#!/usr/bin/env bash
# Benchmark FlashHead's single-GPU attention kernels on the pod (Pro, nurse image, 20 s of audio).
# For each kernel that imports: run generate_video.py in stream mode with FH_ATTN=<kernel>, then
# report warmup (chunk 0), steady-state seconds per 28-frame chunk (chunks 2+), fps, and the mean
# absolute pixel difference of the output against SDPA.
#
# Run from the FlashHead repo root (~/sky_workdir) with /opt/venv active:
#   bash avatar_demo/demo/bench_attention.sh [KERNELS...]     # default: SDPA SAGE FA2 FA3
set -uo pipefail

KERNELS=("${@:-SDPA SAGE FA2 FA3}")
read -r -a KERNELS <<< "${KERNELS[*]}"
OUT=/scratch/bench_attention
COND_IMAGE="${COND_IMAGE:-avatar_demo/figures/nurse_image3.png}"
mkdir -p "$OUT"
ffmpeg -loglevel error -y -i examples/podcast_sichuan_16k.wav -t 20 -ar 16000 -ac 1 "$OUT/audio20.wav"

available() {
  case "$1" in
    SDPA) return 0 ;;
    SAGE) python -c "from sageattention import sageattn" 2>/dev/null ;;
    FA2) python -c "import flash_attn" 2>/dev/null ;;
    FA3) python -c "import flash_attn_interface" 2>/dev/null ;;
  esac
}

for k in "${KERNELS[@]}"; do
  if ! available "$k"; then
    echo "== $k: not installed, skipped"
    continue
  fi
  echo "== $k: running"
  FH_ATTN="$k" python generate_video.py --ckpt_dir models/SoulX-FlashHead-1_3B \
    --wav2vec_dir models/wav2vec2-base-960h --model_type pro --cond_image "$COND_IMAGE" \
    --audio_path "$OUT/audio20.wav" --audio_encode_mode stream --save_file "$OUT/$k.mp4" \
    > "$OUT/$k.log" 2>&1 || { echo "== $k: FAILED"; tail -5 "$OUT/$k.log"; continue; }
done

python - "$OUT" "${KERNELS[@]}" <<'EOF'
import os, re, sys
import numpy as np
out, kernels = sys.argv[1], sys.argv[2:]

def frames(path):
    import imageio.v3 as iio
    return np.stack([f.astype(np.float32) for f in iio.imiter(path)])

ref = frames(f"{out}/SDPA.mp4") if os.path.exists(f"{out}/SDPA.mp4") else None
print(f"{'kernel':6} {'warmup_s':>9} {'s/chunk':>8} {'fps':>6} {'diff_vs_SDPA':>13}")
for k in kernels:
    log = f"{out}/{k}.log"
    if not os.path.exists(log) or not os.path.exists(f"{out}/{k}.mp4"):
        continue
    t = [float(x) for x in re.findall(r"chunk-\d+ done, cost time: ([0-9.]+)s", open(log).read())]
    if len(t) < 3:
        continue
    steady = float(np.mean(t[2:]))
    diff = ""
    if ref is not None:
        f = frames(f"{out}/{k}.mp4")
        n = min(len(f), len(ref))
        diff = f"{np.abs(f[:n] - ref[:n]).mean():.2f}"
    print(f"{k:6} {t[0]:9.1f} {steady:8.3f} {28 / steady:6.1f} {diff:>13}")
EOF
