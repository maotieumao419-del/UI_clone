#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Post-Ingestion Data Cleaning & Deduplication Script (End of Phase 1)

This script:
1. Connects to the Supabase database using psycopg.
2. Identifies duplicate rows on business keys for NEW_* buffer tables.
3. Purges duplicate records, keeping the latest one based on timestamp & tie-breaker columns.
4. Creates descending indexes and clusters tables to maintain reverse chronological order.
5. Measures execution stats and prints a clean markdown log report.
6. Runs garbage collection after each table to maintain memory safety.
"""

import sys
# Set standard streams encoding to UTF-8
for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import os
import gc
import time
from dotenv import dotenv_values
import psycopg

# Table configuration mapping
# Mapping the target buffer tables, their business composite keys, and chronological fields
TABLES_CONFIG = [
    {
        "table": "Profit_Phase1_sp_orders",
        "composite_keys": ["order_id"],
        "timestamp_col": "purchase_date",
        "default_tiebreaker": "synced_at"
    },
    {
        "table": "Profit_Phase1_sp_order_items",
        "composite_keys": ["order_id", "sku", "asin"],
        "timestamp_col": "synced_at",
        "default_tiebreaker": "id"
    },
    {
        "table": "Profit_Phase1_fin_item_fees",
        "composite_keys": ["order_id", "sku", "asin", "fee_type"],
        "timestamp_col": "posted_date",
        "default_tiebreaker": "synced_at"
    },
    {
        "table": "Profit_Phase1_fin_refunds",
        "composite_keys": ["order_id", "sku", "posted_date"],
        "timestamp_col": "posted_date",
        "default_tiebreaker": "synced_at"
    },
    {
        "table": "Profit_Phase1_fin_adjustments",
        "composite_keys": ["posted_date", "adjustment_type", "sku", "asin", "amount"],
        "timestamp_col": "posted_date",
        "default_tiebreaker": "synced_at"
    },
    {
        "table": "Profit_Phase1_ads_campaigns_daily",
        "composite_keys": ["report_date", "campaign_id", "ad_product"],
        "timestamp_col": "report_date",
        "default_tiebreaker": "synced_at"
    },
    {
        "table": "Profit_Phase1_ads_sp_asin_daily",
        "composite_keys": ["report_date", "campaign_id", "ad_group_id", "advertised_sku"],
        "timestamp_col": "report_date",
        "default_tiebreaker": "synced_at"
    }
]

def load_db_url():
    """Finds and loads the DATABASE_URL environment variable from .env files."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, ".env"),                     # Phase1_Ingestion/.env
        os.path.abspath(os.path.join(script_dir, "..", ".env")), # sellerboard_clone/.env
        os.path.abspath(os.path.join(script_dir, "..", "backend", ".env")), # sellerboard_clone/backend/.env
        os.path.abspath(os.path.join(script_dir, "backend", ".env")), # fallback
    ]
    
    for path in candidates:
        if os.path.exists(path):
            env_vals = dotenv_values(path)
            url = env_vals.get("DATABASE_URL")
            if url:
                return url
                
    url = os.getenv("DATABASE_URL")
    if url:
        return url
        
    raise ValueError("Could not locate DATABASE_URL in any of the .env files or OS environment variables.")

def get_table_columns(cur, table_name):
    """Retrieves all columns in the specified table from PostgreSQL schema metadata."""
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table_name,)
    )
    return {r[0] for r in cur.fetchall()}

