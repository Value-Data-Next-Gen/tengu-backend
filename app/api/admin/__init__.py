from fastapi import APIRouter

from . import auth, categories, coffee_subscriptions, orders, products, reviews, site, subscriptions

router = APIRouter(prefix="/api/admin", tags=["admin"])
router.include_router(auth.router)
router.include_router(products.router)
router.include_router(categories.router)
router.include_router(orders.router)
router.include_router(subscriptions.router)
router.include_router(coffee_subscriptions.router)
router.include_router(reviews.router)
router.include_router(site.router)
