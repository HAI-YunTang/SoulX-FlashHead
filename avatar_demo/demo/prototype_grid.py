"""Compose prototype_listening.py output into a labelled grid (frames) and a contact sheet.

  python avatar_demo/demo/prototype_grid.py --src /tmp/proto_listen --out /tmp/proto_grid
Writes <out>/grid/%05d.jpg (all variants side by side, 256 px each, labelled) and
<out>/contact.jpg (each variant's frames around the nod chunks, one row per variant).
"""

import argparse
import glob
import os

import cv2
import numpy as np

FPS = 25


def label(img, text):
    cv2.rectangle(img, (0, 0), (img.shape[1], 22), (0, 0, 0), -1)
    cv2.putText(img, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/tmp/proto_listen")
    ap.add_argument("--out", default="/tmp/proto_grid")
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--nod_chunks", default="5,9")
    ap.add_argument("--chunk_frames", type=int, default=28)
    args = ap.parse_args()

    variants = sorted(os.listdir(args.src), key=lambda v: (v not in ("baseline", "floor_only"), v))
    frames = {v: sorted(glob.glob(os.path.join(args.src, v, "*.jpg"))) for v in variants}
    n = min(len(f) for f in frames.values())
    os.makedirs(os.path.join(args.out, "grid"), exist_ok=True)
    rows = (len(variants) + args.cols - 1) // args.cols
    s = args.size
    for k in range(n):
        canvas = np.zeros((rows * s, args.cols * s, 3), dtype=np.uint8)
        for i, v in enumerate(variants):
            tile = cv2.resize(cv2.imread(frames[v][k]), (s, s), interpolation=cv2.INTER_AREA)
            r, c = divmod(i, args.cols)
            canvas[r * s:(r + 1) * s, c * s:(c + 1) * s] = label(tile, f"{v}  {k / FPS:4.1f}s")
        cv2.imwrite(os.path.join(args.out, "grid", f"{k:05d}.jpg"), canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])

    # contact sheet: per variant, frames 0.0-1.4 s after each nod chunk starts, every 0.2 s
    picks = []
    for c in (int(x) for x in args.nod_chunks.split(",")):
        start = c * args.chunk_frames
        picks += [start + int(t * FPS) for t in np.arange(0.0, 1.41, 0.2)]
    picks = [p for p in picks if p < n]
    t = 160
    sheet = np.zeros((len(variants) * t, len(picks) * t, 3), dtype=np.uint8)
    for i, v in enumerate(variants):
        for j, p in enumerate(picks):
            tile = cv2.resize(cv2.imread(frames[v][p]), (t, t), interpolation=cv2.INTER_AREA)
            if j == 0:
                tile = label(tile, v[:18])
            sheet[i * t:(i + 1) * t, j * t:(j + 1) * t] = tile
    cv2.imwrite(os.path.join(args.out, "contact.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(f"{len(variants)} variants, {n} frames; contact sheet frames {picks}")


if __name__ == "__main__":
    main()
