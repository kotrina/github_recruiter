import requests
from fastapi import HTTPException
from app.core.config import settings

HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "Authorization": f"token {settings.GITHUB_TOKEN}" if settings.GITHUB_TOKEN else None,
}

def gh_get(path: str, params: dict | None = None):
    if not settings.GITHUB_TOKEN:
        raise HTTPException(500, "Falta GITHUB_TOKEN")
    url = f"{settings.GITHUB_API}{path}"
    r = requests.get(url, headers=HEADERS, params=params or {}, timeout=20)
    if r.status_code == 404: raise HTTPException(404, "No encontrado en GitHub")
    if r.status_code == 401: raise HTTPException(401, "Token inválido o sin permisos")
    if r.status_code == 403: raise HTTPException(403, "Rate limit alcanzado")
    if r.status_code >= 400: raise HTTPException(r.status_code, r.text)
    return r.json()

def gh_get_paginated(path: str, base_params: dict | None = None, max_pages: int = 10) -> list:
    items, params = [], dict(base_params or {})
    params.setdefault("per_page", 100)
    for page in range(1, max_pages + 1):
        params["page"] = page
        chunk = gh_get(path, params)
        if not isinstance(chunk, list) or not chunk: break
        items.extend(chunk)
        if len(chunk) < params["per_page"]: break
    return items
