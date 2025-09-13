from fastapi import APIRouter, Query
from app.services.github import gh_get

router = APIRouter()

@router.get("/analyze")
def analyze(username: str = Query(...), repos_limit: int = Query(5, ge=1, le=20)):
    user = gh_get(f"/users/{username}")
    repos = gh_get(f"/users/{username}/repos", {"per_page": repos_limit, "sort": "updated"})
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
