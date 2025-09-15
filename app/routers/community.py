from fastapi import APIRouter
from typing import List
from app.services.github import gh_get, gh_get_paginated
from app.utils.time import months_ago_dt, parse_iso_dt
from app.utils.repos import select_repos_for


router = APIRouter()

    

@router.get("/community")
def community_profile(username: str, repo_limit: int = 10, include_forks: bool = False, include_archived: bool = False, recent_months: int = 12):
    selected = select_repos_for(username, repo_limit, include_forks, include_archived, recent_months)
    out = []
    for r in selected:
        owner, name = r["owner"]["login"], r["name"]
        data = gh_get(f"/repos/{owner}/{name}/community/profile") or {}
        files = (data.get("files") or {})
        out.append({
            "full_name": f"{owner}/{name}",
            "stars": r.get("stargazers_count"),
            "pushed_at": r.get("pushed_at"),
            "checks": {
                "readme": bool(files.get("readme")),
                "license": bool(data.get("license")),
                "code_of_conduct": bool(files.get("code_of_conduct")),
                "issue_template": bool(files.get("issue_template")),
                "pull_request_template": bool(files.get("pull_request_template")),
                "security_policy": bool(files.get("security_policy")),
            }
        })
    return {"username": username, "repos": out}
