"""Side-effect-free JSON and .env configuration loading."""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

_JSON_LIMIT = 1024 * 1024
_ENV_LIMIT = 64 * 1024
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class ConfigError(ValueError):
    """Safe configuration error that never includes secret values."""


@dataclass(frozen=True, slots=True)
class SecretValue:
    _value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self._value or len(self._value) > 4096:
            raise ConfigError("secret must be non-empty and at most 4096 characters")

    def reveal(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __str__(self) -> str:
        return "<redacted>"

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"


@dataclass(frozen=True, slots=True)
class TwitchConfig:
    client_id: str | None
    access_token: SecretValue | None
    redirect_uri: str
    request_timeout_seconds: float
    rate_limit_reserve: int


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    path: Path
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class AppConfig:
    data_dir: Path
    database: DatabaseConfig
    twitch: TwitchConfig
    source_files: tuple[Path, ...] = field(default=(), repr=False)


_JSON_KEYS = {
    "data_dir",
    "database.path",
    "database.timeout_seconds",
    "twitch.client_id",
    "twitch.access_token",
    "twitch.redirect_uri",
    "twitch.request_timeout_seconds",
    "twitch.rate_limit_reserve",
}
_ENV_KEYS = {
    "STREAMOS_DATA_DIR": "data_dir",
    "STREAMOS_DB_PATH": "database.path",
    "STREAMOS_DB_TIMEOUT_SECONDS": "database.timeout_seconds",
    "STREAMOS_TWITCH_CLIENT_ID": "twitch.client_id",
    "STREAMOS_TWITCH_ACCESS_TOKEN": "twitch.access_token",
    "STREAMOS_TWITCH_REDIRECT_URI": "twitch.redirect_uri",
    "STREAMOS_TWITCH_TIMEOUT_SECONDS": "twitch.request_timeout_seconds",
    "STREAMOS_TWITCH_RATE_LIMIT_RESERVE": "twitch.rate_limit_reserve",
}


def _read_limited(path: Path, limit: int) -> str:
    try:
        with path.open("rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ConfigError(
                    f"configuration source is not a regular file: {path}"
                )
            content = source.read(limit + 1)
        if len(content) > limit:
            raise ConfigError(f"configuration source exceeds size limit: {path}")
        return content.decode("utf-8-sig")
    except ConfigError:
        raise
    except UnicodeDecodeError as error:
        raise ConfigError(f"configuration source is not valid UTF-8: {path}") from error
    except OSError as error:
        raise ConfigError(f"cannot read configuration source: {path}") from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError("JSON contains a duplicate key")
        result[key] = value
    return result


def _flatten_json(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ConfigError("JSON configuration must be an object")
    flattened: dict[str, object] = {}
    for section, value in data.items():
        if section in {"database", "twitch"}:
            if not isinstance(value, dict):
                raise ConfigError(f"JSON section {section!r} must be an object")
            for key, nested in value.items():
                flattened[f"{section}.{key}"] = nested
        else:
            flattened[section] = value
    unknown = flattened.keys() - _JSON_KEYS
    if unknown:
        raise ConfigError(f"unknown JSON configuration key: {sorted(unknown)[0]}")
    return flattened


def _load_json(path: Path) -> dict[str, object]:
    try:
        data = json.loads(
            _read_limited(path, _JSON_LIMIT),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(
                ConfigError("JSON non-finite numbers are not allowed")
            ),
        )
    except ConfigError:
        raise
    except json.JSONDecodeError as error:
        raise ConfigError(
            f"invalid JSON configuration at line {error.lineno}, column {error.colno}"
        ) from error
    return _flatten_json(data)


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    text = _read_limited(path, _ENV_LIMIT)
    if "\x00" in text:
        raise ConfigError(".env contains a NUL character")
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigError(f"invalid .env syntax at line {line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not _ENV_NAME.fullmatch(name):
            raise ConfigError(f"invalid .env name at line {line_number}")
        if name in values:
            raise ConfigError(f"duplicate .env name at line {line_number}")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ConfigError(f"unterminated .env quote at line {line_number}")
            value = value[1:-1]
        if any(token in value for token in ("${", "$(", "`")):
            raise ConfigError(f".env interpolation is not supported at line {line_number}")
        if any(ord(character) < 32 and character != "\t" for character in value):
            raise ConfigError(f".env control character at line {line_number}")
        values[name] = value
    return values


def _validate_path_text(value: object, key: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise ConfigError(f"{key} must be a path")
    text = os.fspath(value)
    if not text or "\x00" in text:
        raise ConfigError(f"{key} must be a non-empty path")
    path = Path(text)
    for part in path.parts:
        stem = part.rstrip(" .").split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED:
            raise ConfigError(f"{key} uses a reserved path component")
        if ":" in part and not (len(part) == 3 and part[1:] == ":\\"):
            raise ConfigError(f"{key} uses an alternate data stream")
    return path


def _inside(path: Path, parent: Path, key: str) -> Path:
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(parent)
    except ValueError as error:
        raise ConfigError(f"{key} must remain inside data_dir") from error
    return resolved


def _is_reparse_point(path: Path) -> bool:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(details, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(details.st_mode) or bool(attributes & reparse_flag)


def _reject_reparse_chain(path: Path, stop: Path) -> None:
    current = path
    while True:
        if _is_reparse_point(current):
            raise ConfigError("configured path must not traverse links or junctions")
        if current == stop or current.parent == current:
            return
        current = current.parent


def _positive_float(value: object, key: str) -> float:
    if isinstance(value, bool):
        raise ConfigError(f"{key} must be a positive number")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{key} must be a positive number") from error
    if not 0 < result <= 300:
        raise ConfigError(f"{key} must be between 0 and 300")
    return result


def _nonnegative_int(value: object, key: str) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{key} must be a non-negative integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ConfigError(f"{key} must be a non-negative integer") from error
    if result < 0 or result > 10000 or str(result) != str(value).strip():
        raise ConfigError(f"{key} must be a non-negative integer")
    return result


def load_config(
    *,
    json_path: Path | None = None,
    env_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, object] | None = None,
) -> AppConfig:
    """Load validated config with overrides > environment > .env > JSON."""
    merged: dict[str, object] = {
        "database.path": "streamos.db",
        "database.timeout_seconds": 5.0,
        "twitch.client_id": None,
        "twitch.access_token": None,
        "twitch.redirect_uri": "http://localhost:8080/auth/callback",
        "twitch.request_timeout_seconds": 30.0,
        "twitch.rate_limit_reserve": 10,
    }
    sources: list[Path] = []
    if json_path is not None:
        json_path = Path(json_path)
        merged.update(_load_json(json_path))
        sources.append(json_path.resolve(strict=False))
    if env_path is not None:
        env_path = Path(env_path)
        env_values = _load_env(env_path)
        unknown = {key for key in env_values if key.startswith("STREAMOS_")} - _ENV_KEYS.keys()
        if unknown:
            raise ConfigError(f"unknown StreamOS environment key: {sorted(unknown)[0]}")
        merged.update(
            {_ENV_KEYS[key]: value for key, value in env_values.items() if key in _ENV_KEYS}
        )
        sources.append(env_path.resolve(strict=False))

    environment = dict(os.environ if environ is None else environ)
    unknown = {key for key in environment if key.startswith("STREAMOS_")} - _ENV_KEYS.keys()
    if unknown:
        raise ConfigError(f"unknown StreamOS environment key: {sorted(unknown)[0]}")
    merged.update(
        {_ENV_KEYS[key]: value for key, value in environment.items() if key in _ENV_KEYS}
    )
    if overrides:
        unknown_overrides = overrides.keys() - _JSON_KEYS
        if unknown_overrides:
            raise ConfigError(f"unknown override key: {sorted(unknown_overrides)[0]}")
        merged.update(overrides)

    default_root = Path(environment.get("APPDATA") or Path.home()) / "StreamOS"
    data_dir = _validate_path_text(
        merged.get("data_dir", default_root),
        "data_dir",
    ).resolve(strict=False)
    database_path = _validate_path_text(merged["database.path"], "database.path")
    if not database_path.is_absolute():
        database_path = data_dir / database_path
    database_path = _inside(database_path, data_dir, "database.path")
    if database_path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        raise ConfigError("database.path must use .db, .sqlite, or .sqlite3")
    if database_path.exists() and database_path.is_dir():
        raise ConfigError("database.path must not be a directory")

    client_id = merged["twitch.client_id"]
    if client_id is not None:
        if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id.strip()):
            raise ConfigError("twitch.client_id has an invalid format")
        client_id = client_id.strip()
    token_value = merged["twitch.access_token"]
    token = None if token_value is None else SecretValue(str(token_value).strip())
    redirect_uri = merged["twitch.redirect_uri"]
    if not isinstance(redirect_uri, str):
        raise ConfigError("twitch.redirect_uri must be a string")
    parsed = urlsplit(redirect_uri)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ConfigError("twitch.redirect_uri is invalid")

    return AppConfig(
        data_dir=data_dir,
        database=DatabaseConfig(
            path=database_path,
            timeout_seconds=_positive_float(
                merged["database.timeout_seconds"],
                "database.timeout_seconds",
            ),
        ),
        twitch=TwitchConfig(
            client_id=client_id,
            access_token=token,
            redirect_uri=redirect_uri,
            request_timeout_seconds=_positive_float(
                merged["twitch.request_timeout_seconds"],
                "twitch.request_timeout_seconds",
            ),
            rate_limit_reserve=_nonnegative_int(
                merged["twitch.rate_limit_reserve"],
                "twitch.rate_limit_reserve",
            ),
        ),
        source_files=tuple(sources),
    )


def prepare_directories(config: AppConfig) -> None:
    """Explicitly create validated application directories."""
    try:
        _reject_reparse_chain(config.data_dir, config.data_dir.anchor and Path(config.data_dir.anchor) or config.data_dir)
        config.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        _reject_reparse_chain(config.data_dir, config.data_dir)
        _inside(config.database.path, config.data_dir.resolve(strict=True), "database.path")
        _reject_reparse_chain(config.database.path.parent, config.data_dir)
        config.database.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _reject_reparse_chain(config.database.path.parent, config.data_dir)
    except OSError as error:
        raise ConfigError("cannot prepare configured directories") from error


__all__ = [
    "AppConfig",
    "ConfigError",
    "DatabaseConfig",
    "SecretValue",
    "TwitchConfig",
    "load_config",
    "prepare_directories",
]
