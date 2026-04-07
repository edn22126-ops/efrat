from fastapi import APIRouter

from app.api.v1 import documents

router = APIRouter(prefix="/api/v1")
router.include_router(documents.router)
