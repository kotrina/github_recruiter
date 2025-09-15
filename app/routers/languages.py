from fastapi import APIRouter
from typing import List, Dict, Any, Tuple
from app.services.github import gh_get, gh_get_paginated
from app.utils.time import months_ago_dt, parse_iso_dt
from app.utils.repos import select_repos_for


router = APIRouter()



@router.get("/languages")
def languages_mix(username: str, repo_limit: int = 30, include_forks: bool = False, include_archived: bool = False, recent_months: int = 12):
    
    selected = select_repos_for(username, repo_limit, include_forks, include_archived, recent_months)

    totals: Dict[str, int] = {}
    analyzed: List[Tuple[str, Dict[str, int]]] = []
    for r in selected:
        owner = r["owner"]["login"]
        name = r["name"]
        langs = gh_get(f"/repos/{owner}/{name}/languages") or {}
        analyzed.append((f"{owner}/{name}", langs))
        for lang, b in (langs or {}).items():
            totals[lang] = totals.get(lang, 0) + int(b)

    total_bytes = sum(totals.values())
    if total_bytes == 0:
        return {"username": username, "analyzed_repos": [full for full, _ in analyzed], "languages": [], "total_bytes": 0, "percentages": {}, "skipped": {}, "note": "Sin lenguajes detectables."}

    percentages = {k: round(v * 100.0 / total_bytes, 1) for k, v in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)}
    return {
        "username": username,
        "analyzed_repos": [full for full, _ in analyzed],
        "total_bytes": total_bytes,
        "languages": [{"name": k, "bytes": totals[k], "percent": percentages[k]} for k in percentages.keys()],
        "percentages": percentages,
        "params": {"repo_limit": repo_limit, "include_forks": include_forks, "include_archived": include_archived, "recent_months": recent_months},
    }
