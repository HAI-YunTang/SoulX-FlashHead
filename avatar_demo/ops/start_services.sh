#!/usr/bin/env bash
# Start local Postgres 15 (data in /home/pgdata) and Redis (data in /home/redisdata).
# The container has no systemd, so run this after every container restart.
set -e
PGBIN=/usr/lib/postgresql/15/bin
sudo mkdir -p /var/run/postgresql && sudo chown "$USER" /var/run/postgresql
if $PGBIN/pg_ctl -D /home/pgdata/15 status >/dev/null 2>&1; then
  echo "postgres: already running"
else
  $PGBIN/pg_ctl -D /home/pgdata/15 -l /home/pgdata/postgres.log -o "-c listen_addresses=127.0.0.1,::1 -p 5432" -w start
fi
if redis-cli -p 6379 ping >/dev/null 2>&1; then
  echo "redis: already running"
else
  redis-server --bind 127.0.0.1 ::1 --port 6379 --dir /home/redisdata --appendonly yes \
    --daemonize yes --logfile /home/redisdata/redis.log
fi
sleep 1
psql -h 127.0.0.1 -U postgres -d postgres -Atc "select 'postgres: ok ' || current_setting('server_version')"
echo "redis: $(redis-cli -p 6379 ping)"
