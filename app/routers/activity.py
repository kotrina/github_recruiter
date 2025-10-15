# app/routers/activity.py
"""
Activity endpoint (roles + full categorization)

Fuente: GET /users/{username}/events/public
Ventana: últimos `days` días (por defecto 90) o hasta ~300 eventos (3 páginas x 100).

Devuelve:
- KPIs:
    * last_active_days_ago
    * active_weeks_12w
    * external_ratio_pct   (sobre TODOS los eventos válidos)
- roles (3): build / review / feedback
    * count y pct (pct NORMALIZADO a la suma de roles → ≈100%)
- all_categories (6): build / review / feedback / explore / release / admin
    * count y pct_total (pct sobre TODOS los eventos → ≈100%)
- top_collabs (3): repos externos con mayor actividad (prs+reviews+issues)
"""

from fastapi import APIRouter
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

from app.services.github import gh_get  # helper autenticado

router = APIRouter()

# Tipos base de interés principal (otros van a buckets complementarios)
TYPE_BASE = {
    "PushEvent": "push",
    "PullRequestEvent": "pr",
    "PullRequestReviewEvent": "pr_review",
    "IssueCommentEvent": "issue_comment",
    "IssuesEvent": "issues",
    "ForkEvent": "fork",
    "WatchEvent": "watch",         # stars en REST v3
    "ReleaseEvent": "release",
    "CreateEvent": "create",       # puede ser tag/repo/branch
    "DeleteEvent": "delete",
    "PublicEvent": "public",
    "MemberEvent": "member",
    "RepositoryEvent": "repository",
    "GollumEvent": "gollum",       # wiki
    "DiscussionEvent": "discussion",
    "DiscussionCommentEvent": "discussion_comment",
    "WorkflowRunEvent": "workflow_run",
    "WorkflowJobEvent": "workflow_job",
}

