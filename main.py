from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())  # carga .env antes de tocar settings

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.routers import health, analyze, languages, community , vitality , activity

from pathlib import Path


#env_path = find_dotenv() or (Path(__file__).resolve().parent / ".env")
#load_dotenv(dotenv_path=env_path, override=False)

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
app.include_router(vitality.router, prefix="", tags=["vitality"])
app.include_router(activity.router, prefix="", tags=["actovity"])

# uvicorn main:app --reload --port 8080
