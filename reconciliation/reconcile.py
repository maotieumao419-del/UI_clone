import os
import re
import sys
from datetime import datetime
import pandas as pd

# Set console output encoding to utf-8 to prevent windows print error with unicode checkmarks
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

_CYR = str.maketrans({"с": "c", "о": "o", "а": "a", "е": "e", "р": "p", "у": "y", "х": "x"})

COLUMN_ALIASES = {
    'refunds pct': ['pct refunds', 'refunds pct', 'refunds_pct'],
    'unit session pct': ['unit session percentage', 'unit session pct', 'unit_session_pct'],
}

KNOWN_CONCEPTS = ['order_items', 'products']
IGNORE_WORDS = {'new', 'summary', 'rows', 'dashboard', 'craft', 'dr', 'hai', 'xlsx', 'sheet', 'report', 'reconciliation'}

def clean_order_number(val):
    if pd.isna(val):
        return ""
    val_str = str(val).strip()
    match = re.search(r'(\d{3}-\d{7}-\d{7})', val_str)
    if match:
        return match.group(1)
    return val_str.split(' / ')[0].strip()

def clean_num(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    if isinstance(v, (datetime, pd.Timestamp)):
        return round(v.day + v.month / 100, 2)
    s = str(v).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0

def normalize_col(s):
    s_clean = str(s).translate(_CYR).strip().lower()
    s_clean = s_clean.replace('%', ' pct ')
    s_clean = re.sub(r'\(.*?\)', '', s_clean)
    s_clean = re.sub(r'[\n\r\$]+', '', s_clean)
    s_clean = re.sub(r'[\s_]+', ' ', s_clean).strip()
    return s_clean

def canonicalize_col(s):
    s_norm = normalize_col(s)
    for canonical, aliases in COLUMN_ALIASES.items():
        if s_norm in aliases:
            return canonical
    return s_norm

def find_column(df, target_canonical):
    target_canonical = canonicalize_col(target_canonical)
    for col in df.columns:
        if canonicalize_col(col) == target_canonical:
            return col
    return None

def format_val(label, val):
    lbl = label.lower()
    if 'pct' in lbl or 'percentage' in lbl or 'margin' in lbl or 'roi' in lbl:
        return f"{val:,.2f}%" if 'margin' in lbl or 'roi' in lbl or 'pct' in lbl else f"{val:,.2f}"
    if 'sales' in lbl or 'fee' in lbl or 'cost' in lbl or 'profit' in lbl or 'payout' in lbl or 'cogs' in lbl or 'promo' in lbl or 'ads' in lbl:
        return f"${val:,.2f}"
    try:
        if val.is_integer():
            return f"{int(val):,}"
    except AttributeError:
        pass
    return f"{val:,.2f}"

def get_clean_words(filename):
    name_part = os.path.splitext(filename)[0]
    words = re.findall(r'[a-z]+', name_part.lower())
    return {w for w in words if w not in IGNORE_WORDS}

def make_clean_fn(key_name):
    if 'order' in key_name.lower():
        return lambda x: clean_order_number(x)
    return lambda x: str(x).strip() if not pd.isna(x) else ""

CONFIGS = {
    'order_items': {
        'keys': ['order_number', 'sku'],
        'key_map': {
            'order_number': 'Order number',
            'sku': 'SKU'
        },
        'metrics': [
            ('units', 'units', 'Units'),
            ('refunds', 'refunds', 'Refunds'),
            ('sales', 'sales', 'Sales'),
            ('promo', 'promo', 'Promo'),
            ('refund_cost', 'refund_cost', 'Refund сost'),
            ('amazon_fees', 'amazon_fees', 'Amazon fees'),
            ('cost_of_goods', 'cost_of_goods', 'Cost of Goods'),
            ('shipping', 'shipping', 'Shipping'),
            ('gross_profit', 'gross_profit', 'Gross profit'),
            ('net_profit', 'net_profit', 'Net profit'),
            ('margin', 'margin', 'Margin'),
            ('roi', 'roi', 'ROI'),
            ('expenses', 'expenses', 'Expenses'),
        ],
        'key_cleaning': {
            'order_number': make_clean_fn('order_number'),
            'sku': make_clean_fn('sku')
        }
    },
    'products': {
        'keys': ['sku', 'asin'],
        'key_map': {
            'sku': 'SKU',
            'asin': 'ASIN'
        },
        'metrics': [
            ('units', 'units', 'Units'),
            ('refunds', 'refunds', 'Refunds'),
            ('sales', 'sales', 'Sales'),
            ('promo', 'promo', 'Promo'),
            ('ads', 'ads', 'Ads'),
            ('sponsored_products', 'sponsored_products', 'Sponsored products (PPC)'),
            ('sponsored_display', 'sponsored_display', 'Sponsored Display'),
            ('sponsored_brands', 'sponsored_brands', 'Sponsored brands (HSA)'),
            ('sponsored_brands_video', 'sponsored_brands_video', 'Sponsored Brands Video'),
            ('google_ads', 'google_ads', 'Google\nads'),
            ('facebook_ads', 'facebook_ads', 'Facebook\nads'),
            ('refunds_pct', 'refunds_pct', '% Refunds'),
            ('sellable_quota', 'sellable_quota', 'Sellable Quota'),
            ('refund_cost', 'refund_cost', 'Refund сost'),
            ('amazon_fees', 'amazon_fees', 'Amazon fees'),
            ('cost_of_goods', 'cost_of_goods', 'Cost of Goods'),
            ('shipping', 'shipping', 'Shipping'),
            ('gross_profit', 'gross_profit', 'Gross profit'),
            ('net_profit', 'net_profit', 'Net profit'),
            ('estimated_payout', 'estimated_payout', 'Estimated payout'),
            ('expenses', 'expenses', 'Expenses'),
            ('margin', 'margin', 'Margin'),
            ('roi', 'roi', 'ROI'),
            ('bsr', 'bsr', 'BSR'),
            ('real_acos', 'real_acos', 'Real ACOS'),
            ('sessions', 'sessions', 'Sessions'),
            ('unit_session_pct', 'unit_session_pct', 'Unit Session Percentage'),
            ('average_sales_price', 'average_sales_price', 'Average Sales Price'),
        ],
        'key_cleaning': {
            'sku': make_clean_fn('sku'),
            'asin': make_clean_fn('asin')
        }
    }
}

def auto_detect_config(api_df, sb_df):
    api_cols = {canonicalize_col(c): c for c in api_df.columns}
    sb_cols = {canonicalize_col(c): c for c in sb_df.columns}
    
    common_canonicals = set(api_cols.keys()).intersection(set(sb_cols.keys()))
    potential_keys = ['order number', 'order id', 'sku', 'asin', 'id']
    
    keys = []
    key_map = {}
    for pk in potential_keys:
        if pk in common_canonicals:
            keys.append(pk.replace(' ', '_'))
            key_map[pk.replace(' ', '_')] = sb_cols[pk]
            
    if not keys:
        if 'sku' in api_cols:
            keys = ['sku']
            key_map = {'sku': 'SKU'}
        else:
            first_common = list(common_canonicals)[0] if common_canonicals else api_df.columns[0]
            keys = [first_common.replace(' ', '_')]
            key_map[keys[0]] = first_common
            
    metrics = []
    for c in common_canonicals:
        if c not in potential_keys and c != 'product' and c != 'date' and c != 'comment':
            metrics.append((c.replace(' ', '_'), api_cols[c], sb_cols[c]))
            
    return {
        'keys': keys,
        'key_map': key_map,
        'metrics': metrics,
        'key_cleaning': {k: make_clean_fn(k) for k in keys}
    }

API_DB_COLUMNS = {
    'order_items': [
        'order_number', 'order_date', 'product', 'asin', 'sku', 'units', 'refunds', 'sales', 'promo', 'sellable_quota', 
        'refund_cost', 'amazon_fees', 'cost_of_goods', 'shipping', 'gross_profit', 'expenses', 'net_profit', 'margin', 
        'roi', 'coupon', 'row_type', 'updated_at', 'fee_state', 'order_status', 'price_source'
    ],
    'products': [
        'period_start', 'period_end', 'product', 'asin', 'sku', 'units', 'refunds', 'sales', 'promo', 'ads', 
        'sponsored_products', 'sponsored_display', 'sponsored_brands', 'sponsored_brands_video', 'google_ads', 
        'facebook_ads', 'refunds_pct', 'sellable_quota', 'refund_cost', 'amazon_fees', 'cost_of_goods', 'shipping', 
        'gross_profit', 'net_profit', 'estimated_payout', 'expenses', 'margin', 'roi', 'bsr', 'real_acos', 
        'sessions', 'unit_session_pct', 'average_sales_price', 'updated_at', 'fee_state'
    ]
}

def analyze_status_breakdown(api_df, sb_df):
    from collections import defaultdict
    # Filter API to row_type == 'normal'
    row_type_col = 'row_type' if 'row_type' in api_df.columns else None
    if row_type_col:
        api_normal = api_df[api_df[row_type_col] == 'normal']
    else:
        api_normal = api_df
        
    new_data = {}
    order_col = 'order_number' if 'order_number' in api_df.columns else api_df.columns[0]
    sku_col = 'sku' if 'sku' in api_df.columns else None
    sales_col = 'sales' if 'sales' in api_df.columns else None
    fees_col = 'amazon_fees' if 'amazon_fees' in api_df.columns else None
    status_col = 'order_status' if 'order_status' in api_df.columns else None
    
    for _, r in api_normal.iterrows():
        oid = clean_order_number(r[order_col])
        sku = str(r[sku_col]).strip() if sku_col and not pd.isna(r[sku_col]) else ""
        new_data[(oid, sku)] = {
            "sales": clean_num(r[sales_col]) if sales_col else 0.0,
            "fees": clean_num(r[fees_col]) if fees_col else 0.0,
            "status": r[status_col] if status_col else "Unknown"
        }
        
    sb_data = {}
    sb_status = {}
    sb_order_col = find_column(sb_df, 'Order number')
    sb_sku_col = find_column(sb_df, 'SKU')
    sb_sales_col = find_column(sb_df, 'Sales')
    sb_fees_col = find_column(sb_df, 'Amazon fees')
    
    for _, r in sb_df.iterrows():
        raw = str(r[sb_order_col]) if sb_order_col else ""
        oid = clean_order_number(raw)
        sku = str(r[sb_sku_col]).strip() if sb_sku_col and not pd.isna(r[sb_sku_col]) else ""
        stt = raw.split(" / ")[1].strip() if " / " in raw else ""
        
        sb_data[(oid, sku)] = {
            "sales": clean_num(r[sb_sales_col]) if sb_sales_col else 0.0,
            "fees": clean_num(r[sb_fees_col]) if sb_fees_col else 0.0
        }
        sb_status[oid] = stt
        
    keys = set(new_data) | set(sb_data)
    
    agg = defaultdict(lambda: {"n": 0, "ns": 0.0, "nf": 0.0, "ss": 0.0, "sf": 0.0, "in_sb": 0})
    for k in keys:
        n = new_data.get(k)
        s = sb_data.get(k)
        st = n["status"] if n else "(chỉ có ở SB)"
        a = agg[st]
        a["n"] += 1
        if n:
            a["ns"] += n["sales"]
            a["nf"] += n["fees"]
        if s:
            a["ss"] += s["sales"]
            a["sf"] += s["fees"]
            a["in_sb"] += 1
            
    sbcnt = defaultdict(int)
    for v in sb_status.values():
        sbcnt[v] += 1
        
    lines = []
    lines.append("\n## ── Phân tích theo order_status (phía NEW) ──\n")
    lines.append("| Status | Số dòng | NEW Sales | SB Sales | NEW Fees | SB Fees | Số có ở SB |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    for st, a in sorted(agg.items()):
        lines.append(f"| {st} | {a['n']} | ${a['ns']:,.2f} | ${a['ss']:,.2f} | ${a['nf']:,.2f} | ${a['sf']:,.2f} | {a['in_sb']} |")
        
    lines.append("\n## ── Phân bổ status phía Sellerboard ──\n")
    lines.append("| Status SB | Số lượng |")
    lines.append("| :--- | :---: |")
    for k, v in sorted(sbcnt.items()):
        lines.append(f"| {k} | {v} |")
        
    new_sales_tot = sum(v['sales'] for v in new_data.values())
    new_fees_tot = sum(v['fees'] for v in new_data.values())
    sb_sales_tot = sum(v['sales'] for v in sb_data.values())
    sb_fees_tot = sum(v['fees'] for v in sb_data.values())
    
    lines.append("\n## ── Tổng cộng từ phân tích status ──\n")
    lines.append(f"- **NEW**: Sales = ${new_sales_tot:,.2f}, Fees = ${new_fees_tot:,.2f}")
    lines.append(f"- **SB**: Sales = ${sb_sales_tot:,.2f}, Fees = ${sb_fees_tot:,.2f}")
    
    return "\n".join(lines)

def process_pair(concept, api_path, sb_path, output_dir):
    print("\n" + "="*60)
    print(f"Reconciling: {concept.upper()}")
    print(f"API File: {api_path}")
    print(f"Sellerboard File: {sb_path}")
    
    concept_output_dir = os.path.join(output_dir, concept)
    os.makedirs(concept_output_dir, exist_ok=True)
    
    # Read files
    api_df = pd.read_excel(api_path, sheet_name=0)
    col_names_norm = [canonicalize_col(c) for c in api_df.columns]
    if 'sku' not in col_names_norm and len(api_df.columns) == len(API_DB_COLUMNS.get(concept, [])):
        print(f"Detected headerless Excel file for {concept}. Applying database schema columns.")
        api_df = pd.read_excel(api_path, sheet_name=0, header=None)
        api_df.columns = API_DB_COLUMNS[concept]

    sb_df = pd.read_excel(sb_path, sheet_name=0)
    
    print(f"Loaded {len(api_df)} rows from API and {len(sb_df)} rows from Sellerboard.")
    
    # Resolve config
    if concept in CONFIGS:
        cfg = CONFIGS[concept]
    else:
        print(f"Concept '{concept}' not found in predefined configs. Auto-detecting config...")
        cfg = auto_detect_config(api_df, sb_df)
        
    keys = cfg['keys']
    key_map = cfg['key_map']
    metrics = cfg['metrics']
    key_cleaning = cfg['key_cleaning']
    
    # 1. Clean and normalize keys
    api_keys_clean = []
    sb_keys_clean = []
    
    for key in keys:
        api_col = find_column(api_df, key)
        if api_col:
            clean_col = f"{key}_clean"
            api_df[clean_col] = api_df[api_col].apply(key_cleaning.get(key, lambda x: str(x).strip()))
            api_keys_clean.append(clean_col)
        else:
            print(f"Warning: Key column '{key}' not found in API file.")
            
        sb_target = key_map.get(key, key)
        sb_col = find_column(sb_df, sb_target)
        if sb_col:
            clean_col = f"{key}_clean"
            sb_df[clean_col] = sb_df[sb_col].apply(key_cleaning.get(key, lambda x: str(x).strip()))
            sb_keys_clean.append(clean_col)
        else:
            print(f"Warning: Key column '{sb_target}' not found in Sellerboard file.")
            
    common_keys_clean = list(set(api_keys_clean).intersection(set(sb_keys_clean)))
    if not common_keys_clean:
        print(f"Error: No matching key columns found between API and Sellerboard files for {concept}.")
        return
        
    # 2. Clean metric columns and collect names
    api_metrics_cols = []
    sb_metrics_cols = []
    metric_labels = []
    
    for label, api_target, sb_target in metrics:
        api_col = find_column(api_df, api_target)
        sb_col = find_column(sb_df, sb_target)
        
        if api_col or sb_col:
            metric_labels.append(label)
            
            api_metric_col = f"{label}_api"
            if api_col:
                api_df[api_metric_col] = api_df[api_col].apply(clean_num)
            else:
                api_df[api_metric_col] = 0.0
            api_metrics_cols.append(api_metric_col)
            
            sb_metric_col = f"{label}_sb"
            if sb_col:
                sb_df[sb_metric_col] = sb_df[sb_col].apply(clean_num)
            else:
                sb_df[sb_metric_col] = 0.0
            sb_metrics_cols.append(sb_metric_col)

    # 3. Group and aggregate
    api_grouped = api_df.groupby(common_keys_clean, as_index=False)[api_metrics_cols].sum()
    sb_grouped = sb_df.groupby(common_keys_clean, as_index=False)[sb_metrics_cols].sum()
    
    # 4. Merge
    merged = pd.merge(
        api_grouped,
        sb_grouped,
        on=common_keys_clean,
        how='outer'
    )
    
    # Fill NaN values
    for col in api_metrics_cols + sb_metrics_cols:
        merged[col] = merged[col].fillna(0.0)
        
    # 5. Delta Calculation and Rounding
    delta_cols = []
    for label in metric_labels:
        delta_col = f"delta_{label}"
        merged[delta_col] = merged[f"{label}_api"] - merged[f"{label}_sb"]
        merged[delta_col] = merged[delta_col].round(2)
        merged[f"{label}_api"] = merged[f"{label}_api"].round(2)
        merged[f"{label}_sb"] = merged[f"{label}_sb"].round(2)
        delta_cols.append(delta_col)
        
    # 6. Filter Mismatch Report
    mismatch_mask = pd.Series(False, index=merged.index)
    for delta_col in delta_cols:
        # Avoid checking mismatches on ratio/percentage columns which aren't simple aggregations
        label = delta_col.replace('delta_', '')
        if label in ['margin', 'roi', 'refunds_pct', 'unit_session_pct', 'real_acos']:
            continue
        mismatch_mask |= merged[delta_col].abs() > 0.01
        
    mismatch_report = merged[mismatch_mask].copy()
    
    # Export reports
    mismatch_report_path = os.path.join(concept_output_dir, "mismatch_report.csv")
    full_report_path = os.path.join(concept_output_dir, "full_reconciliation_report.csv")
    
    mismatch_report.to_csv(mismatch_report_path, index=False)
    merged.to_csv(full_report_path, index=False)
    
    print(f"Exported mismatch report to: {mismatch_report_path} ({len(mismatch_report)} rows)")
    print(f"Exported full report to: {full_report_path} ({len(merged)} rows)")
    
    # 7. Generate Markdown Summary
    summary_rows = []
    for label in metric_labels:
        api_sum = merged[f"{label}_api"].sum()
        sb_sum = merged[f"{label}_sb"].sum()
        
        # For ratio metrics like margin, roi, percentages, re-calculate at portfolio level
        if label in ['margin', 'roi', 'refunds_pct', 'unit_session_pct', 'real_acos']:
            # Avoid simple sum delta for percentages as it doesn't make sense mathematically
            delta = api_sum - sb_sum
            status = '✅ MATCH' if abs(delta) < 0.1 else '⚠️ DIFF'
        else:
            delta = api_sum - sb_sum
            mismatch_count = ((merged[f"{label}_api"] - merged[f"{label}_sb"]).abs() > 0.01).sum()
            status = "✅ MATCH" if mismatch_count == 0 else f"❌ {mismatch_count} MISMATCHES"
        
        summary_rows.append(
            f"| **{label.replace('_', ' ').title()}** | {format_val(label, api_sum)} | {format_val(label, sb_sum)} | {format_val(label, delta) if delta == 0 else ('+' if delta > 0 else '') + format_val(label, delta)} | {status} |"
        )
        
    summary_table_md = "\n".join(summary_rows)
    
    status_md = ""
    if concept == 'order_items':
        try:
            status_md = analyze_status_breakdown(api_df, sb_df)
        except Exception as e:
            status_md = f"\n*Error generating status breakdown: {e}*\n"
    
    markdown_report = f"""# Financial Reconciliation Report: {concept.upper()}

Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Summary Table

| Metric | API Output (System) | Sellerboard (Baseline) | Delta (API - SB) | Status |
| :--- | :---: | :---: | :---: | :---: |
{summary_table_md}

## Key Findings

1. **Total Rows Checked**: {len(merged)} rows.
2. **Discrepancies Found**: {len(mismatch_report)} rows with mismatch > $0.01.
3. **Observation**:
   - Check details of mismatched records in `mismatch_report.csv`.
{status_md}
"""
    
    summary_path = os.path.join(concept_output_dir, "reconciliation_summary.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(markdown_report)
        
    print(f"Written Markdown summary to: {summary_path}")
    print("\n" + "="*50)
    print(markdown_report)
    print("="*50)

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_dir = os.path.join(script_dir, "data", "input")
    output_dir = os.path.join(script_dir, "data", "output")
    
    os.makedirs(output_dir, exist_ok=True)
    
    print("--- Amazon FBA Financial Reconciliation Started ---")
    
    # 1. Dynamic File Discovery and Matching
    all_files = [f for f in os.listdir(input_dir) if f.endswith('.xlsx')]
    api_files = []
    sb_files = []
    for f in all_files:
        f_upper = f.upper()
        if f_upper.startswith('NEW_') or 'SUMMARY_' in f_upper:
            api_files.append(f)
        elif 'DR_HAI_' in f_upper or 'DASHBOARD_' in f_upper or 'SELLERBOARD' in f_upper or 'SB_' in f_upper:
            sb_files.append(f)
            
    print(f"Discovered {len(api_files)} API files and {len(sb_files)} Sellerboard files in {input_dir}.")
    
    matched_pairs = []
    for api_f in api_files:
        api_words = get_clean_words(api_f)
        if not api_words:
            continue
        best_sb_f = None
        best_score = -1
        for sb_f in sb_files:
            sb_words = get_clean_words(sb_f)
            score = len(api_words.intersection(sb_words))
            if score > best_score:
                best_score = score
                best_sb_f = sb_f
                
        if best_sb_f and best_score > 0:
            common_words = api_words.intersection(get_clean_words(best_sb_f))
            concept = '_'.join(sorted(list(common_words)))
            for kc in KNOWN_CONCEPTS:
                kc_words = set(kc.split('_'))
                if kc_words.issubset(common_words) or common_words.issubset(kc_words):
                    concept = kc
                    break
            matched_pairs.append({
                'concept': concept,
                'api_file': api_f,
                'sb_file': best_sb_f
            })
            
    if not matched_pairs:
        print("No matching file pairs found to compare.")
        sys.exit(0)
        
    print(f"Successfully matched {len(matched_pairs)} file pairs for comparison:")
    for pair in matched_pairs:
        print(f" - [{pair['concept'].upper()}]: API={pair['api_file']} <-> SB={pair['sb_file']}")
        
    # 2. Run Reconciliation for each matched pair
    for pair in matched_pairs:
        concept = pair['concept']
        api_path = os.path.join(input_dir, pair['api_file'])
        sb_path = os.path.join(input_dir, pair['sb_file'])
        try:
            process_pair(concept, api_path, sb_path, output_dir)
        except Exception as e:
            print(f"Error processing reconciliation for {concept}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()

