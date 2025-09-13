from fastapi import APIRouter
from typing import List, Dict, Any, Tuple
from app.services.github import gh_get, gh_get_paginated
from app.utils.time import months_ago_dt, parse_iso_dt

router = APIRouter()

def _select_repos_for(username: str, repo_limit: int, include_forks: bool, include_archived: bool, recent_months: int) -> List[dict]:
    repos = gh_get_paginated(f"/users/{username}/repos", {"type": "owner", "sort": "updated", "direction": "desc"}, 3)
    cutoff = months_ago_dt(recent_months) if recent_months and recent_months > 0 else None
    selected = []
    for r in repos:
        if not include_forks and r.get("fork"): continue
        if not include_archived and r.get("archived"): continue
        if cutoff and r.get("pushed_at"):
            try:
                if parse_iso_dt(r["pushed_at"]) < cutoff: continue
            except Exception:
                pass
        selected.append(r)
        if len(selected) >= max(1, min(repo_limit, 100)): break
    return selected

@router.get("/languages")
def languages_mix(username: str, repo_limit: int = 30, include_forks: bool = False, include_archived: bool = False, recent_months: int = 12):
    selected = _select_repos_for(username, repo_limit, include_forks, include_archived, recent_months)

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
