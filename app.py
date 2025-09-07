import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Carga variables de entorno desde .env (en local)
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PORT = int(os.getenv("PORT", "8080"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

app = FastAPI(title="LoggedOn Recruiter API (MVP)")

# CORS básico (en prod, restringe a tu dominio de Lovable)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True}

# Endpoint placeholder: lo rellenaremos en el siguiente paso
@app.get("/analyze")
def analyze(username: str):
    """
    De momento devuelve un stub. En el siguiente paso conectaremos GitHub.
    Ej: GET /analyze?username=torvalds
    """
    return {
        "username": username,
        "message": "MVP en marcha. Próximo paso: integrar GitHub API y métricas."
    }

# Nota: para ejecutar en local:
# uvicorn app:app --reload --port 8080