def _parse_dt(iso: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None

def _is_external(username: str, repo_full: str) -> bool:
    try:
        owner = repo_full.split("/", 1)[0]
        return owner.lower() != username.lower()
    except Exception:
        return True

def _week_start(dt: datetime) -> datetime:
    monday = dt - timedelta(days=dt.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)

def _comment_is_review(payload: dict) -> bool:
    """IssueCommentEvent -> True si comenta en un PR; False si en Issue normal."""
    issue = (payload or {}).get("issue") or {}
    return "pull_request" in issue

def _create_is_tag(payload: dict) -> bool:
    """CreateEvent -> True si es tag, usado como 'release'."""
    return (payload or {}).get("ref_type") == "tag"




@router.get("/activity")
def user_activity(
    username: str,
    days: int = 90,
    per_page: int = 100,
    max_pages: int = 3,
):
    return user_activity_core(username, days, per_page, max_pages)

def user_activity_core(username: str,days: int = 90,per_page: int = 100,max_pages: int = 3,):
    """
    Agrega /users/{username}/events/public y devuelve:
      - KPIs
      - roles (build/review/feedback) con % normalizado a roles
      - all_categories (6 buckets) con % sobre total
      - top 3 colaboraciones externas
    """
    # --- Ventana temporal ---
    window = timedelta(days=max(1, min(days, 365)))
    cutoff = datetime.now(timezone.utc) - window

    events: List[dict] = []
    last_active: Optional[datetime] = None

    # --- Paginación (hasta ~300 eventos) ---
    for page in range(1, max_pages + 1):
        data = gh_get(
            f"/users/{username}/events/public",
            params={"per_page": per_page, "page": page},
        )
        if not isinstance(data, list) or not data:
            break

        stop = False
        for ev in data:
            created = _parse_dt(ev.get("created_at", ""))
            if not created:
                continue
            if last_active is None or created > last_active:
                last_active = created
            if created < cutoff:
                stop = True
                break
            events.append(ev)

        if stop:
            break

    # --- KPIs básicos ---
    if last_active:
        last_active_days = max(0, (datetime.now(timezone.utc) - last_active).days)
    else:
        last_active_days = None

    twelve_weeks_ago = datetime.now(timezone.utc) - timedelta(weeks=12)
    weekly_active: set[datetime] = set()

    # Contadores
    roles_counts: Dict[str, int] = {"build": 0, "review": 0, "feedback": 0}
    cats_counts: Dict[str, int] = {
        "build": 0, "review": 0, "feedback": 0,
        "explore": 0, "release": 0, "admin": 0
    }

    total_events = 0
    external_events = 0

    # Colaboraciones externas
    collab: Dict[str, Dict[str, int | str]] = defaultdict(lambda: {
        "prs": 0, "reviews": 0, "issues": 0, "last": None
    })

    for ev in events:
        total_events += 1

        t = ev.get("type", "")
        base = TYPE_BASE.get(t, "other")
        repo_full = ev.get("repo", {}).get("name", "")
        payload = ev.get("payload") or {}
        created = _parse_dt(ev.get("created_at", "")) or datetime.now(timezone.utc)

        # Semanas activas (últimas 12)
        if created >= twelve_weeks_ago:
            weekly_active.add(_week_start(created))

        # --- Clasificación completa -> 6 buckets ---
        # Primero resolvemos roles (build/review/feedback)
        event_role: Optional[str] = None

        if base in ("push", "pr"):
            roles_counts["build"] += 1
            cats_counts["build"] += 1
            event_role = "build"
        elif base == "pr_review":
            roles_counts["review"] += 1
            cats_counts["review"] += 1
            event_role = "review"
        elif base == "issue_comment":
            if _comment_is_review(payload):
                roles_counts["review"] += 1
                cats_counts["review"] += 1
                event_role = "review"
            else:
                roles_counts["feedback"] += 1
                cats_counts["feedback"] += 1
                event_role = "feedback"
        elif base == "issues":
            roles_counts["feedback"] += 1
            cats_counts["feedback"] += 1
            event_role = "feedback"
        elif base in ("fork", "watch"):
            cats_counts["explore"] += 1
        elif base == "release":
            cats_counts["release"] += 1
        elif base == "create":
            # tag -> release; repo/branch -> admin
            if _create_is_tag(payload):
                cats_counts["release"] += 1
            else:
                cats_counts["admin"] += 1
        elif base in ("delete", "public", "member", "repository", "gollum",
                      "discussion", "discussion_comment", "workflow_run", "workflow_job"):
            cats_counts["admin"] += 1
        else:
            # cualquier otro tipo no mapeado -> admin (conservador)
            cats_counts["admin"] += 1

        # --- Externo ---
        is_ext = _is_external(username, repo_full)
        if is_ext:
            external_events += 1
            # Para top collabs solo sumamos si el rol es colaborativo técnico
            if event_role in ("build", "review", "feedback"):
                if event_role == "build":
                    collab[repo_full]["prs"] = int(collab[repo_full]["prs"]) + 1
                elif event_role == "review":
                    collab[repo_full]["reviews"] = int(collab[repo_full]["reviews"]) + 1
                elif event_role == "feedback":
                    collab[repo_full]["issues"] = int(collab[repo_full]["issues"]) + 1
                # last
                prev = collab[repo_full]["last"]
                if (not prev) or (str(created) > str(prev)):
                    collab[repo_full]["last"] = created.isoformat()

    # --- Ratios y porcentajes ---
    external_ratio = round(100 * external_events / total_events, 1) if total_events else 0.0

    roles_total = roles_counts["build"] + roles_counts["review"] + roles_counts["feedback"]

    def pct(n: int, d: int) -> float:
        return round(100 * n / d, 1) if d else 0.0

    # Pct normalizados a roles (sumarán ≈100%)
    roles_out = {
        "build":    {"count": roles_counts["build"],    "pct": pct(roles_counts["build"], roles_total)},
        "review":   {"count": roles_counts["review"],   "pct": pct(roles_counts["review"], roles_total)},
        "feedback": {"count": roles_counts["feedback"], "pct": pct(roles_counts["feedback"], roles_total)},
        "roles_total": roles_total
    }

    # Pct sobre el total (sumarán ≈100% en conjunto)
    all_categories_out = {
        "build":    {"count": cats_counts["build"],    "pct_total": pct(cats_counts["build"], total_events)},
        "review":   {"count": cats_counts["review"],   "pct_total": pct(cats_counts["review"], total_events)},
        "feedback": {"count": cats_counts["feedback"], "pct_total": pct(cats_counts["feedback"], total_events)},
        "explore":  {"count": cats_counts["explore"],  "pct_total": pct(cats_counts["explore"], total_events)},
        "release":  {"count": cats_counts["release"],  "pct_total": pct(cats_counts["release"], total_events)},
        "admin":    {"count": cats_counts["admin"],    "pct_total": pct(cats_counts["admin"], total_events)},
        "total_events": total_events
    }

    # --- Top 3 colaboraciones externas ---
    top_list = []
    for repo, d in collab.items():
        score = int(d["prs"]) + int(d["reviews"]) + int(d["issues"])
        top_list.append({
            "repo": repo,
            "prs": int(d["prs"]),
            "reviews": int(d["reviews"]),
            "issues": int(d["issues"]),
            "score": score,
            "last": d["last"],
            "html_url": f"https://github.com/{repo}", 
        })
    top_list.sort(key=lambda x: (x["score"], x["last"] or ""), reverse=True)
    top_list = top_list[:3]

    return {
        "username": username,
        "window_days": days,
        "kpis": {
            "last_active_days_ago": last_active_days,
            "active_weeks_12w": len(weekly_active),
            "external_ratio_pct": external_ratio,
        },
        "roles": roles_out,                # % sobre roles_total
        "all_categories": all_categories_out,  # % sobre total_events
        "top_collabs": top_list,
    }
