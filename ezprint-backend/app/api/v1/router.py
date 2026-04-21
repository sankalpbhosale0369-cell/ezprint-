from fastapi import APIRouter

from app.api.v1 import admin, auth, dashboard, jobs, printers, shops

api_v1_router = APIRouter()
api_v1_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_v1_router.include_router(shops.router, prefix="/shops", tags=["shops"])
api_v1_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_v1_router.include_router(printers.router, prefix="/printers", tags=["printers"])
api_v1_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_v1_router.include_router(admin.router, prefix="/admin", tags=["admin"])
