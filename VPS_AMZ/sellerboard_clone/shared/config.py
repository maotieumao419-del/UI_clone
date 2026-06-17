"""Shared — env loader, constants, marketplace mapping.

Import:
    from shared.config import ADS_BASE, ADS_PROFILE_ID, MARKETPLACE_ID, CHUNK_SIZE
"""
import os

from dotenv import load_dotenv

load_dotenv()

# ── Ads API ────────────────────────────────────────────────────────────────────
ADS_BASE      = "https://advertising-api.amazon.com"
ADS_CLIENT_ID = (os.getenv("AMAZON_ADS_CLIENT_ID", "")
                 or os.getenv("AMAZON_SPI_CLIENT_ID", ""))
ADS_PROFILE_ID = os.getenv("ADS_PROFILE_ID", "")

POLL_INTERVAL = int(os.getenv("ADS_POLL_INTERVAL_SECONDS", "15"))
POLL_TIMEOUT  = int(os.getenv("ADS_POLL_TIMEOUT_SECONDS", "600"))
REQUEST_GAP   = float(os.getenv("ADS_REQUEST_GAP_SECONDS", "20"))

# ── SP-API ─────────────────────────────────────────────────────────────────────
SP_BASE        = "https://sellingpartnerapi-na.amazon.com"
MARKETPLACE_ID = os.getenv("AMAZON_SPI_MARKETPLACE_ID", "ATVPDKIKX0DER")

# ── Supabase ───────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_KEY", "")

# ── General ────────────────────────────────────────────────────────────────────
CHUNK_SIZE       = 100
SELLER_TIMEZONE  = os.getenv("SELLER_TIMEZONE", "America/Los_Angeles")
MARKETPLACE_LABEL = os.getenv("MARKETPLACE_LABEL", "Amazon.com")

# ── Mapping ad_product -> label ────────────────────────────────────────────────
AD_PRODUCT_LABEL = {
    "SPONSORED_PRODUCTS": "SP",
    "SPONSORED_BRANDS":   "SB",
    "SPONSORED_DISPLAY":  "SD",
}
