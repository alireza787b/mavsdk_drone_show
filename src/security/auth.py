"""Optional MDS authentication primitives.

The module is intentionally framework-light so the same store and recovery
commands can be used by FastAPI routes, bootstrap scripts, tests, and future
agent/MCP tooling.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
except Exception:  # pragma: no cover - exercised by lean installer Python
    class BadSignature(Exception):
        pass

    class SignatureExpired(BadSignature):
        pass

    URLSafeTimedSerializer = None

try:  # Prefer Argon2id through pwdlib when installed from requirements.txt.
    from pwdlib import PasswordHash

    _PASSWORD_HASHER = PasswordHash.recommended()
except Exception:  # pragma: no cover - exercised only in lean environments
    _PASSWORD_HASHER = None


AUTH_DOCS_URL = "/docs/guides/gcs-auth.md"
DEFAULT_AUTH_DIR = Path("/etc/mds/auth")
DEFAULT_USERS_FILE = DEFAULT_AUTH_DIR / "users.json"
DEFAULT_TOKENS_FILE = DEFAULT_AUTH_DIR / "api_tokens.json"
DEFAULT_SESSION_SECRET_FILE = DEFAULT_AUTH_DIR / "session_secret"
DEFAULT_CSRF_SECRET_FILE = DEFAULT_AUTH_DIR / "csrf_secret"
SESSION_COOKIE_NAME = "mds_session"
CSRF_COOKIE_NAME = "mds_csrf"
VALID_ROLES = {"admin", "operator", "viewer"}
VALID_TOKEN_SCOPES = {"admin", "operator", "viewer", "agent", "drone", "readonly"}
PBKDF2_ITERATIONS = 600_000


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _normalize_username(username: str) -> str:
    normalized = str(username or "").strip().lower()
    if not normalized:
        raise ValueError("username is required")
    if len(normalized) > 64:
        raise ValueError("username is too long")
    if not all(ch.isalnum() or ch in {"-", "_", "."} for ch in normalized):
        raise ValueError("username may only contain letters, numbers, dash, underscore, and dot")
    return normalized


def _normalize_role(role: str) -> str:
    normalized = str(role or "").strip().lower()
    if normalized not in VALID_ROLES:
        raise ValueError(f"role must be one of: {', '.join(sorted(VALID_ROLES))}")
    return normalized


def _atomic_write_json(path: Path, payload: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _read_json_file(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return default
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def _ensure_secret_file(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass

    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value

    secret_value = secrets.token_urlsafe(48)
    path.write_text(f"{secret_value}\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return secret_value


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password is required")

    if _PASSWORD_HASHER is not None:
        return _PASSWORD_HASHER.hash(password)

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${iterations}${salt}${digest}".format(
        iterations=PBKDF2_ITERATIONS,
        salt=base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        digest=base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    )


def _verify_pbkdf2(password: str, stored_hash: str) -> bool:
    try:
        scheme, iterations_raw, salt_raw, digest_raw = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw + "=" * (-len(salt_raw) % 4))
        expected = base64.urlsafe_b64decode(digest_raw + "=" * (-len(digest_raw) % 4))
    except Exception:
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def verify_password(password: str, stored_hash: str) -> bool:
    if not password or not stored_hash:
        return False
    if stored_hash.startswith("pbkdf2_sha256$"):
        return _verify_pbkdf2(password, stored_hash)
    if _PASSWORD_HASHER is None:
        return False
    try:
        return bool(_PASSWORD_HASHER.verify(password, stored_hash))
    except Exception:
        return False


def hash_api_token(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def verify_api_token(token: str, stored_hash: str) -> bool:
    if not token or not stored_hash:
        return False
    return hmac.compare_digest(hash_api_token(token), stored_hash)


@dataclass(frozen=True)
class AuthSettings:
    dashboard_auth_enabled: bool
    api_auth_enabled: bool
    users_file: Path
    tokens_file: Path
    session_secret_file: Path
    csrf_secret_file: Path
    session_ttl_hours: int
    secure_cookies: bool
    csrf_enabled: bool
    allowed_cidrs: tuple[str, ...]
    trusted_proxy_cidrs: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "AuthSettings":
        ttl_raw = os.environ.get("MDS_AUTH_SESSION_TTL_HOURS", "12")
        try:
            ttl_hours = max(1, min(int(ttl_raw), 24 * 30))
        except ValueError:
            ttl_hours = 12

        def _split_csv(name: str) -> tuple[str, ...]:
            raw = os.environ.get(name, "")
            return tuple(part.strip() for part in raw.split(",") if part.strip())

        return cls(
            dashboard_auth_enabled=parse_bool(os.environ.get("MDS_AUTH_ENABLED"), default=False),
            api_auth_enabled=parse_bool(os.environ.get("MDS_API_AUTH_ENABLED"), default=False),
            users_file=Path(os.environ.get("MDS_AUTH_USERS_FILE", str(DEFAULT_USERS_FILE))),
            tokens_file=Path(os.environ.get("MDS_API_TOKENS_FILE", str(DEFAULT_TOKENS_FILE))),
            session_secret_file=Path(os.environ.get("MDS_AUTH_SESSION_SECRET_FILE", str(DEFAULT_SESSION_SECRET_FILE))),
            csrf_secret_file=Path(os.environ.get("MDS_AUTH_CSRF_SECRET_FILE", str(DEFAULT_CSRF_SECRET_FILE))),
            session_ttl_hours=ttl_hours,
            secure_cookies=parse_bool(os.environ.get("MDS_AUTH_SECURE_COOKIES"), default=False),
            csrf_enabled=parse_bool(os.environ.get("MDS_AUTH_CSRF_ENABLED"), default=True),
            allowed_cidrs=_split_csv("MDS_AUTH_ALLOWED_CIDRS"),
            trusted_proxy_cidrs=_split_csv("MDS_AUTH_TRUSTED_PROXY_CIDRS"),
        )

    @property
    def any_auth_enabled(self) -> bool:
        return self.dashboard_auth_enabled or self.api_auth_enabled

    @property
    def session_ttl_seconds(self) -> int:
        return self.session_ttl_hours * 3600


class AuthStore:
    """Local file-backed user and token store."""

    def __init__(self, settings: AuthSettings):
        self.settings = settings

    def load_users(self) -> dict[str, Any]:
        return _read_json_file(self.settings.users_file, {"version": 1, "users": []})

    def save_users(self, payload: dict[str, Any]) -> None:
        _atomic_write_json(self.settings.users_file, payload, mode=0o600)

    def load_tokens(self) -> dict[str, Any]:
        return _read_json_file(self.settings.tokens_file, {"version": 1, "tokens": []})

    def save_tokens(self, payload: dict[str, Any]) -> None:
        _atomic_write_json(self.settings.tokens_file, payload, mode=0o600)

    def list_users(self) -> list[dict[str, Any]]:
        users = self.load_users().get("users", [])
        return [dict(user) for user in users if isinstance(user, dict)]

    def find_user(self, username: str) -> dict[str, Any] | None:
        normalized = _normalize_username(username)
        for user in self.list_users():
            if _normalize_username(str(user.get("username", ""))) == normalized:
                return user
        return None

    def has_users(self) -> bool:
        return bool(self.list_users())

    def upsert_user(
        self,
        username: str,
        password: str | None = None,
        role: str = "operator",
        disabled: bool = False,
        force_password_change: bool = False,
    ) -> dict[str, Any]:
        normalized = _normalize_username(username)
        normalized_role = _normalize_role(role)
        payload = self.load_users()
        users = payload.setdefault("users", [])
        now = utc_now_iso()
        existing = None
        for user in users:
            if isinstance(user, dict) and _normalize_username(str(user.get("username", ""))) == normalized:
                existing = user
                break

        if existing is None:
            if password is None:
                raise ValueError("password is required for new user")
            existing = {
                "username": normalized,
                "created_at": now,
            }
            users.append(existing)

        existing["role"] = normalized_role
        existing["disabled"] = bool(disabled)
        existing["force_password_change"] = bool(force_password_change)
        existing["updated_at"] = now
        if password is not None:
            existing["password_hash"] = hash_password(password)
            existing["password_changed_at"] = now

        self.save_users(payload)
        return self.sanitize_user(existing)

    def set_password(self, username: str, password: str, force_password_change: bool = False) -> dict[str, Any]:
        user = self.find_user(username)
        if user is None:
            raise KeyError("user not found")
        return self.upsert_user(
            username=str(user["username"]),
            password=password,
            role=str(user.get("role", "operator")),
            disabled=bool(user.get("disabled", False)),
            force_password_change=force_password_change,
        )

    def set_user_state(self, username: str, *, role: str | None = None, disabled: bool | None = None) -> dict[str, Any]:
        user = self.find_user(username)
        if user is None:
            raise KeyError("user not found")
        return self.upsert_user(
            username=str(user["username"]),
            password=None,
            role=role or str(user.get("role", "operator")),
            disabled=bool(user.get("disabled", False)) if disabled is None else bool(disabled),
            force_password_change=bool(user.get("force_password_change", False)),
        )

    def authenticate_user(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.find_user(username)
        if not user or user.get("disabled"):
            return None
        if not verify_password(password, str(user.get("password_hash", ""))):
            return None
        return self.sanitize_user(user)

    @staticmethod
    def sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
        return {
            "username": str(user.get("username", "")),
            "role": str(user.get("role", "operator")),
            "disabled": bool(user.get("disabled", False)),
            "force_password_change": bool(user.get("force_password_change", False)),
            "created_at": user.get("created_at"),
            "updated_at": user.get("updated_at"),
            "password_changed_at": user.get("password_changed_at"),
        }

    def create_token(
        self,
        name: str,
        scopes: list[str],
        created_by: str = "system",
        ttl_seconds: int | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("token name is required")
        clean_scopes = sorted({str(scope).strip().lower() for scope in scopes if str(scope).strip()})
        if not clean_scopes:
            clean_scopes = ["readonly"]
        invalid = [scope for scope in clean_scopes if scope not in VALID_TOKEN_SCOPES]
        if invalid:
            raise ValueError(f"invalid token scopes: {', '.join(invalid)}")

        token_plaintext = f"mds_{secrets.token_urlsafe(36)}"
        token_id = f"tok_{secrets.token_hex(8)}"
        now_epoch = int(time.time())
        now = utc_now_iso()
        expires_at = None
        if ttl_seconds is not None and ttl_seconds > 0:
            expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_epoch + ttl_seconds))

        record = {
            "id": token_id,
            "name": clean_name,
            "token_hash": hash_api_token(token_plaintext),
            "scopes": clean_scopes,
            "created_by": str(created_by or "system"),
            "created_at": now,
            "expires_at": expires_at,
            "revoked": False,
            "last_used_at": None,
            "last_used_ip": None,
            "notes": str(notes or ""),
        }

        payload = self.load_tokens()
        payload.setdefault("tokens", []).append(record)
        self.save_tokens(payload)
        public_record = self.sanitize_token(record)
        public_record["token"] = token_plaintext
        return public_record

    def list_tokens(self) -> list[dict[str, Any]]:
        tokens = self.load_tokens().get("tokens", [])
        return [self.sanitize_token(token) for token in tokens if isinstance(token, dict)]

    def revoke_token(self, token_id: str) -> dict[str, Any]:
        payload = self.load_tokens()
        target = None
        for token in payload.get("tokens", []):
            if isinstance(token, dict) and token.get("id") == token_id:
                target = token
                break
        if target is None:
            raise KeyError("token not found")
        target["revoked"] = True
        target["revoked_at"] = utc_now_iso()
        self.save_tokens(payload)
        return self.sanitize_token(target)

    def verify_token(self, token_plaintext: str, source_ip: str | None = None) -> dict[str, Any] | None:
        payload = self.load_tokens()
        now = time.time()
        changed = False
        for token in payload.get("tokens", []):
            if not isinstance(token, dict) or token.get("revoked"):
                continue
            expires_at = token.get("expires_at")
            if expires_at:
                try:
                    expires_epoch = time.mktime(time.strptime(str(expires_at), "%Y-%m-%dT%H:%M:%SZ"))
                    if now >= expires_epoch:
                        continue
                except ValueError:
                    continue
            if verify_api_token(token_plaintext, str(token.get("token_hash", ""))):
                token["last_used_at"] = utc_now_iso()
                token["last_used_ip"] = source_ip
                changed = True
                if changed:
                    self.save_tokens(payload)
                return self.sanitize_token(token)
        return None

    @staticmethod
    def sanitize_token(token: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": token.get("id"),
            "name": token.get("name"),
            "scopes": list(token.get("scopes", [])) if isinstance(token.get("scopes", []), list) else [],
            "created_by": token.get("created_by"),
            "created_at": token.get("created_at"),
            "expires_at": token.get("expires_at"),
            "revoked": bool(token.get("revoked", False)),
            "revoked_at": token.get("revoked_at"),
            "last_used_at": token.get("last_used_at"),
            "last_used_ip": token.get("last_used_ip"),
            "notes": token.get("notes", ""),
        }


class AuthService:
    """High-level auth service used by API routes and middleware."""

    def __init__(self, settings: AuthSettings | None = None):
        self.settings = settings or AuthSettings.from_env()
        self.store = AuthStore(self.settings)
        self._session_serializer: URLSafeTimedSerializer | None = None
        self._csrf_serializer: URLSafeTimedSerializer | None = None

    def _get_session_serializer(self) -> URLSafeTimedSerializer:
        if URLSafeTimedSerializer is None:
            raise RuntimeError("Dashboard session signing requires the itsdangerous package.")
        if self._session_serializer is None:
            self._session_serializer = URLSafeTimedSerializer(
                _ensure_secret_file(self.settings.session_secret_file),
                salt="mds-session-v1",
            )
        return self._session_serializer

    def _get_csrf_serializer(self) -> URLSafeTimedSerializer:
        if URLSafeTimedSerializer is None:
            raise RuntimeError("Dashboard CSRF signing requires the itsdangerous package.")
        if self._csrf_serializer is None:
            self._csrf_serializer = URLSafeTimedSerializer(
                _ensure_secret_file(self.settings.csrf_secret_file),
                salt="mds-csrf-v1",
            )
        return self._csrf_serializer

    def setup_required(self) -> bool:
        return self.settings.dashboard_auth_enabled and not self.store.has_users()

    def create_session(self, user: dict[str, Any]) -> tuple[str, str]:
        csrf = secrets.token_urlsafe(32)
        payload = {
            "sub": user["username"],
            "role": user["role"],
            "sid": secrets.token_hex(16),
            "csrf": csrf,
            "iat": int(time.time()),
        }
        session_token = self._get_session_serializer().dumps(payload)
        csrf_token = self._get_csrf_serializer().dumps({"sid": payload["sid"], "csrf": csrf})
        return session_token, csrf_token

    def verify_session(self, session_token: str | None) -> dict[str, Any] | None:
        if not session_token:
            return None
        try:
            payload = self._get_session_serializer().loads(session_token, max_age=self.settings.session_ttl_seconds)
        except (BadSignature, SignatureExpired):
            return None
        username = payload.get("sub")
        user = self.store.find_user(str(username or ""))
        if not user or user.get("disabled"):
            return None
        sanitized = self.store.sanitize_user(user)
        return {
            "kind": "session",
            "username": sanitized["username"],
            "role": sanitized["role"],
            "csrf": payload.get("csrf"),
            "sid": payload.get("sid"),
            "user": sanitized,
        }

    def verify_csrf(self, auth_context: dict[str, Any], csrf_header: str | None) -> bool:
        if not self.settings.csrf_enabled:
            return True
        if auth_context.get("kind") != "session":
            return True
        if not csrf_header:
            return False
        try:
            payload = self._get_csrf_serializer().loads(csrf_header, max_age=self.settings.session_ttl_seconds)
        except (BadSignature, SignatureExpired):
            return False
        return (
            hmac.compare_digest(str(payload.get("sid")), str(auth_context.get("sid")))
            and hmac.compare_digest(str(payload.get("csrf")), str(auth_context.get("csrf")))
        )

    def csrf_token_for_context(self, auth_context: dict[str, Any]) -> str | None:
        if auth_context.get("kind") != "session":
            return None
        sid = auth_context.get("sid")
        csrf = auth_context.get("csrf")
        if not sid or not csrf:
            return None
        return self._get_csrf_serializer().dumps({"sid": sid, "csrf": csrf})

    def authenticate_bearer(self, bearer_token: str | None, source_ip: str | None = None) -> dict[str, Any] | None:
        if not bearer_token:
            return None
        token_record = self.store.verify_token(bearer_token, source_ip=source_ip)
        if token_record is None:
            return None
        role = "viewer"
        scopes = set(token_record.get("scopes", []))
        if "admin" in scopes:
            role = "admin"
        elif "operator" in scopes or "agent" in scopes or "drone" in scopes:
            role = "operator"
        return {
            "kind": "bearer",
            "username": token_record.get("name") or token_record.get("id"),
            "role": role,
            "token": token_record,
            "scopes": sorted(scopes),
        }


def build_auth_service() -> AuthService:
    return AuthService(AuthSettings.from_env())
