from fastapi import APIRouter, Query, HTTPException
from concurrent.futures import ThreadPoolExecutor
import re, json

from app.routers.languages import languages_core
from app.routers.community import community_profile_core
from app.routers.activity import user_activity_core
from app.services.ai_gemini import gemini_client

router = APIRouter()
_USERNAME_RE = re.compile(r"^https?://github\.com/([^/?#]+)/?$", re.IGNORECASE)

def _user(profile: str) -> str:
    m = _USERNAME_RE.match(profile.strip())
    return m.group(1) if m else profile.strip().split("/")[0]

@router.get("/ai_analysis")
def ai_analysis(
    profile: str = Query(..., description="GitHub username or profile URL"),
    days: int = 90,
    lang: str = Query("EN", description="Language for AI output: EN or ES"),

):
    try:
        username = _user(profile)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid profile format")

    lang = lang.upper()
    if lang not in ("EN", "ES"):
        raise HTTPException(status_code=400, detail="Invalid lang, must be EN or ES")
    
    # Ejecutar en paralelo para bajar latencia
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_lang = ex.submit(languages_core, username, 30, 12, False, False)
        f_comm = ex.submit(community_profile_core, username, 10, False, False, 12)
        f_act  = ex.submit(user_activity_core,  username, days, 100, 3)

        try:
            langs = f_lang.result()
            comm  = f_comm.result()
            act   = f_act.result()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Upstream error: {e}")

    # Seleccionar hasta 5 repos “mejores” del community para la IA
    repos = (comm.get("repos") or [])[:5]
    # Compactar para prompt (claves cortas y valores relevantes)
    repos_compact = []
    for r in repos:
        repos_compact.append({
            "n": r.get("full_name"),
            "url": f"https://github.com/{r.get('full_name')}",
            "stars": r.get("stars"),
            "forks": r.get("forks"),
            "watch": r.get("watchers"),
            "pushed": r.get("pushed_at"),
            "score": r.get("community_score"),
            "checks": r.get("checks", {}),
        })

    langs_compact = langs.get("mix") or langs.get("languages") or []
    activity_compact = {
        "last_days": (act.get("kpis") or {}).get("last_active_days_ago"),
        "weeks_12w": (act.get("kpis") or {}).get("active_weeks_12w"),
        "external_pct": (act.get("kpis") or {}).get("external_ratio_pct"),
        "roles": {
            "build_pct": (act.get("roles") or {}).get("build", {}).get("pct"),
            "review_pct": (act.get("roles") or {}).get("review", {}).get("pct"),
            "feedback_pct": (act.get("roles") or {}).get("feedback", {}).get("pct"),
        },
        "top3": act.get("top_collabs", [])[:3],
    }

    # Serializa compacto (menos espacios → menos tokens)
    payload = {
        "profile": {"u": username, "url": f"https://github.com/{username}"},
        "langs": langs_compact,
        "repos": repos_compact,
        "activity": activity_compact,
    }
    ctx_json = json.dumps(payload, separators=(",", ":"))

    # --- Language-specific instruction ---
    if lang == "ES":
        lang_note = "Responde **en español**. Usa un tono profesional y claro para recruiters en España o LATAM."
        lang_label = "Español"
    else:
        lang_note = "Respond **in English**. Use concise, professional language for international recruiters."
        lang_label = "English"

    prompt = f"""
You are a senior technical recruiter assistant. You cannot browse the web.
Analyze the following GitHub context (JSON) and produce a concise briefing.

LANGUAGE: {lang_label}, lang_note

CONTEXT_JSON:
{ctx_json}

Write the briefing in 5 sections with bullet points:
1) Snapshot — top signals (1–2 lines).
2) Strengths — skills & evidence (reference repos, languages, stars).
3) Risks/unknowns — limits of public data and potential gaps.
4) Suggested interview questions — 3–5 bullets.
5) Notable repositories — bullets with why they matter.

Rules:
- Use only the provided context. Do NOT invent details.
- Prefer short bullets and recruiter-friendly language.
- No more than 1400 characters
"""

    result = gemini_client.generate_text(prompt=prompt)
    if "error" in result:
        raise HTTPException(status_code=502, detail=f"Gemini error: {result['error']}")

    return {
        "username": username,
        "github_url": f"https://github.com/{username}",
        "analysis": result["text"],
        "context_preview": payload,  # útil para depurar; puedes quitarlo en prod
    }
