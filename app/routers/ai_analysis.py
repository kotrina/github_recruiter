# app/routers/ai_analysis.py
from fastapi import APIRouter, Query, HTTPException
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import base64
import json
import math
import re

from app.services.github import gh_get  # tu wrapper de requests con auth
from app.routers.languages import languages_core
from app.routers.activity import user_activity_core
from app.services.ai_gemini import gemini_client

router = APIRouter()

_USERNAME_RE = re.compile(r"^https?://github\.com/([^/?#]+)/?$", re.IGNORECASE)

def _username_from(profile: str) -> str:
    if not profile:
        raise ValueError("Empty profile")
    m = _USERNAME_RE.match(profile.strip())
    return m.group(1) if m else profile.strip().split("/")[0]

def _years_since(iso: Optional[str]) -> float:
    if not iso:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - dt).days / 365.25)
    except Exception:
        return 0.0

def _plain_excerpt_from_readme_item(item: Dict[str, Any], max_chars: int = 800) -> Optional[str]:
    """
    item: respuesta de /repos/{o}/{r}/readme (contiene 'content' base64 y 'encoding').
    Devolvemos texto llano truncado (sin imágenes/tabla).
    """
    try:
        content_b64 = item.get("content", "")
        txt = base64.b64decode(content_b64).decode("utf-8", errors="ignore")
        # Limpieza mínima: quita imágenes y tablas/HTML pesadas
        lines = []
        for line in txt.splitlines():
            if line.strip().startswith("!"):  # imágenes ![alt](url)
                continue
            if line.strip().startswith("<"):  # bloques html
                continue
            lines.append(line)
        cleaned = "\n".join(lines)
        return cleaned[:max_chars].strip()
    except Exception:
        return None

