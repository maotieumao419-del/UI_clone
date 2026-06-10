"""
Gọi Amazon Advertising API — lấy spend + attributed sales/units trong 24h gần nhất.

Flow bất đồng bộ:
  1. POST /reporting/reports  → nhận reportId
  2. Poll GET /reporting/reports/{id} cho đến status = COMPLETED
  3. Download URL → decompress gzip → parse JSON

Loại report:
  SP  (Sponsored Products)      — spend + attributed sales 1d/7d
  SB  (Sponsored Brands)        — spend + attributed sales 14d + campaignType (SBV vs SB)
  SD  (Sponsored Display)       — spend + attributed sales 14d

Auth: Bearer LWA token + Amazon-Advertising-API-Scope: {profile_id}
      KHÔNG cần AWS SigV4 (khác SP-API).

Chạy:
    pip install requests python-dotenv
    python fetch_24h_ads.py

Output:
    raw_data/ads_sp_raw.json        — Sponsored Products raw
    raw_data/ads_sb_raw.json        — Sponsored Brands raw (gồm SBV)
    raw_data/ads_sd_raw.json        — Sponsored Display raw
    raw_data/ads_summary.txt        — tổng hợp spend theo loại
    raw_data/ads_fields_map.txt     — schema fields
"""
import gzip, io, json, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
import _auth as auth

OUT_DIR = Path("raw_data")
OUT_DIR.mkdir(exist_ok=True)

# ── Ngày cần lấy: hôm qua (để đủ dữ liệu) ────────────────────────────────────
NOW        = datetime.now(timezone.utc)
REPORT_DATE = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")   # e.g. "2026-06-08"

# Poll settings
POLL_INTERVAL = 15   # giây, poll mỗi 15s
POLL_TIMEOUT  = 600  # giây, tối đa 10 phút

# ── Report configs ────────────────────────────────────────────────────────────

