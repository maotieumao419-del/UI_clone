"""
Query Amazon Ads API để lấy danh sách valid columns cho từng report type.
Chạy 1 lần để biết chính xác columns nào được phép, không cần đoán.

Output: raw_data/ads_columns_schema.txt
"""
import json
from pathlib import Path
import _auth as auth

OUT_DIR = Path("raw_data")
OUT_DIR.mkdir(exist_ok=True)

REPORT_TYPES = [
    ("SPONSORED_PRODUCTS", "spCampaigns"),
    ("SPONSORED_PRODUCTS", "spAdvertisedProduct"),
    ("SPONSORED_BRANDS",   "sbCampaigns"),
    ("SPONSORED_DISPLAY",  "sdCampaigns"),
]

def main():
    print("Lấy LWA token...")
    lwa_ads = auth.get_lwa_token(auth.ADS_REFRESH, auth.ADS_CLIENT_ID, auth.ADS_CLIENT_SECRET)

    lines = []
    for ad_product, report_type_id in REPORT_TYPES:
        print(f"\n── {ad_product} / {report_type_id} ──")
        try:
            # Amazon Ads API v3: GET /reporting/reports/schema/{adProduct}/{reportTypeId}
            resp = auth.ads_get(
                f"/reporting/reports/schema/{ad_product.lower()}/{report_type_id}",
                lwa_ads
            )
            columns = resp.get("columns", resp.get("metrics", []))
            if isinstance(columns, list):
                col_names = [c.get("name", c) if isinstance(c, dict) else c for c in columns]
            else:
                col_names = list(columns.keys()) if isinstance(columns, dict) else [str(columns)]

            print(f"  {len(col_names)} columns:")
            for c in sorted(col_names):
                print(f"    {c}")

            lines.append(f"\n=== {ad_product} / {report_type_id} ({len(col_names)} columns) ===")
            for c in sorted(col_names):
                lines.append(f"  {c}")

        except Exception as e:
            print(f"  ❌ {e}")
            # Thử endpoint khác
            try:
                resp2 = auth.ads_get(
                    f"/reporting/reports/metadata/{report_type_id}",
                    lwa_ads
                )
                print(f"  metadata: {json.dumps(resp2, indent=2)[:500]}")
                lines.append(f"\n=== {report_type_id} metadata ===")
                lines.append(json.dumps(resp2, indent=2)[:1000])
            except Exception as e2:
                print(f"  ❌ metadata cũng lỗi: {e2}")
                lines.append(f"\n=== {report_type_id} → LỖI: {e} ===")

    out = OUT_DIR / "ads_columns_schema.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n→ Đã lưu: {out}")

if __name__ == "__main__":
    main()
