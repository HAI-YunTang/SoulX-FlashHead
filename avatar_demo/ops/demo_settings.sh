#!/usr/bin/env bash
# Snapshot or restore the demo's call settings in the local snow DB.
#   ./demo_settings.sh save      # write demo_settings/*.json from the DB
#   ./demo_settings.sh restore   # put those rows back (e.g. after `make sync-data`)
# Rows: agent "Stacy" (voice, ELEVEN_LABS_MODEL_ID, ASR), the CHF demo script and its version,
# and patient Jane Anderson. The demo link (demo_url.txt) selects exactly these ids.
set -euo pipefail
cd "$(dirname "$0")"
PSQL=(psql -h 127.0.0.1 -U postgres -d hippocraticai -v ON_ERROR_STOP=1 -Atq)
AGENT=240330eb-8274-405c-86b1-931203191157
SCRIPT=67a8386a-c8d5-4166-ac11-2476e8ec7441
PATIENT=826cf739-fc8d-45d7-a536-d6ad1aa740eb
# table | primary key columns | row filter
ROWS=(
  "agent.agents|agent_id|agent_id = '$AGENT'"
  "call_script.call_scripts|script_id|script_id = '$SCRIPT'"
  "call_script.call_script_versions|script_id,version|script_id = '$SCRIPT' and version = (select version from call_script.call_scripts where script_id = '$SCRIPT')"
  "patient.patients|id|id = '$PATIENT'"
)

save() {
  mkdir -p demo_settings
  for r in "${ROWS[@]}"; do
    IFS='|' read -r table _ filter <<< "$r"
    "${PSQL[@]}" -c "select row_to_json(t) from $table t where $filter" > "demo_settings/$table.json"
    [ -s "demo_settings/$table.json" ] || { echo "no row in $table" >&2; exit 1; }
    echo "saved demo_settings/$table.json"
  done
}

restore() {
  for r in "${ROWS[@]}"; do
    IFS='|' read -r table pk _ <<< "$r"
    row=$(cat "demo_settings/$table.json")
    # Upsert every column from the saved JSON; the column list comes from the table itself.
    "${PSQL[@]}" -o /dev/null -v row="$row" -v tbl="$table" -v pk="$pk" <<'SQL'
select set_config('demo.row', :'row', false), set_config('demo.tbl', :'tbl', false), set_config('demo.pk', :'pk', false);
do $$
declare
  tbl text := current_setting('demo.tbl');
  pk text := current_setting('demo.pk');
  cols text;
  sets text;
begin
  select string_agg(quote_ident(column_name), ', ' order by ordinal_position),
         string_agg(format('%1$I = excluded.%1$I', column_name), ', ' order by ordinal_position)
    into cols, sets
    from information_schema.columns
   where table_schema = split_part(tbl, '.', 1) and table_name = split_part(tbl, '.', 2);
  execute format('insert into %s (%s) select %s from jsonb_populate_record(null::%s, $1::jsonb) on conflict (%s) do update set %s',
                 tbl, cols, cols, tbl, pk, sets)
    using current_setting('demo.row');
end $$;
SQL
    echo "restored $table"
  done
}

case "${1:-}" in
  save) save ;;
  restore) restore ;;
  *) echo "usage: $0 save|restore" >&2; exit 2 ;;
esac
