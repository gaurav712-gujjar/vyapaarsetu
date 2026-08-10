from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Product, Category
from ..schemas import ProductOut, CategoryOut, ProductCreate
from ..deps import require_admin

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/categories", response_model=List[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.query(Category).all()


@router.get("/products", response_model=List[ProductOut])
def list_products(category: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Product).options(joinedload(Product.category)).filter(Product.is_active == True)  # noqa: E712
    if category:
        q = q.join(Category).filter(Category.slug == category)
    return q.order_by(Product.id.desc()).all()


@router.post("/admin/products", response_model=ProductOut)
def create_product(payload: ProductCreate, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    category = db.query(Category).filter(Category.id == payload.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    product = Product(**payload.dict())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.delete("/admin/products/{product_id}")
def deactivate_product(product_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.is_active = False
    db.commit()
    return {"ok": True}
