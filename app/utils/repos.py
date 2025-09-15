# app/utils/repos.py
from typing import List
from app.services.github import gh_get_paginated
from app.utils.time import months_ago_dt, parse_iso_dt

def select_repos_for(
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
