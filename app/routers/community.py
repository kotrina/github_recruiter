# app/routers/community.py
"""
Community / OSS Health (fast + sqrt popularity)

Objetivo: latencia baja y señales útiles para recruiters.
Reduce llamadas por repo a 2–3:
  1) /repos/{owner}/{repo}                 -> stars, forks, subscribers_count (watchers), default_branch
  2) /repos/{owner}/{repo}/contents?ref=BR -> listado raíz (detecta README*, LICENSE/COPYING, MAINTAINERS, docs, etc.)
  3) /repos/{owner}/{repo}/contents/.github?ref=BR (opcional si existe) -> ISSUE_TEMPLATE/, PULL_REQUEST_TEMPLATE*, SECURITY.md, CONTRIBUTING.md

Scoring (tú lo pediste así):
- Popularidad (0..70) con sqrt:
    * Stars   -> hasta 40 pts (tope aprox en 50 stars)
    * Forks   -> hasta 20 pts (tope aprox en 20 forks)
    * Watchers-> hasta 10 pts (tope aprox en 10 watchers)
- Gobernanza (0..30): se calcula 0..90 con heurísticos (README, LICENSE/COPYING, etc.) y luego se reescala a 0..30.
- Semáforo:
    * green   >= 60
    * yellow  35..59
    * red     < 35
"""

from fastapi import APIRouter
from typing import List, Dict, Tuple, Optional
import math

from app.services.github import gh_get
from app.utils.repos import select_repos_for

router = APIRouter()

# ---------------------- Ponderaciones y targets (fáciles de ajustar) ----------------------

POPULARITY_TOTAL = 70
GOVERNANCE_TOTAL = 30

# Reparto interno de popularidad (deben sumar POPULARITY_TOTAL)
W_STARS = 40
W_FORKS = 20
W_WATCH = 10

# “Targets” donde cada señal alcanza su peso máximo (usando sqrt)
TARGET_STARS = 50   # ~50 stars ya dan W_STARS
TARGET_FORKS = 20   # ~20 forks ya dan W_FORKS
TARGET_WATCH = 10   # ~10 watchers ya dan W_WATCH

# ------------------------- Utils: listados de contenidos -------------------------

def _list_root(owner: str, repo: str, ref: str) -> List[Dict]:
    """
    Lista el contenido del directorio raíz en la rama `ref`.
    Si falla (404 o similar), devuelve [] para no romper el flujo.
    """
    try:
        data = gh_get(f"/repos/{owner}/{repo}/contents", params={"ref": ref})
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _list_dotgithub(owner: str, repo: str, ref: str) -> List[Dict]:
    """
    Lista el contenido de .github/ en la rama `ref`.
    Si no existe o falla, devuelve [].
    """
    try:
        data = gh_get(f"/repos/{owner}/{repo}/contents/.github", params={"ref": ref})
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _names_set(items: List[Dict]) -> set:
    """
    Devuelve un set con los nombres (lowercased) de los entries listados.
    """
    out = set()
    for it in items:
        name = it.get("name")
        if isinstance(name, str):
            out.add(name.lower())
    return out

def _has_dir(items: List[Dict], dir_name_lower: str) -> bool:
    """
    True si en `items` hay un entry tipo 'dir' con ese nombre (case-insensitive).
    """
    for it in items:
        if it.get("type") == "dir" and isinstance(it.get("name"), str):
            if it["name"].lower() == dir_name_lower:
                return True
    return False

# ------------------------- Gobernanza (lista raíz + .github) -------------------------

def _governance_score_from_lists(root_items: List[Dict], dotgithub_items: List[Dict]) -> Tuple[int, Dict]:
    """
    Calcula score de gobernanza (0..90) leyendo solo:
      - el listado del directorio raíz
      - el listado de .github/ (si existe)
    Señales y pesos (suman 90):
      README (18), License/COPYING (18), Contributing (12), Maintainers (8),
      Issue templates (5), PR template (5), Security policy (12), Docs folder (12).
    """
    root_names = _names_set(root_items)
    gh_names   = _names_set(dotgithub_items)

    checks = {}
    score = 0

    # README (18) – root o implícito si existe docs/Documentation (heurística)
    has_readme_root = any(n in root_names for n in ("readme", "readme.md", "readme.rst"))
    has_docs_folder = _has_dir(root_items, "docs") or _has_dir(root_items, "documentation")
    has_readme = has_readme_root or has_docs_folder
    checks["readme"] = has_readme
    score += 18 if has_readme else 0

    # License/COPYING/Licenses (18)
    has_license_like = any(n in root_names for n in ("license", "license.md", "copying", "copying.md")) \
                       or _has_dir(root_items, "licenses")
    checks["license_like"] = has_license_like
    score += 18 if has_license_like else 0

    # Contributing (12) – root o .github/
    has_contrib = any(n in root_names for n in ("contributing", "contributing.md")) \
                  or any(n in gh_names for n in ("contributing", "contributing.md"))
    checks["contributing"] = has_contrib
    score += 12 if has_contrib else 0

    # Maintainers (8)
    has_maintainers = "maintainers" in root_names
    checks["maintainers"] = has_maintainers
    score += 8 if has_maintainers else 0

    # Issue templates (5) – .github/ISSUE_TEMPLATE/ o ISSUE_TEMPLATE.md en root/.github
    has_issue_tpl = _has_dir(dotgithub_items, "issue_template") \
                    or "issue_template.md" in gh_names \
                    or "issue_template.md" in root_names
    checks["issue_template"] = has_issue_tpl
    score += 5 if has_issue_tpl else 0

    # PR template (5) – .github/PULL_REQUEST_TEMPLATE* o en root
    has_pr_tpl = ("pull_request_template.md" in gh_names) \
                 or ("pull_request_template" in gh_names) \
                 or ("pull_request_template.md" in root_names)
    checks["pull_request_template"] = has_pr_tpl
    score += 5 if has_pr_tpl else 0

    # Security policy (12) – SECURITY.md en root o .github/
    has_security = ("security.md" in root_names) or ("security.md" in gh_names)
    checks["security_policy_like"] = has_security
    score += 12 if has_security else 0

    # Carpeta de documentación (12) – docs/ o Documentation/
    checks["docs_folder"] = has_docs_folder
    score += 12 if has_docs_folder else 0

    # Bound 0..90
    score = max(0, min(90, score))
    return score, checks