def _select_repos(repos: List[Dict[str, Any]], recent_months: int = 12, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Mezcla de top por estrellas + recientes (excluye forks/archivados).
    """
    def is_recent(r: Dict[str, Any]) -> bool:
        pushed = r.get("pushed_at")
        if not pushed:
            return False
        try:
            dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            months = (datetime.now(timezone.utc) - dt).days / 30.4
            return months <= recent_months
        except Exception:
            return False

    pool = [r for r in repos if not r.get("fork") and not r.get("archived")]
    by_stars = sorted(pool, key=lambda r: int(r.get("stargazers_count") or 0), reverse=True)
    recent = [r for r in pool if is_recent(r)]
    # mezcla: 3 por estrellas + 2 recientes, sin duplicados
    picked = []
    for r in by_stars[:3]:
        if r not in picked:
            picked.append(r)
    for r in recent:
        if len(picked) >= limit:
            break
        if r not in picked:
            picked.append(r)
    # si todavía faltan, rellena por estrellas
    for r in by_stars:
        if len(picked) >= limit:
            break
        if r not in picked:
            picked.append(r)
    return picked[:limit]

def _check_path_exists(owner: str, name: str, path: str) -> bool:
    try:
        _ = gh_get(f"/repos/{owner}/{name}/contents/{path}")
        return True
    except Exception:
        return False

def _repo_governance_quick(owner: str, name: str, license_spdx: Optional[str]) -> Dict[str, bool]:
    """
    Checks ligeros (máx 3–4 llamadas por repo):
      - readme: usa endpoint de README (lo necesitamos para excerpt)
      - ci: .github/workflows
      - tests: carpeta tests/ o archivos *_test*
      - license_like: del objeto repo (spdx) o LICENSE en contents
    """
    gov = {"readme": False, "ci": False, "tests": False, "license_like": False}
    # ci
    gov["ci"] = _check_path_exists(owner, name, ".github/workflows")
    # tests (shallow: carpeta tests/)
    gov["tests"] = _check_path_exists(owner, name, "tests")
    # license
    if license_spdx and license_spdx.upper() not in ("NOASSERTION",):
        gov["license_like"] = True
    else:
        gov["license_like"] = _check_path_exists(owner, name, "LICENSE") or _check_path_exists(owner, name, "LICENSE.md")
    return gov

def _total_stars(repos: List[Dict[str, Any]]) -> int:
    return sum(int(r.get("stargazers_count") or 0) for r in repos)

def _recent_repos_count(repos: List[Dict[str, Any]], months: int = 6) -> int:
    cnt = 0
    for r in repos:
        pushed = r.get("pushed_at")
        if not pushed:
            continue
        try:
            dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - dt).days <= months * 30.4:
                cnt += 1
        except Exception:
            pass
    return cnt

@router.get("/ai_analysis")
def ai_analysis(
    profile: str = Query(..., description="GitHub username or profile URL"),
    lang: str = Query("EN", description="Language for AI output: EN or ES"),
    days: int = Query(90, description="Window for activity KPIs"),
):
    username = _username_from(profile)
    lang = (lang or "EN").upper()
    if lang not in ("EN", "ES"):
        raise HTTPException(status_code=400, detail="Invalid lang, must be EN or ES")

    # 1) Core data in parallel: user, repos list, langs, activity
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_user = ex.submit(gh_get, f"/users/{username}")
        f_repos = ex.submit(gh_get, f"/users/{username}/repos", params={"per_page": 100, "sort": "updated"})
        f_langs = ex.submit(languages_core, username, 30, 12, False, False)
        f_act = ex.submit(user_activity_core, username, days, 100, 3)

        user = f_user.result()
        repos_all = f_repos.result() or []
        langs_payload = f_langs.result() or {}
        activity = f_act.result() or {}

    # 2) Compact profile + summary
    profile_compact = {
        "u": username,
        "url": f"https://github.com/{username}",
        "name": user.get("name"),
        "bio": user.get("bio"),
        "loc": user.get("location"),
        "followers": int(user.get("followers") or 0),
        "pub_repos": int(user.get("public_repos") or 0),
        "created": user.get("created_at"),
    }
    summary = {
        "account_age_years": round(_years_since(user.get("created_at")), 1),
        "total_stars": _total_stars(repos_all),
        "recent_repos": _recent_repos_count(repos_all, months=6),
        "main_lang": None,
    }

    # 3) Languages compact
    langs_mix = langs_payload.get("mix") or langs_payload.get("languages") or []
    if langs_mix:
        summary["main_lang"] = max(langs_mix, key=lambda l: l.get("percent", 0)).get("name")

    # 4) Select up to 5 repos (stars+recent)
    picks = _select_repos(repos_all, recent_months=12, limit=5)

    # 5) For each repo: quick governance + README excerpt (done in parallel, 2–3 hits/repo)
    repos_compact: List[Dict[str, Any]] = []
    tasks = []
    with ThreadPoolExecutor(max_workers=min(8, max(2, len(picks)))) as ex:
        for r in picks:
            full = r.get("full_name") or ""
            if "/" not in full:
                continue
            owner, name = full.split("/", 1)
            license_spdx = (r.get("license") or {}).get("spdx_id")
            # Schedule quick checks
            tasks.append(("gov", full, ex.submit(_repo_governance_quick, owner, name, license_spdx)))
            # Schedule README
            tasks.append(("readme", full, ex.submit(gh_get, f"/repos/{owner}/{name}/readme")))

        # Collect results grouped by repo
        tmp: Dict[str, Dict[str, Any]] = {r.get("full_name"): {} for r in picks}
        for kind, full, fut in tasks:
            try:
                val = fut.result()
                tmp[full][kind] = val
            except Exception:
                tmp[full][kind] = None

    for r in picks:
        full = r.get("full_name")
        owner, name = full.split("/", 1)
        t = tmp.get(full, {})
        readme_item = t.get("readme")
        excerpt = _plain_excerpt_from_readme_item(readme_item) if readme_item else None

        repos_compact.append({
            "n": full,
            "url": r.get("html_url"),
            "desc": r.get("description"),
            "lang": r.get("language"),
            "stars": int(r.get("stargazers_count") or 0),
            "forks": int(r.get("forks_count") or 0),
            "watch": int(r.get("subscribers_count") or 0),  # a veces no viene
            "created": r.get("created_at"),
            "updated": r.get("updated_at"),
            "pushed": r.get("pushed_at"),
            "fork": bool(r.get("fork")),
            "arch": bool(r.get("archived")),
            "license": (r.get("license") or {}).get("spdx_id"),
            "gov": t.get("gov") or {"readme": bool(excerpt), "ci": False, "tests": False, "license_like": False},
            "rx": excerpt,  # README excerpt (<=800 chars) o None
        })

    # 6) Activity compact (usa lo que ya devuelves)
    act_kpis = activity.get("kpis") or {}
    act_roles = activity.get("roles") or {}
    activity_compact = {
        "last_days": act_kpis.get("last_active_days_ago"),
        "weeks_12w": act_kpis.get("active_weeks_12w"),
        "external_pct": act_kpis.get("external_ratio_pct"),
        "roles": {
            "build_pct": (act_roles.get("build") or {}).get("pct"),
            "review_pct": (act_roles.get("review") or {}).get("pct"),
            "feedback_pct": (act_roles.get("feedback") or {}).get("pct"),
        },
        "top3": (activity.get("top_collabs") or [])[:3],
    }

    # 7) Payload compacto para la IA
    payload = {
        "profile": profile_compact,
        "summary": summary,
        "langs": langs_mix,
        "repos": repos_compact,
        "activity": activity_compact,
    }
    ctx_json = json.dumps(payload, separators=(",", ":"))

    # 8) Prompt bilingüe
    if lang == "ES":
        lang_note = "Responde en **español** con tono profesional y conciso."
        sections = (
            "1) Resumen — señales principales (1–2 líneas)\n"
            "2) Fortalezas — habilidades y evidencias (repos, lenguajes, estrellas)\n"
            "3) Riesgos/zonas grises — límites de los datos públicos\n"
            "4) Preguntas para entrevista — 3–5 bullets\n"
            "5) Repos destacables — por qué importan (impacto, calidad, gobernanza)\n"
        )
        lang_label = "Spanish"
    else:
        lang_note = "Respond in **English**, concise and recruiter-friendly."
        sections = (
            "1) Snapshot — top signals (1–2 lines)\n"
            "2) Strengths — skills & evidence (repos, languages, stars)\n"
            "3) Risks/unknowns — limits of public data\n"
            "4) Suggested interview questions — 3–5 bullets\n"
            "5) Notable repositories — why they matter (impact, quality, governance)\n"
        )
        lang_label = "English"

    prompt = f"""
You are a senior technical recruiter assistant. You cannot browse the web.
Use ONLY the provided JSON context to produce a practical briefing.

LANGUAGE: {lang_label}

CONTEXT_JSON:
{ctx_json}

Write the briefing with short bullet points and the following structure:
{sections}
Rules:
- Do NOT invent facts outside the JSON.
- Cite repo names when referencing evidence.
- Prefer clear, direct, useful phrasing. {lang_note}
""".strip()

    # 9) IA
    result = gemini_client.generate_text(prompt=prompt)
    if "error" in result:
        raise HTTPException(status_code=502, detail=f"Gemini error: {result['error']}")

    return {
        "username": username,
        "github_url": f"https://github.com/{username}",
        "language": lang,
        "analysis": result["text"],
        "context_preview": payload,  # útil para depurar; quítalo en prod si quieres
    }
