# app/routers/activity.py
"""
Activity endpoint (simple + recruiter-friendly)

Fuente: GET /users/{username}/events/public
Ventana: últimos `days` días (por defecto 90) o hasta ~300 eventos (3 páginas x 100).

Devuelve:
- KPIs:
    * last_active_days_ago: días desde el último evento público
    * active_weeks_12w: nº de semanas activas (últimas 12) con >=1 evento
    * external_ratio_pct: % eventos en repos que NO son {username}/...
- Roles (Activity by role):
    * build    -> PushEvent + PullRequestEvent (opened/merged/closed)
    * review   -> PullRequestReviewEvent + IssueCommentEvent en PR
    * feedback -> IssuesEvent + IssueCommentEvent en Issue (no PR)
- Top 3 collaborations (externas):
    * repos externos ordenados por (prs + reviews + issues) desc y último evento desc
"""

from fastapi import APIRouter
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

from app.services.github import gh_get  # tu helper autenticado (maneja token, base URL)

router = APIRouter()

# Mapeo base de tipos de evento a una categoría a procesar
# (IssueCommentEvent se decide luego según si comenta en PR o en Issue)
TYPE_BASE = {
    "PushEvent": "push",
    "PullRequestEvent": "pr",
    "PullRequestReviewEvent": "review",
    "IssueCommentEvent": "comment",
    "IssuesEvent": "issues",
}

def _parse_dt(iso: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return None

def _is_external(username: str, repo_full: str) -> bool:
    """True si el repo no pertenece al usuario (owner != username)."""
    try:
        owner = repo_full.split("/", 1)[0]
        return owner.lower() != username.lower()
    except Exception:
        return True

def _week_start(dt: datetime) -> datetime:
    """Devuelve el lunes (00:00Z) de la semana de `dt` (para contar semanas activas)."""
    monday = dt - timedelta(days=dt.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)

def _comment_is_review(payload: dict) -> bool:
    """
    IssueCommentEvent -> si el comentario es en un PR, cuenta como 'review'.
    Si es en un Issue normal, cuenta como 'feedback'.
    """
    issue = (payload or {}).get("issue") or {}
    return "pull_request" in issue  # GitHub incluye este campo si el issue es un PR

@router.get("/activity")
def user_activity(
    username: str,
    days: int = 90,
    per_page: int = 100,
    max_pages: int = 3,
):
    """
    Agrega /users/{username}/events/public y devuelve KPIs + roles + top 3 colaboraciones.
    """
    # --- Ventana temporal (cap 1..365 días) ---
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

            # Última actividad (evento más reciente encontrado)
            if last_active is None or created > last_active:
                last_active = created

            # Si el evento ya está fuera de la ventana, podemos parar (orden desc)
            if created < cutoff:
                stop = True
                break

            events.append(ev)

        if stop:
            break

    # --- KPIs ---
    if last_active:
        last_active_days = max(0, (datetime.now(timezone.utc) - last_active).days)
    else:
        last_active_days = None

    twelve_weeks_ago = datetime.now(timezone.utc) - timedelta(weeks=12)
    weekly_active: set[datetime] = set()

    # Roles:
    # build    -> PushEvent + PullRequestEvent
    # review   -> PullRequestReviewEvent + IssueCommentEvent en PR
    # feedback -> IssuesEvent + IssueCommentEvent en Issue
    roles_counts: Dict[str, int] = {"build": 0, "review": 0, "feedback": 0}

    total_events = 0
    external_events = 0

    # Colaboraciones externas (top 3 por score)
    # score = prs + reviews + issues
    collab: Dict[str, Dict[str, int | str]] = defaultdict(lambda: {
        "prs": 0, "reviews": 0, "issues": 0, "last": None
    })

    for ev in events:
        total_events += 1

        t = ev.get("type", "")
        base = TYPE_BASE.get(t)
        repo_full = ev.get("repo", {}).get("name", "")
        payload = ev.get("payload") or {}
        created = _parse_dt(ev.get("created_at", ""))

        # Semanas activas (últimas 12)
        if created and created >= twelve_weeks_ago:
            weekly_active.add(_week_start(created))

        # Clasificación a roles
        if base == "push":
            roles_counts["build"] += 1
            event_role = "build"
        elif base == "pr":
            roles_counts["build"] += 1
            event_role = "build"
        elif base == "review":
            roles_counts["review"] += 1
            event_role = "review"
        elif base == "comment":
            if _comment_is_review(payload):
                roles_counts["review"] += 1
                event_role = "review"
            else:
                roles_counts["feedback"] += 1
                event_role = "feedback"
        elif base == "issues":
            roles_counts["feedback"] += 1
            event_role = "feedback"
        else:
            # Otros tipos no se usan en el resumen (no cuentan para roles)
            event_role = None

        # Externo: repo.owner != username
        is_ext = _is_external(username, repo_full)
        if is_ext:
            external_events += 1
            # Sumamos a colaboraciones externas si el rol es relevante
            if event_role in ("build", "review", "feedback"):
                if event_role == "build":
                    collab[repo_full]["prs"] = int(collab[repo_full]["prs"]) + 1
                elif event_role == "review":
                    collab[repo_full]["reviews"] = int(collab[repo_full]["reviews"]) + 1
                elif event_role == "feedback":
                    collab[repo_full]["issues"] = int(collab[repo_full]["issues"]) + 1

                # Última fecha registrada para el repo
                if created:
                    prev = collab[repo_full]["last"]
                    if (not prev) or (str(created) > str(prev)):
                        collab[repo_full]["last"] = created.isoformat()

    external_ratio = round(100 * external_events / total_events, 1) if total_events else 0.0

    # Porcentajes por rol
    def pct(n: int, d: int) -> float:
        return round(100 * n / d, 1) if d else 0.0

    roles_out = {
        "build":    {"count": roles_counts["build"],    "pct": pct(roles_counts["build"], total_events)},
        "review":   {"count": roles_counts["review"],   "pct": pct(roles_counts["review"], total_events)},
        "feedback": {"count": roles_counts["feedback"], "pct": pct(roles_counts["feedback"], total_events)},
    }

    # Top 3 colaboraciones externas (orden por score desc y last desc)
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
        "roles": roles_out,
        "top_collabs": top_list,
    }
