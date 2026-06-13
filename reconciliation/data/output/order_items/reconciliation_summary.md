# Financial Reconciliation Report: ORDER_ITEMS

Generated at: 2026-06-12 10:40:01

## Summary Table

| Metric | API Output (System) | Sellerboard (Baseline) | Delta (API - SB) | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Units** | 75 | 75 | 0 | ✅ MATCH |
| **Refunds** | 2 | 4 | -2 | ❌ 2 MISMATCHES |
| **Sales** | $778.70 | $778.70 | $0.00 | ✅ MATCH |
| **Promo** | $0.00 | $0.00 | $0.00 | ✅ MATCH |
| **Refund Cost** | $-9.50 | $-26.82 | +$17.32 | ❌ 2 MISMATCHES |
| **Amazon Fees** | $-355.16 | $-323.41 | $-31.75 | ❌ 62 MISMATCHES |
| **Cost Of Goods** | $-17.20 | $-17.20 | $0.00 | ✅ MATCH |
| **Shipping** | 0 | 0 | 0 | ✅ MATCH |
| **Gross Profit** | $396.84 | $411.27 | $-14.43 | ❌ 64 MISMATCHES |
| **Net Profit** | $396.84 | $411.27 | $-14.43 | ❌ 64 MISMATCHES |
| **Margin** | 3,171.01% | 3,337.23% | -166.22% | ⚠️ DIFF |
| **Roi** | 4,390.21% | 4,247.14% | +143.07% | ⚠️ DIFF |
| **Expenses** | 0 | 0 | 0 | ✅ MATCH |

## Key Findings

1. **Total Rows Checked**: 66 rows.
2. **Discrepancies Found**: 64 rows with mismatch > $0.01.
3. **Observation**:
   - Check details of mismatched records in `mismatch_report.csv`.

## ── Phân tích theo order_status (phía NEW) ──

| Status | Số dòng | NEW Sales | SB Sales | NEW Fees | SB Fees | Số có ở SB |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| (chỉ có ở SB) | 4 | $0.00 | $0.00 | $0.00 | $0.00 | 4 |
| Pending | 14 | $156.78 | $156.78 | $-69.86 | $-65.80 | 14 |
| Shipped | 48 | $621.92 | $621.92 | $-285.30 | $-257.61 | 48 |

## ── Phân bổ status phía Sellerboard ──

| Status SB | Số lượng |
| :--- | :---: |
| Return | 4 |
| Shipped | 48 |
| Unshipped | 14 |

## ── Tổng cộng từ phân tích status ──

- **NEW**: Sales = $778.70, Fees = $-355.16
- **SB**: Sales = $778.70, Fees = $-323.41
