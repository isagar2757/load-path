"""Atlas connection. Every client uses certifi's CA bundle; TLS verification is never disabled."""
import os
from functools import lru_cache
from pathlib import Path

import certifi
from pymongo import MongoClient

ENV_FILE = Path(__file__).resolve().parent / ".env"


def mongo_uri(required: bool = True) -> str | None:
    """MONGODB_URI from the environment, else from ./.env."""
    v = os.environ.get("MONGODB_URI")
    if not v and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("MONGODB_URI="):
                v = line.split("=", 1)[1].strip().strip("\"'")
    if not v and required:
        raise RuntimeError("MONGODB_URI not set (environment or .env)")
    return v or None


@lru_cache(maxsize=1)
def client() -> MongoClient:
    return MongoClient(mongo_uri(), tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)


def get_db(name: str = "capital"):
    """`capital` for the app; tests use `capital_test` and drop it."""
    return client()[name]
