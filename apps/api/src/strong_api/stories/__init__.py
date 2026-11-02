"""Story library endpoints (ST-1, ST-2, ST-6 notes). Owned by S20. The outline actions of styled
stories (SC-10 to SC-13) are in `outline_api` and served by the same router."""

from strong_api.stories.flow import router as flow_router
from strong_api.stories.outline_api import router as outline_router
from strong_api.stories.router import router

router.include_router(outline_router)
router.include_router(flow_router)

__all__ = ["router"]
