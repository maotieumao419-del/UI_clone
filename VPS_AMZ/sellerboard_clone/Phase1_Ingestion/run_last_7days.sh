#!/usr/bin/env bash
# Phase 1 — Call API Amazon cho 7 NGÀY PACIFIC gần nhất (đã hoàn tất).
# Nên chạy đúng 00:00 giờ Pacific (UTC-7) = 14:00 giờ VN (UTC+7) để mốc ngày
# khớp đúng Sellerboard.
#
#   Orders + Finances : lookback 168h (= 7 ngày) từ thời điểm chạy.
#   Ads               : lặp đúng 7 ngày Pacific đã hoàn tất (hôm qua -> 7 ngày trước),
#                       mỗi ngày 1 report (Ads API trả "date" theo timezone tài khoản).
set -u
cd "$(dirname "$0")"
PY=../backend/venv/bin/python

echo "================ RUN $(date '+%F %T %Z') | Pacific $(TZ=America/Los_Angeles date '+%F %T') ================"

echo "### ORDERS + FINANCES (168h) ###"
"$PY" direct_stream_pipeline.py --orders --finances --hours 168

for i in 1 2 3 4 5 6 7; do
  D=$(TZ=America/Los_Angeles date -d "$i day ago" +%F)
  echo "### ADS ngày Pacific $D ###"
  "$PY" direct_stream_pipeline.py --ads --date "$D"
done

echo "================ DONE $(date '+%F %T %Z') ================"
