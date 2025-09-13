from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.routers import health, analyze, languages, community  # vitality luego

app = FastAPI(title="LoggedOn Recruiter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(analyze.router, prefix="", tags=["analyze"])
app.include_router(languages.router, prefix="", tags=["languages"])
app.include_router(community.router, prefix="", tags=["community"])

# uvicorn main:app --reload --port 8080
