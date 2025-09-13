import os
from typing import List

class Settings:
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    CORS_ORIGINS: List[str] = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]
    GITHUB_API: str = "https://api.github.com"

settings = Settings()
