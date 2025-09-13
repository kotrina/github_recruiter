from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()

@router.get("/health")
def health():    
    return {"ok": True}
