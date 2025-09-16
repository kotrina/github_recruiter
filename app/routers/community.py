from fastapi import APIRouter
from typing import List
from app.services.github import gh_get, gh_get_paginated
from app.utils.time import months_ago_dt, parse_iso_dt
from app.utils.repos import select_repos_for


router = APIRouter()

def _compute_community_score(checks: dict) -> dict:
    """
    Calcula score (0–6) y semáforo (traffic_light) a partir de los booleanos.
    """
    score = sum(1 for v in checks.values() if v)
    if score <= 2:
        traffic_light = "red"
    elif score <= 4:
        traffic_light = "yellow"
    else:
        traffic_light = "green"

    reason = f"{score}/6 checks: " + ", ".join(
        [k for k, v in checks.items() if v]
    ) or "none"

    return {
        "community_score": score,
        "traffic_light": traffic_light,
        "traffic_reason": reason,
    }

    

def community_profile(
    username: str,
    repo_limit: int = 10,
    include_forks: bool = False,
    include_archived: bool = False,
    recent_months: int = 12,
):
    """
    Checklist OSS + score + traffic light por repo.
    """
    selected = select_repos_for(
        username, repo_limit, include_forks, include_archived, recent_months
    )
    out = []
    for r in selected:
        owner, name = r["owner"]["login"], r["name"]
        data = gh_get(f"/repos/{owner}/{name}/community/profile") or {}
        files = (data.get("files") or {})

        checks = {
            "readme": bool(files.get("readme")),
            "license": bool(data.get("license")),
            "code_of_conduct": bool(files.get("code_of_conduct")),
            "issue_template": bool(files.get("issue_template")),
            "pull_request_template": bool(files.get("pull_request_template")),
            "security_policy": bool(files.get("security_policy")),
        }

        score_info = _compute_community_score(checks)

        out.append({
            "full_name": f"{owner}/{name}",
            "stars": r.get("stargazers_count"),
            "pushed_at": r.get("pushed_at"),
            "checks": checks,
            **score_info,
        })

    # Ordenar por score y stars
    out.sort(key=lambda x: (x["community_score"], x["stars"]), reverse=True)

    return {
        "username": username,
        "repos": out,
        "params": {
            "repo_limit": repo_limit,
            "include_forks": include_forks,
            "include_archived": include_archived,
            "recent_months": recent_months,
        },
    }
