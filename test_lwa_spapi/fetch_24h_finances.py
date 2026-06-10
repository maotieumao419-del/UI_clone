"""
Gọi Amazon SP-API Finances API — lấy tất cả financial events trong 24h gần nhất.

Bao gồm:
  ShipmentEventList   — phí FBA, Referral cho từng đơn hàng
  RefundEventList     — phí hoàn hàng (Refund cost = Refunded amount + commission - referral fee back)
  AdjustmentEventList — Compensated clawback, FBA disposal, inventory reimbursement
  ServiceFeeEventList — phí dịch vụ Amazon khác

Chạy:
    pip install requests python-dotenv
    python fetch_24h_finances.py

Output:
    raw_data/finances_24h_raw.json   — toàn bộ events thô
    raw_data/finances_summary.txt    — tổng hợp số tiền theo loại phí
    raw_data/finances_fields_map.txt — schema của tất cả field
"""
import json, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import _auth as auth

OUT_DIR = Path("raw_data")
OUT_DIR.mkdir(exist_ok=True)

# ── Date range: 24h gần nhất ──────────────────────────────────────────────────
# PostedBefore bị bỏ vì Finances API trả 400 khi PostedBefore quá gần hiện tại
# (data chưa được Amazon finalize) — để trống = Amazon tự dùng "now"
NOW          = datetime.now(timezone.utc)
POSTED_AFTER = (NOW - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
POSTED_BEFORE = None


def fetch_all_financial_events(lwa, sk, ss, st):
    """Kéo toàn bộ financial events với pagination (NextToken)."""
    all_events = {
        "ShipmentEventList":    [],
        "RefundEventList":      [],
        "AdjustmentEventList":  [],
        "ServiceFeeEventList":  [],
        "OtherEventLists":      {},
    }
    next_token = None
    page = 0

    while True:
        page += 1
        if next_token:
            params = {"NextToken": next_token}
        else:
            params = {"PostedAfter": POSTED_AFTER, "MaxResultsPerPage": 100}
            if POSTED_BEFORE:
                params["PostedBefore"] = POSTED_BEFORE

        print(f"  Trang {page}...", end=" ")
        resp     = auth.spapi_get("/finances/v0/financialEvents", params, lwa, sk, ss, st)
        payload  = resp.get("payload", {})
        events   = payload.get("FinancialEvents", {})
        next_token = payload.get("NextToken")

        for key in ("ShipmentEventList", "RefundEventList",
                    "AdjustmentEventList", "ServiceFeeEventList"):
            items = events.get(key, [])
            all_events[key].extend(items)
            print(f"{key}: +{len(items)}", end="  ")

        # Ghi nhận các list ít phổ biến để không bỏ sót
        for k, v in events.items():
            if k not in ("ShipmentEventList", "RefundEventList",
                         "AdjustmentEventList", "ServiceFeeEventList") and v:
                all_events["OtherEventLists"].setdefault(k, []).extend(v)
                print(f"{k}: +{len(v)}", end="  ")

        print(f"(NextToken: {bool(next_token)})")
        if not next_token:
            break
        time.sleep(1.0)

    return all_events


def summarize_events(all_events):
    """Tổng hợp số tiền từng loại phí để so sánh với Sellerboard."""
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"FINANCE SUMMARY — {POSTED_AFTER} → {POSTED_BEFORE}")
    lines.append(f"{'='*60}\n")

    def _amt(obj, key="CurrencyAmount"):
        """Lấy số tiền an toàn — trả 0.0 nếu field không tồn tại."""
        return float((obj or {}).get(key, 0) or 0)

    # ── ShipmentEventList ──────────────────────────────────────────
    lines.append("── SHIPMENT EVENTS (đơn bình thường) ──")
    fba_total = referral_total = principal_total = 0.0
    for event in all_events["ShipmentEventList"]:
        for item in event.get("ShipmentItemList", []):
            for charge in item.get("ItemChargeList", []):
                if charge.get("ChargeType") == "Principal":
                    principal_total += _amt(charge.get("ChargeAmount"))
            for fee in item.get("ItemFeeList", []):
                amt = _amt(fee.get("FeeAmount"))
                ft  = fee.get("FeeType", "")
                if ft == "FBAPerUnitFulfillmentFee":
                    fba_total      += amt
                elif ft == "Commission":
                    referral_total += amt

    lines.append(f"  Tổng đơn:              {len(all_events['ShipmentEventList'])}")
    lines.append(f"  Principal (Sales):     ${principal_total:>10.2f}")
    lines.append(f"  FBA Fulfillment fee:   ${fba_total:>10.2f}")
    lines.append(f"  Referral fee:          ${referral_total:>10.2f}")

    # ── RefundEventList ────────────────────────────────────────────
    lines.append("\n── REFUND EVENTS (trả hàng) ──")
    refund_principal = refund_commission = refund_referral_back = 0.0
    for event in all_events["RefundEventList"]:
        for item in event.get("ShipmentItemAdjustmentList", []):
            for charge in item.get("ItemChargeAdjustmentList", []):
                if charge.get("ChargeType") == "Principal":
                    refund_principal += _amt(charge.get("ChargeAmount"))
            for fee in item.get("ItemFeeAdjustmentList", []):
                amt = _amt(fee.get("FeeAmount"))
                ft  = fee.get("FeeType", "")
                if ft == "Commission":
                    refund_commission    += amt
                elif ft == "RefundCommission":
                    refund_referral_back += amt  # DƯƠNG — Amazon hoàn lại referral fee

    refund_total = refund_principal + refund_commission + refund_referral_back
    lines.append(f"  Tổng return:                {len(all_events['RefundEventList'])}")
    lines.append(f"  Refunded amount:            ${refund_principal:>10.2f}")
    lines.append(f"  Refund commission:          ${refund_commission:>10.2f}")
    lines.append(f"  Refunded referral fee (+):  ${refund_referral_back:>10.2f}  ← DƯƠNG, Amazon hoàn lại")
    lines.append(f"  Refund cost (tổng):         ${refund_total:>10.2f}")

    # ── AdjustmentEventList ────────────────────────────────────────
    lines.append("\n── ADJUSTMENT EVENTS (điều chỉnh) ──")
    adj_totals = {}
    for event in all_events["AdjustmentEventList"]:
        adj_type = event.get("AdjustmentType", "Unknown")
        for item in event.get("AdjustmentItemList", []):
            amt = float(item.get("PerUnitAmount", {}).get("CurrencyAmount", 0)) * float(item.get("Quantity", 1))
            adj_totals[adj_type] = adj_totals.get(adj_type, 0.0) + amt
    for k, v in sorted(adj_totals.items()):
        lines.append(f"  {k:<40} ${v:>10.2f}")

    # ── ServiceFeeEventList ────────────────────────────────────────
    lines.append("\n── SERVICE FEE EVENTS ──")
    svc_totals = {}
    for event in all_events["ServiceFeeEventList"]:
        for fee in event.get("FeeList", []):
            ft  = fee.get("FeeType", "Unknown")
            amt = _amt(fee.get("FeeAmount"))
            svc_totals[ft] = svc_totals.get(ft, 0.0) + amt
    for k, v in sorted(svc_totals.items()):
        lines.append(f"  {k:<40} ${v:>10.2f}")

    # ── Tổng Amazon fees (giống Sellerboard) ──────────────────────
    adj_total = sum(adj_totals.values())
    svc_total = sum(svc_totals.values())
    amazon_fees = fba_total + referral_total + adj_total + svc_total
    lines.append(f"\n{'─'*60}")
    lines.append(f"TỔNG AMAZON FEES (giống Sellerboard):")
    lines.append(f"  FBA fulfillment:  ${fba_total:>10.2f}")
    lines.append(f"  Referral:         ${referral_total:>10.2f}")
    lines.append(f"  Adjustments:      ${adj_total:>10.2f}")
    lines.append(f"  Service fees:     ${svc_total:>10.2f}")
    lines.append(f"  ── TỔNG ──        ${amazon_fees:>10.2f}")
    lines.append(f"\n  REFUND COST:      ${refund_total:>10.2f}")
    lines.append(f"  SALES (Principal):${principal_total:>10.2f}")

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("FETCH FINANCES — 24H — SP-API Finances")
    print("=" * 60)
    print(f"Khoảng thời gian: {POSTED_AFTER} → {POSTED_BEFORE}\n")

    missing = [k for k, v in {
        "CLIENT_ID":     auth.CLIENT_ID,
        "CLIENT_SECRET": auth.CLIENT_SECRET,
        "SP_REFRESH":    auth.SP_REFRESH,
    }.items() if not v]
    if missing:
        print(f"❌ Thiếu credentials: {missing}")
        return

    lwa = auth.get_lwa_token(auth.SP_REFRESH)
    use_sigv4 = all([auth.AWS_KEY, auth.AWS_SECRET, auth.ROLE_ARN])
    if use_sigv4:
        try:
            sk, ss, st = auth.get_sts_creds()
        except Exception as e:
            print(f"  ⚠️  STS thất bại: {e} → thử LWA-only")
            sk = ss = st = None
    else:
        print("  [Auth] LWA-only mode")
        sk = ss = st = None

    # ── Kéo dữ liệu ──────────────────────────────────────────────
    print("\nKéo financial events...")
    all_events = fetch_all_financial_events(lwa, sk, ss, st)

    total_items = (len(all_events["ShipmentEventList"]) +
                   len(all_events["RefundEventList"]) +
                   len(all_events["AdjustmentEventList"]) +
                   len(all_events["ServiceFeeEventList"]))
    print(f"\nTổng events: {total_items}")

    # ── Lưu raw JSON ──────────────────────────────────────────────
    raw_file = OUT_DIR / "finances_24h_raw.json"
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(all_events, f, ensure_ascii=False, indent=2, default=str)
    print(f"→ Raw JSON: {raw_file}  ({raw_file.stat().st_size // 1024} KB)")

    # ── Tổng hợp ──────────────────────────────────────────────────
    summary = summarize_events(all_events)
    print("\n" + summary)
    summary_file = OUT_DIR / "finances_summary.txt"
    summary_file.write_text(summary, encoding="utf-8")
    print(f"\n→ Summary: {summary_file}")

    # ── Fields map ────────────────────────────────────────────────
    all_fields = {}
    for key in ("ShipmentEventList", "RefundEventList", "AdjustmentEventList", "ServiceFeeEventList"):
        for event in all_events[key]:
            auth.collect_fields(event, key, all_fields)
    auth.write_fields_map(all_fields, OUT_DIR / "finances_fields_map.txt", "FINANCE FIELDS")


if __name__ == "__main__":
    main()
