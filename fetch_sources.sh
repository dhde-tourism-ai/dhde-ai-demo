#!/usr/bin/env bash
# Download the code4fukui open data that build_data.py aggregates.
#
# These files are NOT committed to this repo: they are ~95 MB, they belong to
# Code for Fukui, and they change daily. Fetch them, build, commit the small
# dhde_data.json that comes out.
#
#   ./fetch_sources.sh && python3 build_data.py
set -euo pipefail

SURVEY="https://raw.githubusercontent.com/code4fukui/fukui-kanko-survey/master"
RSV="https://raw.githubusercontent.com/code4fukui/fukui-kanko-reservation/main"
START_YM=202204
END_YM=$(date +%Y%m)

echo "==> area master"
curl -sSLf -o area.csv "$SURVEY/area.csv"

echo "==> monthly survey files ($START_YM .. $END_YM)"
mkdir -p monthly
for y in $(seq 2022 "$(date +%Y)"); do
  for m in 01 02 03 04 05 06 07 08 09 10 11 12; do
    ym="$y$m"
    [ "$ym" -lt "$START_YM" ] && continue
    [ "$ym" -gt "$END_YM" ] && continue
    echo "$ym"
  done
done | xargs -P 8 -I{} sh -c \
  "curl -sSLf -o monthly/{}.csv '$SURVEY/monthly/{}.csv' || echo '    (no file for {})' >&2"

echo "==> Awara reservation data"
for f in latest_rsv_sum latest_hotel booking_curve latest_rsv_prefecture_sum; do
  curl -sSLf -o "rsv_$f.csv" "$RSV/$f.csv"
done

echo
echo "monthly files : $(ls monthly | wc -l)"
echo "total size    : $(du -sh . | cut -f1)"
echo "next          : python3 build_data.py"
