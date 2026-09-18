from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    banners,
    blog,
    certifications,
    contact_requests,
    content,
    curriculum,
    enrollments,
    matching,
    orientation,
    quizzes,
    reviews,
    stats,
    taxonomy,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(taxonomy.router, prefix="/taxonomy", tags=["taxonomy"])
api_router.include_router(curriculum.router, prefix="/curriculum", tags=["curriculum"])
api_router.include_router(enrollments.router, prefix="/enrollments", tags=["enrollments"])
api_router.include_router(quizzes.router, prefix="/quizzes", tags=["quizzes"])
api_router.include_router(certifications.router, prefix="/certifications", tags=["certifications"])
api_router.include_router(matching.router, prefix="/matching", tags=["matching"])
api_router.include_router(content.router, prefix="/content", tags=["content"])
api_router.include_router(blog.router, prefix="/blog", tags=["blog"])
api_router.include_router(banners.router, prefix="/banners", tags=["banners"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(contact_requests.router, prefix="/contact-requests", tags=["contact-requests"])
api_router.include_router(stats.router, prefix="/stats", tags=["stats"])
api_router.include_router(orientation.router, prefix="/orientation", tags=["orientation"])