# ------------------------------ Popularidad (0..70, sqrt) ------------------------------

def _sqrt_ratio(value: int | float, target: int | float) -> float:
    """
    Ratio 0..1 con sqrt: crece rápido al principio y satura en `target`.
    Si value >= target -> 1.0
    """
    if target <= 0:
        return 0.0
    return min(1.0, math.sqrt(max(0.0, float(value))) / math.sqrt(float(target)))

def _popularity_score(stars: int, forks: int, watchers: Optional[int]) -> tuple[int, dict]:
    """
    Popularidad total (0..70) a partir de stars/forks/watchers con sqrt y caps por componente.
    - Stars   puntúan hasta W_STARS cuando stars ~= TARGET_STARS.
    - Forks   puntúan hasta W_FORKS cuando forks ~= TARGET_FORKS.
    - Watchers puntúan hasta W_WATCH cuando watchers ~= TARGET_WATCH.
    """
    watchers_val = watchers or 0

    stars_part = W_STARS * _sqrt_ratio(stars, TARGET_STARS)
    forks_part = W_FORKS * _sqrt_ratio(forks, TARGET_FORKS)
    watch_part = W_WATCH * _sqrt_ratio(watchers_val, TARGET_WATCH)

    total = int(round(stars_part + forks_part + watch_part))
    total = max(0, min(POPULARITY_TOTAL, total))  # bound por sanidad

    meta = {
        "inputs": {"stars": stars, "forks": forks, "watchers": watchers_val},
        "targets": {"stars": TARGET_STARS, "forks": TARGET_FORKS, "watchers": TARGET_WATCH},
        "weights": {"stars": W_STARS, "forks": W_FORKS, "watchers": W_WATCH},
        "parts": {
            "stars_part": round(stars_part, 2),
            "forks_part": round(forks_part, 2),
            "watch_part": round(watch_part, 2),
        },
        "popularity_total": total,
    }
    return total, meta

# -------------------------------- Semáforo --------------------------------------

def _traffic(score_total: int) -> tuple[str, str]:
    if score_total >= 60:
        return "green", "Strong governance and/or community traction."
    if score_total >= 35:
        return "yellow", "Some governance signals or decent traction, may need context."
    return "red", "Few governance signals and limited traction."

# -------------------------------- Endpoint --------------------------------------

@router.get("/community")
def community_profile(
    username: str,
    repo_limit: int = 10,
    include_forks: bool = False,
    include_archived: bool = False,
    recent_months: int = 12,
):
    """
    Devuelve por repo:
      - community_score (0..100) = popularity(0..70) + governance(0..30)
      - traffic_light ('green'|'yellow'|'red') + traffic_reason
      - breakdown (governance_0_90, governance_scaled_0_30, popularity_0_70)
      - checks (detalle de gobernanza)
      - popularity_meta (desglose de popularidad)
      - métrica básicas: stars, forks, watchers, pushed_at
    """
    # 1) Elegir repos relevantes (recientes / no forks/archived según filtros)
    selected = select_repos_for(username, repo_limit, include_forks, include_archived, recent_months)
    out = []

    for r in selected:
        owner, name = r["owner"]["login"], r["name"]

        # 2) /repos -> métricas + rama por defecto (1 llamada)
        repo_meta = gh_get(f"/repos/{owner}/{name}")
        stars = int(repo_meta.get("stargazers_count") or 0)
        forks = int(repo_meta.get("forks_count") or 0)
        watchers = int(repo_meta.get("subscribers_count") or 0)
        default_branch = repo_meta.get("default_branch") or "HEAD"

        # 3) lista raíz en la rama por defecto (1 llamada)
        root_items = _list_root(owner, name, default_branch)

        # 4) lista .github/ si existe (0..1 llamada extra)
        dotgithub_items: List[Dict] = []
        has_dotgithub = _has_dir(root_items, ".github")
        if has_dotgithub:
            dotgithub_items = _list_dotgithub(owner, name, default_branch)

        # 5) Gobernanza: 0..90 -> reescalamos a 0..30
        gov_score_raw, checks = _governance_score_from_lists(root_items, dotgithub_items)
        gov_score = round(GOVERNANCE_TOTAL * (gov_score_raw / 90.0))

        # 6) Popularidad: 0..70 con sqrt
        pop_score, pop_meta = _popularity_score(stars, forks, watchers)

        # 7) Total y semáforo
        total = min(100, gov_score + pop_score)
        light, reason = _traffic(total)

        out.append({
            "full_name": f"{owner}/{name}",
            "stars": stars,
            "forks": forks,
            "watchers": watchers,
            "pushed_at": r.get("pushed_at"),
            "community_score": total,
            "traffic_light": light,
            "traffic_reason": reason,
            "checks": checks,
            "breakdown": {
                "governance_0_90": gov_score_raw,
                "governance_scaled_0_30": gov_score,
                "popularity_0_70": pop_score,
            },
            "popularity_meta": pop_meta,
        })

    # 8) Ordenamos por mayor score y, a igualdad, por stars
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
