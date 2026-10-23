"""Preview the overlay nod on rendered frames (e.g. prototype_listening.py's baseline).

  python avatar_demo/demo/prototype_nod_preview.py --src /tmp/proto_listen/baseline --out /tmp/nod_preview
Writes <out>/%05d.jpg: left half the original, right half with nods at --at seconds.
"""

import argparse
import glob
import os

import cv2
import numpy as np

from listening import NOD_S, NodWarp, nod_curve


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/tmp/proto_listen/baseline")
    ap.add_argument("--out", default="/tmp/nod_preview")
    ap.add_argument("--at", default="3.0,6.0,9.0")
    ap.add_argument("--px", type=float, default=5.0)
    args = ap.parse_args()
    starts = [float(t) for t in args.at.split(",")]
    warp = NodWarp(px=args.px)
    os.makedirs(args.out, exist_ok=True)
    for k, path in enumerate(sorted(glob.glob(os.path.join(args.src, "*.jpg")))):
        frame = cv2.imread(path)
        t = k / 25.0
        amount = max((nod_curve(t - s) for s in starts), default=0.0)
        both = np.concatenate([frame, warp.apply(frame, amount)], axis=1)
        cv2.putText(both, "original", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(both, f"overlay nod {args.px:g}px", (520, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.imwrite(os.path.join(args.out, f"{k:05d}.jpg"), both, [cv2.IMWRITE_JPEG_QUALITY, 90])
    print("nod length", NOD_S, "s; frames", k + 1)


if __name__ == "__main__":
    main()
