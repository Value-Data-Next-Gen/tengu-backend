from fastapi import APIRouter

from . import auth, orders, products, subscriptions

router = APIRouter(prefix="/api/admin", tags=["admin"])
router.include_router(auth.router)
router.include_router(products.router)
router.include_router(orders.router)
router.include_router(subscriptions.router)
