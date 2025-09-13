from datetime import datetime, timedelta, timezone

def months_ago_dt(months: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=30*months)

def days_ago_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

def parse_iso_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
