from fastapi import APIRouter

from . import auth, coffee_subscriptions, orders, products, reviews, subscriptions

router = APIRouter(prefix="/api/admin", tags=["admin"])
router.include_router(auth.router)
router.include_router(products.router)
router.include_router(orders.router)
router.include_router(subscriptions.router)
router.include_router(coffee_subscriptions.router)
router.include_router(reviews.router)
