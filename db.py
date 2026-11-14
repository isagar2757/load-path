"""Atlas connection. Every client uses certifi's CA bundle; TLS verification is never disabled."""
import os
from functools import lru_cache
from pathlib import Path

import certifi
from pymongo import MongoClient

ENV_FILE = Path(__file__).resolve().parent / ".env"


def _setting(key: str) -> str | None:
    """`key` from the environment, else from ./.env."""
    v = os.environ.get(key)
    if not v and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith(f"{key}="):
                v = line.split("=", 1)[1].strip().strip("\"'")
    return v or None


def mongo_uri(required: bool = True) -> str | None:
    """MONGODB_URI from the environment, else from ./.env."""
    v = _setting("MONGODB_URI")
    if not v and required:
        raise RuntimeError("MONGODB_URI not set (environment or .env)")
    return v or None


@lru_cache(maxsize=1)
def client() -> MongoClient:
    return MongoClient(mongo_uri(), tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)


def get_db(name: str | None = None):
    """`capital` for the app, or the database named in CAPITAL_DB so two people can run the demo at once.

    Tests pass their own `capital_test_<suffix>` and drop it.
    """
    return client()[name or _setting("CAPITAL_DB") or "capital"]