def process_table_cleanup(conn, config):
    """Cleans, deduplicates, indexes, and clusters a single table."""
    table_name = config["table"]
    composite_keys = config["composite_keys"]
    timestamp_col = config["timestamp_col"]
    
    start_time = time.time()
    
    with conn.cursor() as cur:
        # Check if table exists
        cur.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s)",
            (table_name,)
        )
        if not cur.fetchone()[0]:
            # Table does not exist, return default indicators
            return None
            
        # 1. Fetch initial row count
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        orig_count = cur.fetchone()[0]
        
        # 2. Inspect available columns
        columns = get_table_columns(cur, table_name)
        
        # Choose id_col (id column if exists, otherwise order_id, or ctid as generic postgres row identifier)
        if "id" in columns:
            id_col = "id"
        elif "order_id" in columns:
            id_col = "order_id"
        else:
            id_col = "ctid"
            
        # Determine the tie-breaker column for newest records (updated_at -> synced_at -> default_tiebreaker)
        if "updated_at" in columns:
            tiebreaker_col = "updated_at"
        elif "synced_at" in columns:
            tiebreaker_col = "synced_at"
        elif config["default_tiebreaker"] in columns:
            tiebreaker_col = config["default_tiebreaker"]
        else:
            # Fallback to id_col if nothing else matches
            tiebreaker_col = id_col
            
        # Format keys for Partition By clause
        partition_clause = ", ".join(f'"{key}"' for key in composite_keys)
        
        # 3. Apply memory-safe CTE window deduplication
        # Kept row_num = 1 as the newest / highest state record, deleting others
        dedup_sql = f"""
        WITH RankedRows AS (
            SELECT "{id_col}", 
                   ROW_NUMBER() OVER(
                       PARTITION BY {partition_clause} 
                       ORDER BY "{timestamp_col}" DESC, "{tiebreaker_col}" DESC
                   ) as row_num
            FROM "{table_name}"
        )
        DELETE FROM "{table_name}"
        WHERE "{id_col}" IN (SELECT "{id_col}" FROM RankedRows WHERE row_num > 1);
        """
        cur.execute(dedup_sql)
        
        # 4. Fetch row count after deduplication
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        final_count = cur.fetchone()[0]
        purged = orig_count - final_count
        
        # 5. Create descending index for reverse chronological ordering
        index_name = f"idx_{table_name}_{timestamp_col}_desc"
        cur.execute(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table_name}" ("{timestamp_col}" DESC);')
        
        # 6. Cluster table to physically reorganize rows in DESC order
        cur.execute(f'CLUSTER "{table_name}" USING "{index_name}";')
        
        # 7. Update query planner statistics
        cur.execute(f'ANALYZE "{table_name}";')
        
    duration_ms = int((time.time() - start_time) * 1000)
    
    return {
        "table": table_name,
        "original_count": orig_count,
        "purged_count": purged,
        "final_count": final_count,
        "time_ms": duration_ms
    }

def main():
    print("⏳ Starting database buffer cleanup and deduplication process...")
    
    try:
        url = load_db_url()
        # Clean URL format for psycopg v3 connection compatibility
        url = url.replace("postgresql+psycopg://", "postgresql://")
    except Exception as exc:
        print(f"❌ Initialization Error: {exc}")
        sys.exit(1)
        
    report = []
    
    # Establish connection with autocommit enabled to allow CLUSTER commands
    try:
        # prepare_threshold=None: tắt server-side prepared statements — cần
        # thiết khi DATABASE_URL đi qua Supabase pooler (transaction-mode,
        # port 6543), nơi PgBouncer có thể route sang backend connection đã
        # có sẵn prepared statement cùng tên ("_pg3_0"...) gây lỗi
        # "prepared statement already exists".
        with psycopg.connect(url, autocommit=True, connect_timeout=30, prepare_threshold=None) as conn:
            for config in TABLES_CONFIG:
                table_name = config["table"]
                print(f"🧹 Cleaning {table_name}...")
                
                try:
                    stats = process_table_cleanup(conn, config)
                    if stats:
                        report.append(stats)
                        print(f"   Done in {stats['time_ms']}ms. Purged: {stats['purged_count']} rows.")
                    else:
                        print(f"   ⚠️ Table {table_name} does not exist in database. Skipping.")
                except Exception as exc:
                    print(f"   ❌ Error cleaning {table_name}: {exc}")
                    
                # Strict garbage collection after each table
                gc.collect()
                
    except Exception as conn_exc:
        print(f"❌ Database Connection Failure: {conn_exc}")
        sys.exit(1)
        
    # Print markdown table report to stdout
    print("\n## PHASE 1 POST-INGESTION CLEANUP & DEDUPLICATION REPORT\n")
    print("| Table Name | Original Row Count | Rows Purged (Duplicates Deleted) | Final Cleaned Row Count | Processing Execution Time (ms) |")
    print("| :--- | :---: | :---: | :---: | :---: |")
    for row in report:
        print(f"| `{row['table']}` | {row['original_count']:,} | {row['purged_count']:,} | {row['final_count']:,} | {row['time_ms']:,} ms |")
    print("")
    
    print("✅ All buffers deduplicated, sorted, and clustered successfully.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
