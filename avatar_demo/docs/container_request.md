# Container request: devbox for the nurse avatar demo

> **Update 2026-10-22: resolved.** The container was rebuilt with 8 CPU, 16 GB, swap and `--init`. The "Lima" VM is actually **Colima**. The network stalls came from Colima's user-mode NAT, plus an MTU black hole on the vzNAT path. Both are fixed with `colima start --network-address`, a `col0` default route and `mtu 1280`; see `network_and_frame_drops.md` and `runbook.md` step 0. The analysis below is kept for history.

**Purpose:** run local snow (snow_call, snow_web, demo_portal), Postgres and Redis, plus the SSH tunnels to the GPU pod. The GPU work runs on SkyPilot, not in this container.

Observed on 2026-10-21/22 in the current devbox: Docker container `devbox` (172.17.0.2) inside a Lima VM on the Mac, Ubuntu 24.04 aarch64.

## What went wrong with the current container

| Problem | Evidence | Impact |
|---|---|---|
| Too little RAM, no swap | 8 GB total, about 1.9 GB free with snow running. `swapon` is not permitted. `oom_kill 5` in `/sys/fs/cgroup/memory.events` | Vite and esbuild were OOM-killed. Snow and the UI could not start together the normal way (`make run-all-services`), so the UI needs a special start command. |
| Too few CPUs | 4 vCPUs at load 3.5–4.5 | Processing was slow and the network stalls got worse. |
| Unstable network from the container | The Mac is fast: worst request 0.23 s, DNS about 3 ms. The container is not: 15 of 43 requests to `api.model.hippocraticai.com` took over 1 s, with stalls up to 15 s (DNS and TCP connect). Public hosts also stalled. | Snow's model calls took 130 s+, agent replies never came, and calls failed. **This is the biggest issue.** |
| No init process | PID 1 is `sleep`, and about 500 zombie processes piled up | Mostly harmless, but zombies use up PIDs. |
| No ports published | The Mac reaches the UI only with `ssh -L` | Workable, but adds a moving part. |
| No systemd | Postgres and Redis must be started by hand after every restart | `start_services.sh` handles this. |

## Request

### Resources

| | Current | Requested | Why |
|---|---|---|---|
| vCPU | 4 | **8** (minimum 6) | snow_call alone runs about 10 processes (VAD, workers). Vite, gunicorn, Postgres, git and the Claude/IDE servers run alongside it. |
| RAM | 8 GB | **16 GB** (minimum 12) | snow_call plus snow_web use about 3 GB, Vite and esbuild 0.4–1.8 GB, the IDE/Claude servers 1–2 GB, and Postgres and Redis about 0.3 GB. The Vite first build peaks above 1.5 GB. |
| Swap | not allowed | **4–8 GB allowed** | A safety net for build peaks instead of OOM kills. |
| Disk | 59 GB overlay, `/home` 927 GB shared | Same | Data already lives on `/home` (shared from the Mac). |

On Lima, the VM must be sized first, then the container. For example, in `~/.lima/<instance>/lima.yaml` set `cpus: 8` and `memory: "20GiB"`, then give the container `--cpus 8 --memory 16g --memory-swap 24g`.

### Networking (most important)

1. **Lima network mode.** Prefer **`vzNAT`** (macOS Virtualization.framework NAT, `vmType: vz`) over the default user-mode slirp/gvisor networking. The stalls look like packet or connection drops in the VM's NAT, not on the Mac. Switch, then re-run the latency loop below.
2. **DNS.** The container uses Lima's host resolver at 192.168.5.1. Lookups sometimes took 15 s. Tailscale MagicDNS and split DNS must still resolve the internal `*.hippocraticai.com` and `*.hippocraticdev.com` hosts, so either forward DNS to the Mac's resolver reliably or run a local caching resolver (`dnsmasq`) in the VM.
3. **Docker networking.** Use `--network host` inside the VM. This avoids a second NAT layer and makes the services' ports reachable from the VM directly.
4. **Port publishing (optional).** Forward Lima ports 5173, 3000 and 4000 to the Mac, using Lima `portForwards` or the container's `-p`. The Mac `ssh -L` step then becomes unnecessary. With host networking, Lima's automatic port forwarding usually picks them up.

**Acceptance test.** Run this in the container. Expect no request over 1 s:

```bash
for h in api.model.hippocraticai.com dev-api.model.hippocraticai.com api.deepgram.com; do
  for i in $(seq 1 40); do curl -s -o /dev/null -m 15 -w '%{time_total}\n' https://$h/ || echo 15; sleep 0.5; done |
  awk -v h=$h '{n++; s+=$1; if($1>1) slow++; if($1>m) m=$1} END {printf "%-34s mean=%.2fs max=%.2fs over_1s=%d/%d\n", h, s/n, m, slow, n}'
done
```

### Process and runtime

- **Init process.** Run with `docker run --init` (tini) so zombies are reaped.
- **Persistent data.** Keep `/home` mounted from the Mac as now. Postgres (`/home/pgdata`), Redis (`/home/redisdata`), the repos, `~/.bashrc` and `~/.aws` all live there.
- **Sudo.** Passwordless sudo, as now, so `start_services.sh` can create `/var/run/postgresql`.
- **Entrypoint (optional).** Run `start_services.sh` at container start, so Postgres and Redis come up automatically.

### Packages to bake into the image

These were installed by hand on 2026-10-21 and are lost on rebuild. Use the Dockerfile snippet in `container_packages.md`:

- `postgresql-15`, `postgresql-client-15` and `postgresql-15-pgvector` from the PGDG apt repo (`noble-pgdg`)
- `libpq-dev`, `redis-server`, `nodejs` 24.x (NodeSource)
- `git-lfs`, `ffmpeg`, `libasound2-dev`, `libgeos-dev`, `rustc`, `cargo`, `libsndfile1`
- `libpango-1.0-0`, `libpangoft2-1.0-0`, `libharfbuzz0b`, `libffi-dev`, `shared-mime-info`
- `rsync`, `lsof`, `iproute2`, `procps`, `zsh`, `iputils-ping`, `dnsutils`
- Optional: `uv python install 3.11.11`, the Python snow pins

## After the container restarts or is rebuilt

Follow `TODO.md`, section "Restart checklist".
