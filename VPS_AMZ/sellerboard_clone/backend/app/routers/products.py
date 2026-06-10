"""Router quản lý sản phẩm (catalog) của người bán."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Product, User
from ..schemas.schemas import ProductCreate, ProductOut

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return db.scalars(select(Product).where(Product.owner_id == current.id).order_by(Product.id)).all()


@router.post("", response_model=ProductOut, status_code=201)
def create_product(payload: ProductCreate, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    product = Product(owner_id=current.id, **payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    product = db.scalar(select(Product).where(Product.id == product_id, Product.owner_id == current.id))
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    return product


@router.put("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, payload: ProductCreate,
                   db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    product = db.scalar(select(Product).where(Product.id == product_id, Product.owner_id == current.id))
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    for k, v in payload.model_dump().items():
        setattr(product, k, v)
    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    product = db.scalar(select(Product).where(Product.id == product_id, Product.owner_id == current.id))
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")
    db.delete(product)
    db.commit()
