import json
from pathlib import Path

from app.config import TOKENS_DIR


def _path(provider: str, email: str) -> Path:
    safe_email = email.replace("/", "_")
    return TOKENS_DIR / f"{provider}_{safe_email}.json"


def save_token(provider: str, email: str, data: dict) -> None:
    _path(provider, email).write_text(json.dumps(data))


def load_token(provider: str, email: str) -> dict | None:
    path = _path(provider, email)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def list_accounts(provider: str) -> list[str]:
    prefix = f"{provider}_"
    return [
        p.stem[len(prefix):]
        for p in TOKENS_DIR.glob(f"{prefix}*.json")
    ]
