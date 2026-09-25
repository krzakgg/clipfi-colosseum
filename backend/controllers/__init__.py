from .application_controller import router as application_router
from .campaign_controller import router as campaign_router
from .company_controller import router as company_router
from .creator_controller import router as creator_router
from .submission_controller import router as submission_router
from .reflink_controller import router as reflink_router
from .auth_controller import router as auth_router

__all__ = [
    "application_router",
    "campaign_router",
    "company_router",
    "creator_router",
    "submission_router",
    "reflink_router",
    "auth_router",
]