"""Active listening: the nurse nods while the patient talks a lot.

FlashHead has no pose input, and silent backchannel audio ("mm-hmm") moves her head under 1 px
(prototype_measure.py), so nods are a 2D overlay: the head region of each outgoing frame is warped
along a smooth nod curve when the frame is sent. The model, its motion state and the audio are untouched.

NodScheduler decides when (pure logic, clock injected so it is testable):
  - it counts the patient's speech time in the current turn; no nod before NOD_AFTER_S (short answers
    such as "yes" or a date of birth get none);
  - after that: a nod at the patient's pauses, and every NOD_INTERVAL_S (random in a range) otherwise;
  - at least MIN_GAP_S between nods; none while the nurse speaks or right after a barge-in flush;
  - the turn's counter resets when the nurse starts speaking, or after a long silence.
"""

import random

import numpy as np

NOD_S = 0.7  # one nod: down in ~40% of it, back up in the rest


def nod_curve(t: float, duration: float = NOD_S) -> float:
    """0 -> 1 -> 0 over `duration`, eased; 0 outside."""
    if t <= 0.0 or t >= duration:
        return 0.0
    down = 0.4 * duration
    if t < down:
        u = t / down
    else:
        u = 1.0 - (t - down) / (duration - down)
    return float(u * u * (3 - 2 * u))  # smoothstep


class NodWarp:
    """Moves the head region of a frame down by `px * amount` pixels, with a soft elliptical mask so the
    shoulders and background stay put. The defaults fit figures/nurse_image3.png at 512 px: the face
    (forehead y~110 to chin y~310) sits in the mask's full-strength core and the neck takes the stretch. The top of the head moves a little more than the chin, so the face
    shortens slightly the way it does when the head pitches forward."""

    def __init__(self, size: int = 512, center=(230, 210), radii=(150, 190), px: float = 5.0):
        h = w = size
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        cx, cy = center
        rx, ry = radii
        r = np.sqrt(((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2)
        u = np.clip((1.0 - r) / 0.45, 0.0, 1.0)  # 1 inside r < 0.55, fading to 0 at the ellipse edge
        mask = u * u * (3 - 2 * u)
        tilt = 1.0 + 0.15 * np.clip((cy - ys) / ry, -1.0, 1.0)  # forehead ~1.1x, chin ~0.9x
        self.dy_unit = (mask * tilt * px).astype(np.float32)  # displacement at amount = 1
        self.xs, self.ys = xs, ys
        self.px = px

    def apply(self, frame: np.ndarray, amount: float) -> np.ndarray:
        if amount <= 0.0:
            return frame
        import cv2

        map_y = self.ys - self.dy_unit * amount  # sample from above: content moves down
        return cv2.remap(frame, self.xs, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


class NodScheduler:
    def __init__(self, after_s: float = 5.0, interval_s=(5.0, 8.0), min_gap_s: float = 3.0,
                 reset_silence_s: float = 4.0, flush_quiet_s: float = 2.0, rng=None):
        self.after_s = after_s
        self.interval_s = interval_s
        self.min_gap_s = min_gap_s
        self.reset_silence_s = reset_silence_s
        self.flush_quiet_s = flush_quiet_s
        self.rng = rng or random.Random()
        self.listening = False
        self.agent_speaking = False
        self.speech_s = 0.0  # patient speech in this turn
        self.last_t = None
        self.silent_since = None
        self.last_nod_t = -1e9
        self.quiet_until = -1e9
        self.pause_pending = False
        self.gate_open_t = None  # when this turn's speech first passed after_s
        self.next_interval = self._draw()
        self.nod_start = None  # set while a nod plays

    def _draw(self) -> float:
        return self.rng.uniform(*self.interval_s)

    def _reset_turn(self) -> None:
        self.speech_s = 0.0
        self.pause_pending = False
        self.gate_open_t = None

    def _gate_open(self) -> bool:
        return self.speech_s >= self.after_s

    # --- events (from the forwarder, via the GPU server's client messages) ---
    def set_listening(self, on: bool, now: float) -> None:
        self._advance(now)
        if on and not self.listening:
            self.silent_since = None
        if not on and self.listening:
            self.silent_since = now
            # the patient stopped (the forwarder waits ~0.8 s of silence for this); pauses only count
            # once the patient has talked a lot
            self.pause_pending = self._gate_open()
        self.listening = on

    def pause(self, now: float) -> None:
        self._advance(now)
        if self.listening and self._gate_open():
            self.pause_pending = True

    def set_agent_speaking(self, on: bool, now: float) -> None:
        self._advance(now)
        self.agent_speaking = on
        if on:
            self._reset_turn()  # the nurse replies: a new patient turn comes next (a nod in progress finishes)

    def flush(self, now: float) -> None:
        self._advance(now)
        self.quiet_until = now + self.flush_quiet_s
        self.nod_start = None

    # --- per sent frame ---
    def _advance(self, now: float) -> None:
        # Not while the nurse speaks: VAD also hears her voice echoing into the patient's mic, which would
        # open the gate before the patient has said anything.
        if self.last_t is not None and self.listening and not self.agent_speaking:
            self.speech_s += max(0.0, now - self.last_t)
            if self.gate_open_t is None and self._gate_open():
                self.gate_open_t = now
        self.last_t = now
        if not self.listening and self.silent_since is not None and now - self.silent_since > self.reset_silence_s:
            self._reset_turn()
            self.silent_since = None

    def amount(self, now: float, allow_start: bool = True) -> float:
        """Nod amount 0..1 for the frame sent at `now`. A nod in progress always finishes (cutting it off
        would snap the head back); a new one starts only when due and `allow_start` (not on frames that
        carry the nurse's voice)."""
        self._advance(now)
        if self.nod_start is not None:
            a = nod_curve(now - self.nod_start)
            if now - self.nod_start >= NOD_S:
                self.nod_start = None
            return a
        if allow_start and self._due(now):
            self.nod_start = now
            self.last_nod_t = now
            self.pause_pending = False
            self.next_interval = self._draw()
            return 0.0
        return 0.0

    def _due(self, now: float) -> bool:
        if self.agent_speaking or now < self.quiet_until or not self._gate_open():
            return False
        if now - self.last_nod_t < self.min_gap_s:
            return False
        if self.pause_pending:
            return True
        since = now - max(self.last_nod_t, self.gate_open_t if self.gate_open_t is not None else now)
        return self.listening and since >= self.next_interval
