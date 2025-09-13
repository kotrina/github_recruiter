# app/routers/vitality.py
from fastapi import APIRouter
from typing import List
from datetime import datetime, timedelta, timezone

from app.services.github import gh_get, gh_get_paginated
from app.utils.time import months_ago_dt, parse_iso_dt

router = APIRouter()

def _select_repos_for(
    username: str,
    repo_limit: int,
    include_forks: bool,
    include_archived: bool,
    recent_months: int,
) -> List[dict]:
    repos = gh_get_paginated(
        f"/users/{username}/repos",
        {"type": "owner", "sort": "updated", "direction": "desc"},
        max_pages=3,
    )
    cutoff = months_ago_dt(recent_months) if recent_months and recent_months > 0 else None
    selected: List[dict] = []
    for r in repos:
        if not include_forks and r.get("fork"):
            continue
        if not include_archived and r.get("archived"):
            continue
        if cutoff and r.get("pushed_at"):
            try:
                if parse_iso_dt(r["pushed_at"]) < cutoff:
                    continue
            except Exception:
                pass
        selected.append(r)
        if len(selected) >= max(1, min(repo_limit, 100)):
            break
    return selected

def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

def _vitality_score(
    commits_8w: int,
    issues_closed_30d: int,
    prs_closed_30d: int,
    releases_6m: int,
    issues_open_now: int,
) -> int:
    score = 0
    score += min(40, commits_8w)                 # commits/pushes recientes (señal proxied)
    score += min(20, prs_closed_30d // 2)        # merges/PRs cerrados
    score += min(15, issues_closed_30d // 2)     # issues cerrados
    score += min(15, releases_6m * 3)            # cadencia de releases
    if issues_open_now > (issues_closed_30d + 5):
        score -= 10                               # penaliza backlog
    return max(0, min(100, score))

@router.get("/vitality")
def vitality(
    username: str,
    repo_limit: int = 10,
    include_forks: bool = False,
    include_archived: bool = False,
    recent_months: int = 12,
):
    """
    Señales de actividad por repo + 'vitality' (0–100) para priorizar qué mirar.
    *Nota:* evitamos /stats/* por ahora para no toparnos con 202 (recalculando).
    """
    selected = _select_repos_for(username, repo_limit, include_forks, include_archived, recent_months)
    out = []
    since_30d = _iso_days_ago(30)
    six_months_ago = datetime.now(timezone.utc) - timedelta(days=180)
    eight_weeks_ago_iso = _iso_days_ago(56)

    for r in selected:
        owner = r["owner"]["login"]
        name = r["name"]

        # issues/PRs abiertos (snapshot)
        issues_open = len(gh_get(f"/repos/{owner}/{name}/issues", params={"state": "open", "per_page": 50}) or [])
        prs_open = len(gh_get(f"/repos/{owner}/{name}/pulls", params={"state": "open", "per_page": 50}) or [])

        # PRs cerrados (aprox 30d: filtramos por updated_at localmente en los últimos N resultados)
        prs_closed_list = gh_get(f"/repos/{owner}/{name}/pulls", params={"state": "closed", "per_page": 50}) or []
        prs_closed_30d = 0
        for pr in prs_closed_list:
            dt = pr.get("merged_at") or pr.get("closed_at") or pr.get("updated_at")
            if dt:
                try:
                    if parse_iso_dt(dt) >= datetime.fromisoformat(eight_weeks_ago_iso.replace("Z", "+00:00")) - timedelta(days=14):
                        # margen amplio; si quieres estrictamente 30d, usa 30 en vez de 56-14
                        prs_closed_30d += 1
                except Exception:
                    pass

        # Issues cerradas en ~30d (GitHub aplica since en updated, suficiente como señal)
        issues_closed_recent = len(
            gh_get(f"/repos/{owner}/{name}/issues", params={"state": "closed", "since": since_30d, "per_page": 50}) or []
        )

        # Releases últimos 6 meses
        releases = gh_get(f"/repos/{owner}/{name}/releases", params={"per_page": 50}) or []
        releases_6m = 0
        for rel in releases:
            ts = rel.get("published_at")
            if ts:
                try:
                    if parse_iso_dt(ts) >= six_months_ago:
                        releases_6m += 1
                except Exception:
                    pass

        # Commits recientes (proxy): 1 si pushed_at dentro de 8 semanas
        commits_8w = 1 if (r.get("pushed_at") and r["pushed_at"] >= eight_weeks_ago_iso) else 0

        score = _vitality_score(
            commits_8w=commits_8w,
            issues_closed_30d=issues_closed_recent,
            prs_closed_30d=prs_closed_30d,
            releases_6m=releases_6m,
            issues_open_now=issues_open,
        )

        out.append({
            "full_name": f"{owner}/{name}",
            "stars": r.get("stargazers_count"),
            "pushed_at": r.get("pushed_at"),
            "issues_open": issues_open,
            "prs_open": prs_open,
            "prs_closed_30d": prs_closed_30d,
            "issues_closed_30d": issues_closed_recent,
            "releases_6m": releases_6m,
            "vitality": score,
        })

    out.sort(key=lambda x: (x["vitality"], x["stars"]), reverse=True)

    return {
        "username": username,
        "repos": out,
        "params": {
            "repo_limit": repo_limit,
            "include_forks": include_forks,
            "include_archived": include_archived,
            "recent_months": recent_months,
        }
    }
