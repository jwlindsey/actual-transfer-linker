"""Settings file (YAML)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .matching import Pair


@dataclass
class Config:
    url: str
    file: str
    password: str | None = None
    encryption_password: str | None = None
    cert: bool | str = True
    pairs: list[Pair] = field(default_factory=list)
    words: list[str] = field(default_factory=lambda: ["transfer"])
    max_days: int = 5
    lookback_days: int = 30


class ConfigError(ValueError):
    pass


def _secret(raw: dict, key: str) -> str | None:
    """A secret from `<key>_env` (the name of an environment variable, preferred) or `<key>` itself."""
    env = raw.get(f"{key}_env")
    if env:
        value = os.environ.get(str(env))
        if value is None:
            raise ConfigError(f"environment variable {env} (from {key}_env) is not set")
        return value
    return raw.get(key)


def load(path: str | Path) -> Config:
    import yaml
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    server = raw.get("server") or {}
    if not server.get("url") or not server.get("file"):
        raise ConfigError("server.url and server.file are required")
    pairs = []
    for i, p in enumerate(raw.get("pairs") or []):
        if isinstance(p, dict):
            a, b, cat = p.get("from") or p.get("a"), p.get("to") or p.get("b"), p.get("category")
        else:
            p = list(p)
            a, b, cat = (p + [None, None, None])[:3]
        if not a or not b or a == b:
            raise ConfigError(f"pairs[{i}] needs two different account names")
        pairs.append(Pair(str(a), str(b), str(cat) if cat else None))
    if not pairs:
        raise ConfigError("no account pairs configured")
    cfg = Config(
        url=str(server["url"]), file=str(server["file"]),
        password=_secret(server, "password"), encryption_password=_secret(server, "encryption_password"),
        cert=server.get("cert", True), pairs=pairs,
        words=[str(w) for w in (raw.get("words") or ["transfer"])],
        max_days=int(raw.get("max_days", 5)), lookback_days=int(raw.get("lookback_days", 30)),
    )
    if cfg.password is None:
        raise ConfigError("no server password: set server.password_env (recommended) or server.password")
    if not 0 <= cfg.max_days <= 14:
        raise ConfigError("max_days must be between 0 and 14")
    return cfg
