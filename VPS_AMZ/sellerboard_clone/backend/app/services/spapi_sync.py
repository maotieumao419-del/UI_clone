from __future__ import annotations
import hashlib
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from ..config import settings
from ..models import Order, OrderItem, Product, User
from .amazon_client import AmazonAPIError, sp_get

def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)

def _anon(customer_id: str) -> str:
    return hashlib.sha256(customer_id.encode()).hexdigest()[:16]

def _get_or_create_product(db: Session, owner_id: int, asin: str, sku: str, title: str, price: float) -> Product:
    p = db.query(Product).filter_by(owner_id=owner_id, asin=asin).first()
    if not p:
        p = Product(owner_id=owner_id, asin=asin, sku=sku or asin, title=title or asin, marketplace="amazon", price=price)
        db.add(p)
        db.flush()
    return p

def sync_orders(db: Session, owner: User, days: int | None = None) -> dict:
    days = days or settings.SPAPI_SYNC_DAYS
    created_after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    orders_created = orders_skipped = items_created = 0
    errors = []
    next_token = None
    page = 0

    while True:
        page += 1
        try:
            if next_token:
                data = sp_get("/orders/v0/orders", {"NextToken": next_token, "MarketplaceIds": settings.SPI_MARKETPLACE_ID})
            else:
                data = sp_get("/orders/v0/orders", {
                    "MarketplaceIds": settings.SPI_MARKETPLACE_ID,
                    "CreatedAfter": created_after,
                    "OrderStatuses": "Shipped,Unshipped,PartiallyShipped,Canceled",
                })
        except AmazonAPIError as e:
            errors.append(str(e))
            break

        payload = data.get("payload", {})
        for ao in payload.get("Orders", []):
            ext_id = ao.get("AmazonOrderId", "")
            if db.query(Order).filter_by(external_id=ext_id, owner_id=owner.id).first():
                orders_skipped += 1
                continue
            try:
                items_data = sp_get(f"/orders/v0/orders/{ext_id}/orderItems")
                amazon_items = items_data.get("payload", {}).get("OrderItems", [])
            except AmazonAPIError as e:
                errors.append(f"OrderItems {ext_id}: {e}")
                continue

            purchased_at = _utc(ao.get("PurchaseDate", datetime.utcnow().isoformat()))
            is_refunded = ao.get("OrderStatus") == "Canceled"
            buyer_id = ao.get("BuyerInfo", {}).get("BuyerEmail", ext_id)
            order = Order(
                owner_id=owner.id, external_id=ext_id, marketplace="amazon",
                customer_ref=_anon(buyer_id), purchased_at=purchased_at,
                status=ao.get("OrderStatus", "shipped").lower(),
                is_refunded=is_refunded, ppc_cost=0.0,
            )
            db.add(order)
            db.flush()
            orders_created += 1

            for ai in amazon_items:
                asin = ai.get("ASIN", "")
                sku = ai.get("SellerSKU", asin)
                title = ai.get("Title", asin)
                qty = int(ai.get("QuantityOrdered", 1))
                price_info = ai.get("ItemPrice", {})
                amount = float(price_info.get("Amount", 0)) if price_info else 0.0
                unit_price = (amount / qty) if qty else 0.0
                product = _get_or_create_product(db, owner.id, asin, sku, title, unit_price)
                db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=qty, unit_price=unit_price))
                items_created += 1

        db.commit()
        next_token = payload.get("NextToken")
        if not next_token:
            break

    return {"pages_fetched": page, "orders_created": orders_created, "orders_skipped": orders_skipped, "items_created": items_created, "errors": errors}
