import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import requests
from fastapi import HTTPException, Query

# Carga variables de entorno desde .env (en local)
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PORT = int(os.getenv("PORT", "8080"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
GITHUB_API = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "Authorization": f"token {GITHUB_TOKEN}" if GITHUB_TOKEN else None,
}
def gh_get(path: str, params: dict | None = None):
    if not GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="Falta GITHUB_TOKEN en variables de entorno")

    url = f"{GITHUB_API}{path}"
    r = requests.get(url, headers=HEADERS, params=params or {}, timeout=20)
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="No encontrado en GitHub")
    if r.status_code == 401:
        raise HTTPException(status_code=401, detail="Token inválido o sin permisos")
    if r.status_code == 403:
        raise HTTPException(status_code=403, detail="Rate limit alcanzado")
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


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
def analyze(
    username: str = Query(..., description="Username de GitHub, p.ej. 'torvalds'"),
    repos_limit: int = Query(5, ge=1, le=20, description="Cuántos repos recientes traer"),
):
    user = gh_get(f"/users/{username}")
    repos = gh_get(f"/users/{username}/repos", params={"per_page": repos_limit, "sort": "updated"})

    def map_repo(r: dict):
        return {
            "name": r.get("name"),
            "full_name": r.get("full_name"),
            "html_url": r.get("html_url"),
            "stars": r.get("stargazers_count"),
            "forks": r.get("forks_count"),
            "primary_language": r.get("language"),
            "pushed_at": r.get("pushed_at"),
            "is_fork": r.get("fork", False),
            "is_archived": r.get("archived", False),
        }

    return {
        "user": {
            "login": user.get("login"),
            "name": user.get("name"),
            "bio": user.get("bio"),
            "company": user.get("company"),
            "location": user.get("location"),
            "followers": user.get("followers"),
            "public_repos": user.get("public_repos"),
            "created_at": user.get("created_at"),
            "html_url": user.get("html_url"),
        },
        "repos": [map_repo(r) for r in repos],
    }


# Nota: para ejecutar en local:
# uvicorn app:app --reload --port 8080
