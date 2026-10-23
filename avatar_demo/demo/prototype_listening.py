"""Prototype for active listening: render the nurse "listening" with silent backchannel chunks.

For each variant, renders ~12 s from the reference pose with the same noise seed, so frames match the
baseline exactly until the backchannel chunk. The idle chunks are silence (optionally over a noise floor);
at chunk indices --nod_chunks the conditioning audio is a backchannel clip ("mm-hmm" in the nurse's
voice). The clip only drives the motion; when this goes live the patient hears silence.

Run on the pod from the repo root (~/sky_workdir), with no call active (it loads a second model copy):
  python avatar_demo/demo/prototype_listening.py --out /tmp/proto_listen
Writes <out>/<variant>/%05d.jpg per variant.
"""

import argparse
import glob
import os
import sys
import time
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

HERE = os.path.dirname(os.path.abspath(__file__))
CLIPS = os.path.join(HERE, "..", "data", "backchannel")  # short backchannels from ElevenLabs, Stacy voice


def load_clip(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0


def conditioning_chunk(n: int, floor_db, clip=None, level: float = 1.0, rng=None) -> np.ndarray:
    """One chunk of conditioning audio: silence or a noise floor, with a clip at the start if given."""
    if floor_db is None:
        x = np.zeros(n, dtype=np.float32)
    else:
        x = (rng.standard_normal(n) * 10 ** (floor_db / 20)).astype(np.float32)
    if clip is not None:
        m = min(len(clip), n)
        x[:m] += clip[:m] * level
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/proto_listen")
    ap.add_argument("--chunks", type=int, default=11)  # 11 x 1.12 s = 12.3 s
    ap.add_argument("--nod_chunks", default="5,9")  # nods at ~5.6 s and ~10.1 s
    ap.add_argument("--levels", default="1.0,0.3")
    ap.add_argument("--floor_db", type=float, default=-50.0, help="noise floor in dBFS; nan = pure silence")
    ap.add_argument("--clips", default="", help="comma-separated clip names to try (default: all)")
    ap.add_argument("--no_refs", action="store_true", help="skip the baseline and floor_only references")
    ap.add_argument("--quality", type=int, default=90)
    args = ap.parse_args()

    import cv2
    from gpu_server import build_model  # noqa: E402

    engine, chunker, reset_model, _link = build_model(
        argparse.Namespace(model_type="pro", cond_image=os.path.join(HERE, "..", "figures", "nurse_image3.png")),
        world_size=1,
    )
    pipe = reset_model.__self__  # reset_model is the pipeline's bound reset_person_name
    n = chunker.chunk_samples
    nod_at = {int(i) for i in args.nod_chunks.split(",")}
    clips = {os.path.splitext(os.path.basename(p))[0]: load_clip(p) for p in sorted(glob.glob(f"{CLIPS}/*.wav"))}

    floor = None if np.isnan(args.floor_db) else args.floor_db
    variants = [] if args.no_refs else [("baseline", None, None, 1.0), ("floor_only", floor, None, 1.0)]
    for name in clips:
        if args.clips and name not in args.clips.split(","):
            continue
        for lv in (float(v) for v in args.levels.split(",")):
            tag = "nofloor" if floor is None else f"lv{lv:g}"
            variants.append((f"{name}_{tag}", floor, name, lv))

    for vname, floor_db, clip_name, level in variants:
        engine.reset()
        reset_model()
        pipe.generator.manual_seed(42)  # same noise per variant: frames match until the nod chunk
        rng = np.random.default_rng(0)
        out_dir = os.path.join(args.out, vname)
        os.makedirs(out_dir, exist_ok=True)
        t0, k = time.time(), 0
        for i in range(args.chunks):
            clip = clips[clip_name] if (clip_name and i in nod_at) else None
            chunk = conditioning_chunk(n, floor_db, clip, level, rng)
            for frame in engine.render_chunk(chunk, speech=False)["frames"]:
                cv2.imwrite(os.path.join(out_dir, f"{k:05d}.jpg"), np.ascontiguousarray(frame[..., ::-1]),
                            [cv2.IMWRITE_JPEG_QUALITY, args.quality])
                k += 1
        print(f"{vname}: {k} frames in {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