SP_CONFIG = {
    "adProduct":    "SPONSORED_PRODUCTS",
    "reportTypeId": "spCampaigns",
    "groupBy":      ["campaign"],
    "columns": [
        "campaignId", "campaignName", "campaignStatus", "campaignBiddingStrategy",
        "impressions", "clicks", "cost",
        "purchases1d",  "purchases7d",  "purchases14d",  "purchases30d",
        "sales1d",      "sales7d",      "sales14d",      "sales30d",
        "unitsSoldClicks1d",
        "attributedSalesSameSku1d", "attributedSalesSameSku7d", "attributedSalesSameSku14d",
        "roasClicks14d",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

# SP report theo ASIN để biết spend per SKU
SP_ASIN_CONFIG = {
    "adProduct":    "SPONSORED_PRODUCTS",
    "reportTypeId": "spAdvertisedProduct",
    "groupBy":      ["advertiser"],
    "columns": [
        "campaignId", "campaignName", "adGroupId", "adGroupName",
        "advertisedAsin", "advertisedSku",
        "impressions", "clicks", "cost",
        "purchases1d", "sales1d", "unitsSoldClicks1d",
        "purchases7d", "sales7d",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

SB_CONFIG = {
    "adProduct":    "SPONSORED_BRANDS",
    "reportTypeId": "sbCampaigns",
    "groupBy":      ["campaign"],
    # Columns từ Amazon error message (allowed list cho sbCampaigns):
    # purchases/sales KHÔNG có suffix 14d — SB dùng tên khác SP
    "columns": [
        "campaignId", "campaignName", "campaignStatus",
        "impressions", "clicks", "cost", "date",
        "purchases", "purchasesPromoted",
        "detailPageViews", "brandedSearches", "brandStorePageView",
        "newToBrandPurchases", "newToBrandSales",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

SD_CONFIG = {
    "adProduct":    "SPONSORED_DISPLAY",
    "reportTypeId": "sdCampaigns",
    "groupBy":      ["campaign"],
    # Dùng tập tối thiểu chắc chắn hợp lệ — nếu lỗi sẽ in full allowed list
    "columns": [
        "campaignId", "campaignName", "campaignStatus",
        "impressions", "clicks", "cost", "date",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}


# ── Core: request + poll + download ──────────────────────────────────────────

def request_report(lwa_ads, config, name):
    body = {
        "name":          f"{name} {REPORT_DATE}",
        "startDate":     REPORT_DATE,
        "endDate":       REPORT_DATE,
        "configuration": config,
    }
    print(f"  [ADS] POST /reporting/reports ({name})...")
    resp = auth.ads_post("/reporting/reports", lwa_ads, body)
    report_id = resp.get("reportId", "")
    status    = resp.get("status", "")
    print(f"  [ADS] reportId={report_id}  status={status}")
    return report_id


def poll_until_done(lwa_ads, report_id, name):
    print(f"  [ADS] Polling {name} ({report_id[:12]}...)...", end="", flush=True)
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        resp   = auth.ads_get(f"/reporting/reports/{report_id}", lwa_ads)
        status = resp.get("status", "")
        print(f" {status}({elapsed}s)", end="", flush=True)
        if status == "COMPLETED":
            print()
            return resp.get("url", "")
        if status in ("FAILED", "CANCELLED"):
            print()
            print(f"  ❌ Report {name} {status}: {resp}")
            return None
    print()
    print(f"  ❌ Timeout sau {POLL_TIMEOUT}s")
    return None


def download_report(url):
    """Download từ pre-signed S3 URL (không cần auth header)."""
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    # Response là GZIP_JSON
    try:
        with gzip.open(io.BytesIO(resp.content)) as f:
            return json.load(f)
    except Exception:
        # Một số trường hợp không gzip
        return resp.json()


def fetch_report(lwa_ads, config, name):
    report_id = request_report(lwa_ads, config, name)
    if not report_id:
        return []
    url = poll_until_done(lwa_ads, report_id, name)
    if not url:
        return []
    print(f"  [ADS] Downloading {name}...")
    data = download_report(url)
    print(f"  [ADS] {name}: {len(data)} rows")
    return data


# ── Summary ───────────────────────────────────────────────────────────────────

def summarize_ads(sp_data, sp_asin_data, sb_data, sd_data):
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"ADS SUMMARY — {REPORT_DATE}")
    lines.append(f"{'='*60}\n")

    def agg(data, cost_key="cost", sales_key="sales1d", units_key="unitsSoldClicks1d",
            type_key=None, type_val=None):
        total_cost = total_sales = total_units = 0.0
        total_clicks = total_impressions = 0
        for row in data:
            if type_key and row.get(type_key) != type_val:
                continue
            total_cost         += float(row.get(cost_key,   0) or 0)
            total_sales        += float(row.get(sales_key,  0) or 0)
            total_units        += float(row.get(units_key,  0) or 0)
            total_clicks       += int(row.get("clicks",       0) or 0)
            total_impressions  += int(row.get("impressions",  0) or 0)
        return total_cost, total_sales, total_units, total_clicks, total_impressions

    # ── SP ──────────────────────────────────────────────────────
    sp_cost, sp_sales, sp_units, sp_clicks, sp_imp = agg(sp_data)
    lines.append("── SPONSORED PRODUCTS ──")
    lines.append(f"  Campaigns:             {len(sp_data)}")
    lines.append(f"  Impressions:           {sp_imp:>12,}")
    lines.append(f"  Clicks:                {sp_clicks:>12,}")
    lines.append(f"  Spend:                 ${sp_cost:>10.2f}")
    lines.append(f"  Attributed sales (1d): ${sp_sales:>10.2f}  ← same-day attribution")
    lines.append(f"  Attributed units (1d): {sp_units:>12.0f}")

    # SP by ASIN
    if sp_asin_data:
        lines.append(f"\n  Top 10 ASIN by spend:")
        sorted_asin = sorted(sp_asin_data, key=lambda x: float(x.get("cost", 0) or 0), reverse=True)[:10]
        for r in sorted_asin:
            lines.append(f"    {r.get('advertisedSku','?'):<30} cost=${float(r.get('cost',0)):>7.2f}  sales1d=${float(r.get('sales1d',0)):>8.2f}  units={r.get('unitsSoldClicks1d',0)}")

    # ── SB (Sponsored Brands) ──────────────────────────────────
    sb_cost, sb_sales, sb_units, sb_clicks, sb_imp = agg(sb_data, sales_key="sales14d", units_key="unitsSoldClicks14d")
    sbv_cost, sbv_sales, sbv_units, _, _ = agg(sb_data, sales_key="sales14d", units_key="unitsSoldClicks14d",
                                               type_key="campaignType", type_val="sponsoredBrandsVideo")
    sb_only_cost = sb_cost - sbv_cost
    lines.append("\n── SPONSORED BRANDS (gồm SBV) ──")
    lines.append(f"  Campaigns:             {len(sb_data)}")
    lines.append(f"  Spend SB only:         ${sb_only_cost:>10.2f}")
    lines.append(f"  Spend SBV only:        ${sbv_cost:>10.2f}")
    lines.append(f"  Spend tổng SB+SBV:     ${sb_cost:>10.2f}")
    lines.append(f"  Attributed sales (14d):${sb_sales:>10.2f}")

    # ── SD ──────────────────────────────────────────────────────
    sd_cost, sd_sales, sd_units, sd_clicks, sd_imp = agg(sd_data, sales_key="sales14d", units_key="unitsSoldClicks14d")
    lines.append("\n── SPONSORED DISPLAY ──")
    lines.append(f"  Campaigns:             {len(sd_data)}")
    lines.append(f"  Spend:                 ${sd_cost:>10.2f}")
    lines.append(f"  Attributed sales (14d):${sd_sales:>10.2f}")

    # ── Tổng (giống Sellerboard) ───────────────────────────────
    total_adv_cost = sp_cost + sb_cost + sd_cost
    lines.append(f"\n{'─'*60}")
    lines.append(f"TỔNG ADVERTISING COST (giống Sellerboard):")
    lines.append(f"  Sponsored Products:    ${sp_cost:>10.2f}")
    lines.append(f"  Sponsored Brands:      ${sb_only_cost:>10.2f}")
    lines.append(f"  Sponsored Brands Video:${sbv_cost:>10.2f}")
    lines.append(f"  Sponsored Display:     ${sd_cost:>10.2f}")
    lines.append(f"  ── TỔNG ──             ${total_adv_cost:>10.2f}")
    lines.append(f"\nReal ACOS (tham khảo): cần kết hợp với Sales từ SP-API")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print(f"FETCH ADS REPORTS — {REPORT_DATE} — Amazon Advertising API")
    print("=" * 60)

    missing = [k for k, v in {
        "CLIENT_ID":      auth.CLIENT_ID,
        "CLIENT_SECRET":  auth.CLIENT_SECRET,
        "ADS_REFRESH":    auth.ADS_REFRESH,
        "ADS_PROFILE_ID": auth.ADS_PROFILE_ID,
    }.items() if not v]
    if missing:
        print(f"❌ Thiếu credentials: {missing}")
        print("   Thêm ADS_PROFILE_ID và AMAZON_ADS_REFRESH_TOKEN vào .env")
        print("   Xem .env.example để biết cách lấy.")
        return

    print(f"\n[1] Lấy LWA token cho Ads API...")
    lwa_ads = auth.get_lwa_token(auth.ADS_REFRESH, auth.ADS_CLIENT_ID, auth.ADS_CLIENT_SECRET)

    # Optional: lấy danh sách profiles nếu chưa biết profile_id
    if auth.ADS_PROFILE_ID in ("", "your_ads_profile_id"):
        print("\n[!] ADS_PROFILE_ID chưa điền. Lấy danh sách profiles...")
        profiles = auth.ads_get("/v2/profiles", lwa_ads)
        print(f"  Tìm thấy {len(profiles)} profiles:")
        for p in profiles:
            print(f"    profileId={p['profileId']}  marketplace={p.get('countryCode','')}  "
                  f"type={p.get('accountInfo',{}).get('type','')}  "
                  f"name={p.get('accountInfo',{}).get('name','')}")
        print("\n  → Điền ADS_PROFILE_ID vào .env và chạy lại.")
        return

    # Luôn in danh sách profiles để xác nhận profile_id đúng
    print(f"\n[2] Lấy danh sách profiles (không cần Scope header)...")
    try:
        profiles = auth.ads_get("/v2/profiles", lwa_ads, profile_id="")
        print(f"  Tìm thấy {len(profiles)} profiles:")
        for p in profiles:
            marker = " ← ĐANG DÙNG" if str(p.get("profileId", "")) == str(auth.ADS_PROFILE_ID) else ""
            print(f"    profileId={p['profileId']}  {p.get('countryCode','')}  "
                  f"type={p.get('accountInfo',{}).get('type','')}  "
                  f"name={p.get('accountInfo',{}).get('name','')}{marker}")
    except Exception as e:
        print(f"  ⚠️  Không lấy được profiles: {e}")
        print("  → Tiếp tục với ADS_PROFILE_ID trong .env")

    print(f"\n[3] Request reports cho {REPORT_DATE} (async)...")
    print("  (Mỗi report mất 1-5 phút để Amazon generate)\n")

    # Gửi từng report với delay 5s để tránh 429
    sp_id      = request_report(lwa_ads, SP_CONFIG,      "SP-Campaigns");  time.sleep(5)
    sp_asin_id = request_report(lwa_ads, SP_ASIN_CONFIG, "SP-ASIN");       time.sleep(5)
    sb_id      = request_report(lwa_ads, SB_CONFIG,      "SB-Campaigns");  time.sleep(5)
    sd_id      = request_report(lwa_ads, SD_CONFIG,      "SD-Campaigns")

    print("\n[4] Poll & download từng report...")
    sp_data      = []
    sp_asin_data = []
    sb_data      = []
    sd_data      = []

    for report_id, name, target in [
        (sp_id,      "SP-Campaigns",  sp_data),
        (sp_asin_id, "SP-ASIN",       sp_asin_data),
        (sb_id,      "SB-Campaigns",  sb_data),
        (sd_id,      "SD-Campaigns",  sd_data),
    ]:
        if not report_id:
            continue
        url = poll_until_done(lwa_ads, report_id, name)
        if url:
            target.extend(download_report(url))
            print(f"  ✅ {name}: {len(target)} rows")

    # ── Lưu raw JSON ──────────────────────────────────────────────
    for data, filename in [
        (sp_data,      "ads_sp_raw.json"),
        (sp_asin_data, "ads_sp_asin_raw.json"),
        (sb_data,      "ads_sb_raw.json"),
        (sd_data,      "ads_sd_raw.json"),
    ]:
        out = OUT_DIR / filename
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        print(f"  → {out}  ({out.stat().st_size // 1024} KB)")

    # ── Summary ────────────────────────────────────────────────────
    summary = summarize_ads(sp_data, sp_asin_data, sb_data, sd_data)
    print("\n" + summary)
    sf = OUT_DIR / "ads_summary.txt"
    sf.write_text(summary, encoding="utf-8")
    print(f"\n→ Summary: {sf}")

    # ── Fields map ────────────────────────────────────────────────
    all_fields = {}
    for lst, prefix in [(sp_data, "SP"), (sb_data, "SB"), (sd_data, "SD"), (sp_asin_data, "SP_ASIN")]:
        for row in lst:
            auth.collect_fields(row, prefix, all_fields)
    auth.write_fields_map(all_fields, OUT_DIR / "ads_fields_map.txt", "ADS REPORT FIELDS")

    print("\n✅ Xong. Xem raw_data/ để phân tích chi tiết.")


if __name__ == "__main__":
    main()
