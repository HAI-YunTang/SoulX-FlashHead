# Packages the container needs for local snow

Container: Ubuntu 24.04, aarch64. Checked on 2026-10-21.

Already installed: git, gh, curl, wget, make, gcc/g++ (build-essential), pkg-config, jq, unzip, ssh, sudo, aws, op, uv, portaudio19-dev / libportaudio2, python3-dev.

## Missing

| Package | Why |
|---|---|
| `postgresql-15`, `postgresql-client-15`, `postgresql-15-pgvector` (from the PGDG apt repo; Ubuntu 24.04's default is 16) | Snow DB. Snow uses `pgvector/pgvector:pg15` in docker; `psql` is used by the make DB targets. |
| `libpq-dev` | `pg_config` for psycopg2 builds (psycopg2-binary usually has a wheel, but keep it as a safety net) |
| `redis-server` (includes `redis-cli`) | Snow uses Redis 7.x on 6379 |
| `nodejs` 24.x (NodeSource; includes npm) | demo_portal pins Node 24.19.0 in `.nvmrc`. Ubuntu's apt nodejs is too old. |
| `git-lfs` | `git lfs pull` in snow and igloo |
| `ffmpeg` | Audio handling (in snow's base image) |
| `libasound2-dev` | pyaudio / ALSA headers (in snow's base image) |
| `libgeos-dev` | shapely (in snow's base image) |
| `rustc`, `cargo` | Python packages without aarch64 wheels may need a Rust build (in snow's base image) |
| `libsndfile1` | soundfile / torchaudio |
| `libpango-1.0-0`, `libpangoft2-1.0-0`, `libharfbuzz0b`, `libffi-dev`, `shared-mime-info` | weasyprint 62.3 (PDF rendering) |
| `rsync`, `lsof`, `iproute2` (provides `ss`), `procps` | Moving files to the GPU pod, debugging ports and processes |
| `zsh` (optional) | The makefile uses zsh if it's there and falls back to bash |

Python: snow pins **3.11.11** (`.python-version`) and `/opt/venv` is 3.13. `uv sync` downloads 3.11.11 by itself. To bake it into the image, add `uv python install 3.11.11`.

Not needed: `ngrok` (only phone calls use it), docker.

## Dockerfile snippet

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt noble-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
 && apt-get update && apt-get install -y --no-install-recommends \
      postgresql-15 postgresql-client-15 postgresql-15-pgvector libpq-dev \
      redis-server \
      nodejs \
      git-lfs ffmpeg libasound2-dev libportaudio2 libgeos-dev rustc cargo libsndfile1 \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi-dev shared-mime-info \
      make rsync lsof iproute2 procps zsh iputils-ping dnsutils \
 && git lfs install --system \
 && rm -rf /var/lib/apt/lists/*
```

## How it's set up now (installed by hand on 2026-10-21)
- Everything above is installed with apt. `lsb_release` isn't in the image, so the PGDG line uses `noble` directly. Node is 24.22.1.
- Postgres 15.19 + pgvector 0.8.7 runs as `yuntang`, not `postgres`, with its data in `/home/pgdata/15`. `/home` is shared from the Mac, so the data survives a rebuild. Files there can't be given to another owner, so running as the `postgres` user wouldn't work.
  - Superuser `postgres` / password `postgres`, listening on 127.0.0.1:5432.
  - `~/.pgpass` holds the password so the make targets' `psql` calls don't prompt.
- Redis 7.0.15 listens on 127.0.0.1:6379, with its data and append-only file in `/home/redisdata`.
- After a container restart, run `./start_services.sh`.
- After a rebuild, apt installs are lost: add the snippet above to the Dockerfile, then run `start_services.sh`. The data in `/home` is still there.
