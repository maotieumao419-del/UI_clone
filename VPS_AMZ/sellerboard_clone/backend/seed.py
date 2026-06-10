"""Tạo dữ liệu mẫu để demo nhanh dashboard.

Chạy:  python seed.py   (từ thư mục backend/, sau khi đã cài requirements)
Tạo tài khoản demo:  demo@sellervision.io / demo1234
"""
import hashlib
import random
from datetime import timedelta

from app.core.security import hash_password
from app.timeutils import now_utc
from app.database import Base, SessionLocal, engine
from app.models import (
    Alert,
    BsrSnapshot,
    InventoryBatch,
    ListingSnapshot,
    Order,
    OrderItem,
    Product,
    ReimbursementCase,
    User,
)

random.seed(42)
NOW = now_utc()

PRODUCTS = [
    # asin, sku, title, price, stock, inbound, cost, marketplace, category, season_pop
    ("B0DEMO0001", "SV-KNIFE-01", "Bộ dao bếp thép không gỉ 6 món", 49.99, 320, 0, 14.5, "amazon", "Kitchen", 1.4),
    ("B0DEMO0002", "SV-YOGA-02", "Thảm tập yoga chống trượt 8mm", 29.99, 90, 200, 8.2, "amazon", "Sports", 1.0),
    ("B0DEMO0003", "SV-LED-03", "Đèn LED dây thông minh 10m RGB", 24.99, 45, 0, 6.8, "amazon", "Home", 1.2),
    ("B0DEMO0004", "SV-BOTL-04", "Bình giữ nhiệt inox 1L", 19.99, 600, 0, 5.1, "shopify", "Outdoor", 0.9),
    ("B0DEMO0005", "SV-EARB-05", "Tai nghe Bluetooth TWS Pro", 59.99, 18, 0, 19.0, "amazon", "Electronics", 1.3),
    ("B0DEMO0006", "SV-DESK-06", "Đèn bàn LED chống cận", 34.99, 150, 100, 9.9, "walmart", "Home", 1.1),
]


def main():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    user = User(
        email="demo@sellervision.io",
        full_name="Người bán Demo",
        hashed_password=hash_password("demo1234"),
        consent={"analytics": True, "marketing": False, "data_sharing": False},
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    products = []
    for asin, sku, title, price, stock, inbound, cost, market, cat, pop in PRODUCTS:
        p = Product(
            owner_id=user.id, asin=asin, sku=sku, title=title, price=price,
            current_stock=stock, inbound_stock=inbound, marketplace=market, category=cat,
            referral_fee_pct=0.15, fba_fee_per_unit=round(price * 0.07 + 2, 2),
            lead_time_manufacture_days=random.choice([15, 20, 25]),
            lead_time_shipping_days=random.choice([20, 25, 30]),
            lead_time_prep_days=5, safety_stock_days=14,
        )
        db.add(p)
        products.append((p, cost, pop))
    db.commit()
    for p, _, _ in products:
        db.refresh(p)

    # Lô nhập (FIFO): 2-3 lô giá vốn tăng dần theo thời gian
    for p, cost, _ in products:
        for i, days_ago in enumerate([120, 70, 25]):
            db.add(InventoryBatch(
                product_id=p.id,
                received_at=NOW - timedelta(days=days_ago),
                quantity=random.randint(300, 700),
                unit_cost=round(cost * (1 + 0.04 * i), 2),
            ))
    db.commit()

    # Đơn hàng 90 ngày, có xu hướng tăng nhẹ + nhiễu ngẫu nhiên theo độ phổ biến
    customer_pool = [hashlib.sha256(f"cust{i}".encode()).hexdigest()[:16] for i in range(120)]
    for day in range(90, -1, -1):
        date = NOW - timedelta(days=day)
        trend = 1 + (90 - day) / 300  # tăng dần theo thời gian
        for p, cost, pop in products:
            base = 3 * pop * trend
            n_orders = max(0, int(random.gauss(base, base * 0.4)))
            for _ in range(n_orders):
                qty = random.choices([1, 1, 1, 2, 3], weights=[6, 3, 2, 2, 1])[0]
                refunded = random.random() < 0.04
                order = Order(
                    owner_id=user.id,
                    external_id=f"AMZ-{day}-{p.id}-{random.randint(1000, 9999)}",
                    marketplace=p.marketplace,
                    customer_ref=random.choice(customer_pool),
                    purchased_at=date - timedelta(hours=random.randint(0, 23)),
                    status="refunded" if refunded else "shipped",
                    ppc_cost=round(p.price * qty * random.uniform(0.05, 0.18), 2),
                    is_refunded=refunded,
                    refund_returned=(random.random() < 0.7) if refunded else True,
                )
                order.items.append(OrderItem(
                    product_id=p.id, quantity=qty,
                    unit_price=round(p.price * random.uniform(0.95, 1.0), 2),
                ))
                db.add(order)
        if day % 15 == 0:
            db.commit()
    db.commit()

    # BSR snapshots (xu hướng cải thiện dần)
    for p, _, pop in products:
        bsr = random.randint(8000, 60000)
        for day in range(30, -1, -1):
            bsr = max(500, int(bsr * random.uniform(0.95, 1.03)))
            db.add(BsrSnapshot(product_id=p.id, captured_at=NOW - timedelta(days=day), bsr=bsr))
    db.commit()

    # Listing snapshots: tạo 2 mốc, mốc mới có vài thay đổi để sinh cảnh báo
    for idx, (p, _, _) in enumerate(products):
        old = {
            "title": p.title, "main_image": f"img_{p.asin}_v1.jpg",
            "dimensions": "20x15x8 cm", "referral_fee_pct": 0.15,
            "buybox_owner": p.sku, "sellers": [p.sku],
        }
        new = dict(old)
        if idx == 0:  # đổi ảnh chính
            new["main_image"] = f"img_{p.asin}_v2.jpg"
        if idx == 2:  # mất buy box + hijacker
            new["buybox_owner"] = "SELLER_X"
            new["sellers"] = [p.sku, "SELLER_X", "HIJACK_99"]
        if idx == 4:  # tăng phí giới thiệu
            new["referral_fee_pct"] = 0.17
        db.add(ListingSnapshot(product_id=p.id, captured_at=NOW - timedelta(days=2), data=old))
        db.add(ListingSnapshot(product_id=p.id, captured_at=NOW, data=new))
    db.commit()

    # Sinh sẵn cảnh báo & hồ sơ bồi thường để dashboard có dữ liệu ngay
    from app.services.alerts import build_reimbursement_report, scan_listing_changes
    scan_listing_changes(db, user.id)
    build_reimbursement_report(db, user.id)

    counts = {
        "products": db.query(Product).count(),
        "orders": db.query(Order).count(),
        "order_items": db.query(OrderItem).count(),
        "alerts": db.query(Alert).count(),
        "reimbursements": db.query(ReimbursementCase).count(),
    }
    db.close()
    print("[OK] Seed xong. Dang nhap: demo@sellervision.io / demo1234")
    print("  Thong ke:", counts)


if __name__ == "__main__":
    main()
