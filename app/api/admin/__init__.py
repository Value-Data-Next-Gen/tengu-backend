from fastapi import APIRouter

from . import abandoned_carts, auth, categories, coffee_subscriptions, discount_codes, hero, horeca, orders, posts, products, reviews, site, subscriptions, uploads

router = APIRouter(prefix="/api/admin", tags=["admin"])
router.include_router(auth.router)
router.include_router(products.router)
router.include_router(categories.router)
router.include_router(orders.router)
router.include_router(subscriptions.router)
router.include_router(coffee_subscriptions.router)
router.include_router(reviews.router)
router.include_router(abandoned_carts.router)
router.include_router(discount_codes.router)
router.include_router(site.router)
router.include_router(posts.router)
router.include_router(uploads.router)
router.include_router(hero.router)
router.include_router(horeca.router)
