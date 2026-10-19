from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin_access,
    admin_auth,
    auth,
    bookings,
    blog,
    certifications,
    contact_requests,
    payments,
    quotes,
    admin_resources,
    admin_settings,
    configuration,
    content,
    curriculum,
    directory,
    enrollment_forms,
    enrollments,
    home,
    legacy_category,
    matching,
    orientation,
    provider_account,
    provider_services,
    provider_space,
    provider_work,
    admin_dashboard,
    admin_vendors,
    providers,
    quizzes,
    reviews,
    stats,
    taxonomy,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin_auth.router, prefix="/auth/admin", tags=["admin-auth"])
api_router.include_router(admin_access.router, prefix="/access", tags=["admin-access"])
api_router.include_router(taxonomy.router, prefix="/taxonomy", tags=["taxonomy"])
api_router.include_router(curriculum.router, prefix="/curriculum", tags=["curriculum"])
api_router.include_router(enrollments.router, prefix="/enrollments", tags=["enrollments"])
api_router.include_router(quizzes.router, prefix="/quizzes", tags=["quizzes"])
api_router.include_router(certifications.router, prefix="/certifications", tags=["certifications"])
api_router.include_router(matching.router, prefix="/matching", tags=["matching"])
api_router.include_router(content.router, prefix="/content", tags=["content"])
api_router.include_router(blog.router, prefix="/blog", tags=["blog"])
api_router.include_router(bookings.router, prefix="/bookings", tags=["bookings"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(admin_settings.router, prefix="/admin-settings", tags=["admin-settings"])
api_router.include_router(admin_resources.router, prefix="/admin-resources", tags=["admin-resources"])
api_router.include_router(quotes.router, prefix="/quotes", tags=["quotes"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(contact_requests.router, prefix="/contact-requests", tags=["contact-requests"])
api_router.include_router(stats.router, prefix="/stats", tags=["stats"])
api_router.include_router(orientation.router, prefix="/orientation", tags=["orientation"])
api_router.include_router(home.router, prefix="/home", tags=["home"])
api_router.include_router(providers.router, prefix="/providers", tags=["providers"])
api_router.include_router(admin_vendors.router, prefix="/admin-vendors", tags=["admin-vendors"])
api_router.include_router(admin_dashboard.router, prefix="/admin-dashboard", tags=["admin-dashboard"])
api_router.include_router(directory.router, prefix="/directory", tags=["directory"])
api_router.include_router(configuration.router, prefix="/config", tags=["configuration"])

api_router.include_router(provider_space.router, prefix="/provider-space", tags=["provider-space"])
api_router.include_router(enrollment_forms.router, prefix="/enrollment-forms", tags=["enrollment-forms"])
api_router.include_router(legacy_category.router, prefix="/category", tags=["compat-trankyl"])
api_router.include_router(provider_work.router, prefix="/provider-space", tags=["provider-space"])
api_router.include_router(provider_services.router, prefix="/provider-space", tags=["provider-space"])
api_router.include_router(provider_account.router, prefix="/provider-space", tags=["provider-space"])
