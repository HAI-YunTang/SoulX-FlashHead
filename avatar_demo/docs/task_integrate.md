> The original brief for this demo (2026-10-21), kept as written.

We want to build a demo with a nurse (an avatar) talks with user (patient). 
- Background
  - The working directory is under a linux container with a local mac. 
  - We have an agent to user conversational system at ~/source_codes/snow/ and we can create a web service as below 
    - snow repo: ~/source_codes/snow/
    - igloo repo: ~/source_codes/igloo/
    - follow the readme to setup local snow /home/source_codes/snow/install-local.md. Remember, the doc might be good for a mac and we are running under a linux container with a mac 
      - make all (installs things)
      - make run-all-services
    - docker - for db and for redis
    - oauth identity is required
      - use okta to authenticate (localhost dev)
    - ngrok
    - report api keys or password missing in the environment setting 
  - We have a talking face repo at ~/source_codes/SoulX-FlashHead/ and the working  2GPU inference setting is recorded at /home/works/2026/video_avatar/20261020_soulX-FlashHead/reports/pro_2gpu_working_config_benchmark.md 
  - We have reference image figures/nurse_image3.png 
  - We can use RTX machine as server. We can check /home/works/2026/TTS/20261009_step2/ to use skypilot to request machine/GPUs. We should source ~/source_codes/skypilot-infra/.venv/bin/activate to skypilot env.
  - We have reference voice from Rebecca at  ~/source_codes/kanzi/packages/chantek-monolith/src/csm_generation/resources/audio/rebec*wav. 
  - We have some demo scripts at ~/works/2026/video_avatar/20261020_soulX-FlashHead. We might reuse them
- Build a demo to simulate nurse and patient (user) conversation
  - We can interact with agent via video call from the local mac 
  - The system will use VAD, ASR and TTS from snow 
- Others
  - We might have gap/latency due to the conversational system process the information and machine to generate the corresponding avatar video, we can either have a still image or fill that a prepared video clip
  - The working directory is /home/works/2026/video_avatar/20261021_soulX-FlashHead and we can modify code at ~/source_codes/SoulX-FlashHead/ if needed. 

