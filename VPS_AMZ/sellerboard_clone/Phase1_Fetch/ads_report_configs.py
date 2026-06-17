"""Phase1_Fetch — Định nghĩa TẤT CẢ report config của Ads API ở 1 nơi.

Mỗi report type chỉ gọi 1 LẦN, lưu 1 file. Cột là HỢP của những gì cả 2
dashboard (profit + PPC) cần — upload script mỗi bên tự lấy cột mình dùng.

Phân loại theo người tiêu thụ (consumer):
  - profit: spCampaigns (phân bổ ad spend tầng 3), spAdvertisedProduct (tầng 1),
            sbCampaigns, sdCampaigns.
  - ppc:    spCampaigns, spAdGroups, spKeywords, spTargeting, spSearchTerm,
            spCampaigns-placement (topOfSearch%).
spCampaigns dùng CHUNG cho cả 2 → chỉ fetch 1 lần.
"""

# ── SP Campaigns (DÙNG CHUNG profit + ppc) ────────────────────────────────────
SP_CAMPAIGNS = {
    "adProduct":    "SPONSORED_PRODUCTS",
    "reportTypeId": "spCampaigns",
    "groupBy":      ["campaign"],
    "columns": [
        "campaignId", "campaignName", "campaignStatus", "campaignBiddingStrategy",
        "impressions", "clicks", "cost",
        "purchases1d", "purchases7d", "purchases14d", "purchases30d",
        "sales1d", "sales7d", "sales14d", "sales30d",
        "unitsSoldClicks1d", "unitsSoldClicks7d", "unitsSoldClicks14d",
        "attributedSalesSameSku14d", "roasClicks14d",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

# ── SP Campaigns segmented theo placement (ppc — topOfSearch%) ────────────────
SP_PLACEMENT = {
    "adProduct":    "SPONSORED_PRODUCTS",
    "reportTypeId": "spCampaigns",
    "groupBy":      ["campaign", "campaignPlacement"],
    "columns": [
        "campaignId", "campaignName", "placementClassification",
        "impressions", "clicks", "cost",
        "purchases14d", "sales14d",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

# ── SP Advertised Product (profit — Tầng 1 phân bổ ad spend cấp SKU/ASIN) ──────
SP_ADVERTISED_PRODUCT = {
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

# ── SP Ad Groups (ppc) ────────────────────────────────────────────────────────
SP_ADGROUPS = {
    "adProduct":    "SPONSORED_PRODUCTS",
    "reportTypeId": "spAdGroups",
    "groupBy":      ["adGroup"],
    "columns": [
        "campaignId", "campaignName", "adGroupId", "adGroupName", "adGroupStatus",
        "impressions", "clicks", "cost",
        "purchases1d", "purchases7d", "purchases14d",
        "sales1d", "sales7d", "sales14d",
        "unitsSoldClicks1d", "unitsSoldClicks14d", "attributedSalesSameSku14d",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

# ── SP Keywords (ppc) ─────────────────────────────────────────────────────────
SP_KEYWORDS = {
    "adProduct":    "SPONSORED_PRODUCTS",
    "reportTypeId": "spKeywords",
    "groupBy":      ["keyword"],
    "columns": [
        "campaignId", "campaignName", "adGroupId", "adGroupName",
        "keywordId", "keyword", "keywordType", "matchType",
        "impressions", "clicks", "cost",
        "purchases1d", "purchases7d", "purchases14d",
        "sales1d", "sales7d", "sales14d",
        "unitsSoldClicks1d", "unitsSoldClicks14d", "attributedSalesSameSku14d",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

# ── SP Targeting (ppc — product/ASIN/auto targets) ────────────────────────────
SP_TARGETING = {
    "adProduct":    "SPONSORED_PRODUCTS",
    "reportTypeId": "spTargeting",
    "groupBy":      ["targeting"],
    "columns": [
        "campaignId", "campaignName", "adGroupId", "adGroupName",
        "targetId", "targeting", "targetingType", "matchType",
        "impressions", "clicks", "cost",
        "purchases1d", "purchases7d", "purchases14d",
        "sales1d", "sales7d", "sales14d",
        "unitsSoldClicks1d", "unitsSoldClicks14d",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

# ── SP Search Term (ppc) ──────────────────────────────────────────────────────
SP_SEARCHTERM = {
    "adProduct":    "SPONSORED_PRODUCTS",
    "reportTypeId": "spSearchTerm",
    "groupBy":      ["searchTerm"],
    "columns": [
        "campaignId", "campaignName", "adGroupId", "adGroupName",
        "keywordId", "keyword", "matchType", "searchTerm",
        "impressions", "clicks", "cost",
        "purchases1d", "purchases7d", "purchases14d",
        "sales1d", "sales7d", "sales14d",
        "unitsSoldClicks1d", "unitsSoldClicks14d", "attributedSalesSameSku14d",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

# ── SB / SD Campaigns (profit — phân bổ ad spend các kênh khác) ────────────────
SB_CAMPAIGNS = {
    "adProduct":    "SPONSORED_BRANDS",
    "reportTypeId": "sbCampaigns",
    "groupBy":      ["campaign"],
    "columns": [
        "campaignId", "campaignName", "campaignStatus",
        "impressions", "clicks", "cost", "date",
        "purchases", "purchasesPromoted",
        "detailPageViews", "brandedSearches",
        "newToBrandPurchases", "newToBrandSales",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}

SD_CAMPAIGNS = {
    "adProduct":    "SPONSORED_DISPLAY",
    "reportTypeId": "sdCampaigns",
    "groupBy":      ["campaign"],
    "columns": [
        "campaignId", "campaignName", "campaignStatus",
        "impressions", "clicks", "cost", "date",
        "purchases", "sales",
    ],
    "timeUnit": "DAILY",
    "format":   "GZIP_JSON",
}


# (file_key, report_name, config, consumers) — file_key = tên file lưu trong data/ads_reports/
REPORT_JOBS = [
    ("sp_campaigns",          "SP-Campaigns",      SP_CAMPAIGNS,          ("profit", "ppc")),
    ("sp_placement",          "SP-Placement",      SP_PLACEMENT,          ("ppc",)),
    ("sp_advertised_product", "SP-AdvertisedProd", SP_ADVERTISED_PRODUCT, ("profit",)),
    ("sp_adgroups",           "SP-AdGroups",       SP_ADGROUPS,           ("ppc",)),
    ("sp_keywords",           "SP-Keywords",       SP_KEYWORDS,           ("ppc",)),
    ("sp_targeting",          "SP-Targeting",      SP_TARGETING,          ("ppc",)),
    ("sp_searchterm",         "SP-SearchTerm",     SP_SEARCHTERM,         ("ppc",)),
    ("sb_campaigns",          "SB-Campaigns",      SB_CAMPAIGNS,          ("profit",)),
    ("sd_campaigns",          "SD-Campaigns",      SD_CAMPAIGNS,          ("profit",)),
]
