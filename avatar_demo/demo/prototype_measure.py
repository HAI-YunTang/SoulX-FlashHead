"""Measure prototype_listening.py variants against the baseline: head motion (the nod) and mouth change.

Frames match the reference (--ref, default floor_only: same seed, start pose and noise floor) exactly
until the first backchannel chunk, so any difference is caused by the backchannel. Per variant, over each nod window:
  dy_max  vertical head shift vs the baseline frame (phase correlation on the head region), px
  dx_max  horizontal head shift (a nod should be mostly vertical), px
  mouth   mean abs pixel difference in the mouth region vs the baseline (mumbling risk), 0-255
  idle    the same mouth measure before the first nod (should be ~0: sanity check)

  python avatar_demo/demo/prototype_measure.py --src /tmp/proto_listen
"""

import argparse
import os

import cv2
import numpy as np

HEAD = (slice(110, 320), slice(150, 310))  # 512x512 frame, nurse_image3
MOUTH = (slice(252, 290), slice(195, 260))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/tmp/proto_listen")
    ap.add_argument("--nod_chunks", default="5,9")
    ap.add_argument("--ref", default="floor_only", help="variant with the same idle conditioning, no nods")
    args = ap.parse_args()
    nods = [int(c) for c in args.nod_chunks.split(",")]

    def load(v, k):
        return cv2.imread(f"{args.src}/{v}/{k:05d}.jpg", cv2.IMREAD_GRAYSCALE).astype(np.float32)

    hann = np.outer(np.hanning(210), np.hanning(160)).astype(np.float32)
    print(f"{'variant':14s} " + " ".join(f"{'nod%d dy' % (i + 1):>8s}" for i in range(len(nods)))
          + f" {'dx_max':>7s} {'mouth':>6s} {'idle':>6s}")
    for v in sorted(os.listdir(args.src)):
        if v in ("baseline", args.ref):
            continue
        dys, dxs, mouth = [], [], []
        for c in nods:
            best = 0.0
            for k in range(c * 28 - 5, min(c * 28 + 45, 308)):
                a, b = load(args.ref, k), load(v, k)
                (dx, dy), _ = cv2.phaseCorrelate(a[HEAD] * hann, b[HEAD] * hann)
                best = max(best, abs(dy))
                dxs.append(abs(dx))
                mouth.append(np.abs(a[MOUTH] - b[MOUTH]).mean())
            dys.append(best)
        idle = max(np.abs(load(args.ref, k)[MOUTH] - load(v, k)[MOUTH]).mean() for k in range(60, 110))
        print(f"{v:14s} " + " ".join(f"{d:8.2f}" for d in dys) + f" {max(dxs):7.2f} {max(mouth):6.2f} {idle:6.2f}")


if __name__ == "__main__":
    main()
