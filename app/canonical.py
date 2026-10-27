"""Canonical JSON and hashing. An approval is bound to the SHA-256 of the exact change."""
import hashlib
import json


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_of(obj) -> str:
    return sha256(canon(obj))
