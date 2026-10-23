# TODO: nurse avatar demo (state 2026-10-23 ~18:30)

## Where we are

- **Working end to end** on the local devbox: a Mac browser VOIP call to local snow, with the nurse rendered by FlashHead Pro on a SkyPilot GPU pod. Steps are in `runbook.md`; the design is in `demo_system.html`.
- **Done and verified in calls:**
  - the network fixes (Colima vzNAT route and MTU 1280; `network_and_frame_drops.md`);
  - live idle motion between turns (H200);
  - barge-in that stops the avatar at once;
  - the tunnel watchdog;
  - the demo default settings (`ops/demo_url.txt`, `ops/demo_settings.sh`).
- **Built, tested, not yet tried in a call:** active-listening nods on the H200 (fork commits `c99c5c4`, and `de4e1b9` for the echo and snap fixes). They need live idle, so they don't apply on 2x RTX.
- **GPU now:** `yuntang-avatar-2gpu` (2x RTX Pro 6000, use15, default workspace) is **up and billing**. The tunnel watchdog points at it. Use the demo link with `avatar_delay_ms=2850`.
- **The reserved usw4 H200 node didn't schedule** on 2026-10-23: the pod waited an hour, then the request ended. The node still carries the `hai/reserved=yuntang-sa` label and taint; see the header of `configs/skypilot_avatar_h200_cw_usw4_speech.yaml` for how to remove them.

## Code

- **SoulX-FlashHead fork** (`git@github.com:HAI-YunTang/SoulX-FlashHead.git`), branch `yuntang/nurse-avatar-demo`, in `avatar_demo/`. Pushed to the fork, so it can be checked out on another machine.
- **Snow**, branch `yuntang/nurse-avatar-demo`: forwarder, page and tests. All commits are **local only**.

## Next tasks

- [ ] Try the listening nods in a call on an H200: no nods on short answers, nods about 5 s into a long one, at pauses. Tune `AVATAR_NOD_PX`, `AVATAR_NOD_AFTER_S` and `AVATAR_NOD_INTERVAL_S`.
- [ ] Add a "listening behaviour" section and the `AVATAR_LISTEN_NODS` / `AVATAR_NOD_*` settings to `runbook.md`.
- [ ] Find H200 capacity again: retry the reserved node, or `sky gpus list H200`.
- [ ] Decide whether the snow branch becomes a PR (the images are already in LFS).
- [ ] Make the Colima route and MTU persistent with the provision script in `network_and_frame_drops.md`.
- [ ] Skip the Twilio sub-account fetch at snow start-up when `DISABLE_TWILIO=true` (a separate snow change).
- [ ] Fix the layout of the flow chart in `demo_system.html`: overlapping arrows and labels running past box edges.
- [ ] When done: `sky down yuntang-avatar-2gpu`, then remove the usw4 node's reservation.
