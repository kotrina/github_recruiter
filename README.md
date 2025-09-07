# LoggedOn Recruiter (MVP)

API mínima en **FastAPI** para analizar perfiles de GitHub y devolver métricas “recruiter-ready”.

## Requisitos
- Python 3.10+
- Token de GitHub (GITHUB_TOKEN): crea uno Fine-grained (solo lectura pública).

## Puesta en marcha
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# edita .env y pega tu GITHUB_TOKEN

uvicorn app:app --reload --port 8080
# prueba:
curl "http://localhost:8080/health"
