#!/usr/bin/env bash
# Chờ tới 14:00 ICT (= 00:00 Pacific UTC-7) rồi chạy run_last_7days.sh.
# Dùng: nohup bash schedule_7days.sh >/tmp/sched7_nohup.log 2>&1 &
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET=$(date -d 'today 14:00' +%s)
NOW=$(date +%s)
SECS=$((TARGET - NOW))
if [ "$SECS" -lt 0 ]; then
  SECS=$(( $(date -d 'tomorrow 14:00' +%s) - NOW ))
fi
echo "$(date '+%F %T %Z') | sleep ${SECS}s (~$((SECS/60)) phut) -> 14:00 ICT / 00:00 Pacific" > /tmp/sched7.log
sleep "$SECS"
echo "$(date '+%F %T %Z') | BAT DAU run_last_7days.sh" >> /tmp/sched7.log
"$DIR/run_last_7days.sh" > /tmp/ingest7.log 2>&1
echo "$(date '+%F %T %Z') | XONG run_last_7days.sh" >> /tmp/sched7.log
