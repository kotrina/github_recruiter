# app/routers/ai_analysis.py
from fastapi import APIRouter, Query, HTTPException
from app.services.ai_gemini import gemini_client
import re

router = APIRouter()

# --- Ayuda: permite pasar URL o nombre ---
_USERNAME_RE = re.compile(r"^https?://github\.com/([^/?#]+)/?$", re.IGNORECASE)

def extract_username(profile: str) -> str:
    """Admite 'torvalds' o 'https://github.com/torvalds' y devuelve 'torvalds'."""
    if not profile:
        raise ValueError("Empty profile")
    m = _USERNAME_RE.match(profile.strip())
    return m.group(1) if m else profile.strip().split("/")[0]


@router.get("/ai_analysis")
def ai_analysis(
    profile: str = Query(..., description="GitHub username or full profile URL"),
):
    """
    Simple endpoint: recibe un perfil de GitHub, genera un prompt fijo y pide análisis a Gemini.
    """
    try:
        username = extract_username(profile)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid profile format")

    # --- Prompt fijo que siempre enviaremos a Gemini ---
    prompt = f"""
You are a senior technical recruiter assistant.

Your task is to analyze the GitHub profile of this user:
👉 https://github.com/{username}

Based on the repositories, activity and code visible there,
generate a concise recruiter-oriented summary in English with these sections:

1) **Profile snapshot** — 1–2 lines about their developer type and seniority.
2) **Strengths & skills** — technologies, patterns, or areas of expertise inferred.
3) **Potential risks or gaps** — what might be missing or unclear from their profile.
4) **Overall impression** — short final paragraph (max 3 sentences).

Keep it concrete and professional. Do NOT invent information not visible on the GitHub page.
The link to analyze is: https://github.com/{username}

IMPORTANT: Please no more than 1400 characteres
    """

    # --- Llamada al cliente Gemini ---
    
    result = gemini_client.generate_text(prompt=prompt)

    if "error" in result:
        raise HTTPException(status_code=502, detail=f"Gemini error: {result['error']}")

    return {
        "username": username,
        "github_url": f"https://github.com/{username}",
        "analysis": result["text"],
    }
