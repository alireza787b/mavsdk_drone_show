"""Optional MDS authentication primitives.

The module is intentionally framework-light so the same store and recovery
commands can be used by FastAPI routes, bootstrap scripts, tests, and future
agent/MCP tooling.
"""

from __future__ import annotations

import base64
import calendar
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
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
MACHINE_CREDENTIAL_HEADER = "X-MDS-Machine-Credential"
MACHINE_CREDENTIAL_TTL_SECONDS = 15
MACHINE_CREDENTIAL_MAX_TTL_SECONDS = 30
MACHINE_CREDENTIAL_MAX_SIGNERS = 32
MACHINE_CREDENTIAL_MAX_BYTES = 16 * 1024
MACHINE_CREDENTIAL_CLOCK_SKEW_SECONDS = 5
MACHINE_CREDENTIAL_PREFIX = "mdsm1"
MACHINE_CREDENTIAL_SIGNING_DOMAIN = b"mds-gcs-to-node-v1"
MACHINE_CREDENTIAL_REQUIRED_TOKEN_SCOPE = "drone"
ULOG_OP_POLICY_READ = "ulog.policy.read"
ULOG_OP_FILES_READ = "ulog.files.read"
ULOG_OP_SUMMARY_READ = "ulog.summary.read"
ULOG_OP_DOWNLOAD_CREATE = "ulog.download.create"
ULOG_OP_DOWNLOAD_STATUS = "ulog.download.status"
ULOG_OP_DOWNLOAD_DELETE = "ulog.download.delete"
ULOG_OP_DOWNLOAD_CONTENT = "ulog.download.content"
ULOG_OP_ERASE = "ulog.erase"
ULOG_MACHINE_OPERATIONS = frozenset(
    {
        ULOG_OP_POLICY_READ,
        ULOG_OP_FILES_READ,
        ULOG_OP_SUMMARY_READ,
        ULOG_OP_DOWNLOAD_CREATE,
        ULOG_OP_DOWNLOAD_STATUS,
        ULOG_OP_DOWNLOAD_DELETE,
        ULOG_OP_DOWNLOAD_CONTENT,
        ULOG_OP_ERASE,
    }
)
_MACHINE_CREDENTIAL_REPLAY_LIMIT = 4096
_MACHINE_CREDENTIAL_REPLAY_LOCK = threading.Lock()
_MACHINE_CREDENTIAL_REPLAY_CACHE: dict[str, int] = {}


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


class MachineCredentialUnavailable(RuntimeError):
    """Raised when no existing drone machine token can sign a node request."""


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _machine_signing_key(token_hash: str) -> bytes:
    normalized = str(token_hash or "").strip()
    if not normalized.startswith("sha256:") or len(normalized) != len("sha256:") + 64:
        raise ValueError("machine token hash is invalid")
    return hmac.new(
        normalized.encode("ascii"),
        MACHINE_CREDENTIAL_SIGNING_DOMAIN,
        hashlib.sha256,
    ).digest()


def _machine_signing_key_id(signing_key: bytes) -> str:
    return hashlib.sha256(signing_key).hexdigest()[:16]


def _token_record_is_active(record: dict[str, Any], *, now_epoch: int) -> bool:
    if bool(record.get("revoked")):
        return False
    expires_at = record.get("expires_at")
    if not expires_at:
        return True
    try:
        expires_epoch = calendar.timegm(
            time.strptime(str(expires_at), "%Y-%m-%dT%H:%M:%SZ")
        )
    except (TypeError, ValueError):
        return False
    return now_epoch < expires_epoch


def _consume_machine_credential_nonce(jti: str, expires_at: int, *, now_epoch: int) -> bool:
    """Reject immediate replay in one node process while keeping memory bounded."""

    with _MACHINE_CREDENTIAL_REPLAY_LOCK:
        expired = [
            nonce
            for nonce, expiry in _MACHINE_CREDENTIAL_REPLAY_CACHE.items()
            if expiry <= now_epoch
        ]
        for nonce in expired:
            _MACHINE_CREDENTIAL_REPLAY_CACHE.pop(nonce, None)
        if jti in _MACHINE_CREDENTIAL_REPLAY_CACHE:
            return False
        if len(_MACHINE_CREDENTIAL_REPLAY_CACHE) >= _MACHINE_CREDENTIAL_REPLAY_LIMIT:
            oldest = min(
                _MACHINE_CREDENTIAL_REPLAY_CACHE,
                key=_MACHINE_CREDENTIAL_REPLAY_CACHE.__getitem__,
            )
            _MACHINE_CREDENTIAL_REPLAY_CACHE.pop(oldest, None)
        _MACHINE_CREDENTIAL_REPLAY_CACHE[jti] = int(expires_at)
        return True


def verify_machine_credential(
    credential: str | None,
    *,
    bearer_token: str | None,
    audience: str,
    operation: str,
    now_epoch: int | None = None,
    consume_nonce: bool = True,
) -> dict[str, Any] | None:
    """Verify one short-lived GCS-to-node credential with the node machine token."""

    compact = str(credential or "").strip()
    if (
        not compact
        or len(compact.encode("utf-8")) > MACHINE_CREDENTIAL_MAX_BYTES
        or not bearer_token
    ):
        return None
    parts = compact.split(".")
    if len(parts) != 3 or parts[0] != MACHINE_CREDENTIAL_PREFIX:
        return None

    try:
        claims_raw = _urlsafe_decode(parts[1])
        signatures_raw = _urlsafe_decode(parts[2])
        claims = json.loads(claims_raw.decode("utf-8"))
        signatures = json.loads(signatures_raw.decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(claims, dict) or not isinstance(signatures, dict):
        return None

    expected_audience = str(audience or "").strip()
    expected_operation = str(operation or "").strip()
    if (
        claims.get("version") != 1
        or not expected_audience
        or expected_operation not in ULOG_MACHINE_OPERATIONS
        or not hmac.compare_digest(str(claims.get("audience") or ""), expected_audience)
        or not hmac.compare_digest(str(claims.get("operation") or ""), expected_operation)
    ):
        return None

    try:
        issued_at = int(claims["issued_at"])
        expires_at = int(claims["expires_at"])
    except (KeyError, TypeError, ValueError):
        return None
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    if (
        issued_at > now + MACHINE_CREDENTIAL_CLOCK_SKEW_SECONDS
        or expires_at <= now
        or expires_at <= issued_at
        or expires_at - issued_at > MACHINE_CREDENTIAL_MAX_TTL_SECONDS
    ):
        return None

    jti = str(claims.get("jti") or "").strip()
    if len(jti) < 16 or len(jti) > 128:
        return None

    try:
        signing_key = _machine_signing_key(hash_api_token(str(bearer_token)))
    except ValueError:
        return None
    key_id = _machine_signing_key_id(signing_key)
    supplied_signature = signatures.get(key_id)
    if not isinstance(supplied_signature, str):
        return None
    signing_input = f"{MACHINE_CREDENTIAL_PREFIX}.{parts[1]}".encode("ascii")
    expected_signature = _urlsafe_encode(
        hmac.new(signing_key, signing_input, hashlib.sha256).digest()
    )
    if not hmac.compare_digest(supplied_signature, expected_signature):
        return None
    if consume_nonce and not _consume_machine_credential_nonce(
        jti,
        expires_at,
        now_epoch=now,
    ):
        return None
    return dict(claims)


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
        self._scoped_serializers: dict[str, URLSafeTimedSerializer] = {}

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

    def _get_scoped_serializer(self, scope: str) -> URLSafeTimedSerializer:
        normalized_scope = str(scope or "").strip()
        if not normalized_scope:
            raise ValueError("signing scope is required")
        if URLSafeTimedSerializer is None:
            raise RuntimeError("Scoped token signing requires the itsdangerous package.")
        serializer = self._scoped_serializers.get(normalized_scope)
        if serializer is None:
            serializer = URLSafeTimedSerializer(
                _ensure_secret_file(self.settings.session_secret_file),
                salt=f"mds-{normalized_scope}",
            )
            self._scoped_serializers[normalized_scope] = serializer
        return serializer

    def sign_scoped_payload(self, scope: str, payload: dict[str, Any]) -> str:
        """Sign a short-lived internal handle without exposing the signing key."""

        return self._get_scoped_serializer(scope).dumps(dict(payload))

    def verify_scoped_payload(
        self,
        scope: str,
        token: str,
        *,
        max_age_seconds: int,
    ) -> dict[str, Any] | None:
        """Verify one scoped handle and return its object payload."""

        try:
            payload = self._get_scoped_serializer(scope).loads(
                token,
                max_age=max(1, int(max_age_seconds)),
            )
        except (BadSignature, SignatureExpired, TypeError, ValueError):
            return None
        return dict(payload) if isinstance(payload, dict) else None

    def derive_scoped_secret(self, scope: str, payload: dict[str, Any]) -> str:
        """Derive a non-reversible capability from the local signing secret."""

        normalized_scope = str(scope or "").strip()
        if not normalized_scope:
            raise ValueError("secret scope is required")
        signing_secret = _ensure_secret_file(self.settings.session_secret_file).encode("utf-8")
        message = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        digest = hmac.new(
            signing_secret,
            normalized_scope.encode("utf-8") + b"\0" + message,
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def issue_machine_credential(
        self,
        *,
        audience: str,
        operation: str,
        target_ip: str | None = None,
        ttl_seconds: int = MACHINE_CREDENTIAL_TTL_SECONDS,
        now_epoch: int | None = None,
    ) -> str:
        """Issue a scoped node credential from existing active drone tokens.

        The GCS stores only hashes of machine bearer tokens. Those high-entropy
        hashes are domain-separated into signing keys; a node derives the same
        key from its root-readable MDS_GCS_API_TOKEN_FILE token. A recent
        last-used IP narrows signing to the target token. Small bootstrap fleets
        can use a bounded signature set until that association is established.
        """

        normalized_audience = str(audience or "").strip()
        normalized_operation = str(operation or "").strip()
        if not normalized_audience:
            raise ValueError("machine credential audience is required")
        if normalized_operation not in ULOG_MACHINE_OPERATIONS:
            raise ValueError("machine credential operation is not allowed")

        now = int(time.time()) if now_epoch is None else int(now_epoch)
        ttl = max(1, min(int(ttl_seconds), MACHINE_CREDENTIAL_MAX_TTL_SECONDS))
        active_records: list[dict[str, Any]] = []
        for record in self.store.load_tokens().get("tokens", []):
            if not isinstance(record, dict):
                continue
            scopes = {
                str(scope).strip().lower()
                for scope in record.get("scopes", [])
                if str(scope).strip()
            }
            if (
                MACHINE_CREDENTIAL_REQUIRED_TOKEN_SCOPE not in scopes
                or not _token_record_is_active(record, now_epoch=now)
            ):
                continue
            try:
                _machine_signing_key(str(record.get("token_hash") or ""))
            except ValueError:
                continue
            active_records.append(record)

        normalized_target_ip = str(target_ip or "").strip()
        matching_records = [
            record
            for record in active_records
            if normalized_target_ip
            and hmac.compare_digest(
                str(record.get("last_used_ip") or "").strip(),
                normalized_target_ip,
            )
        ]
        signing_records = matching_records or active_records
        if not signing_records:
            raise MachineCredentialUnavailable(
                "No active drone-scoped machine token is available."
            )
        if len(signing_records) > MACHINE_CREDENTIAL_MAX_SIGNERS:
            raise MachineCredentialUnavailable(
                "The target node has no unique recent machine-token association."
            )

        claims = {
            "version": 1,
            "issuer": "mds-gcs",
            "audience": normalized_audience,
            "operation": normalized_operation,
            "issued_at": now,
            "expires_at": now + ttl,
            "jti": secrets.token_urlsafe(24),
        }
        claims_segment = _urlsafe_encode(_canonical_json_bytes(claims))
        signing_input = (
            f"{MACHINE_CREDENTIAL_PREFIX}.{claims_segment}".encode("ascii")
        )
        signatures: dict[str, str] = {}
        for record in signing_records:
            signing_key = _machine_signing_key(str(record["token_hash"]))
            signatures[_machine_signing_key_id(signing_key)] = _urlsafe_encode(
                hmac.new(signing_key, signing_input, hashlib.sha256).digest()
            )
        signature_segment = _urlsafe_encode(_canonical_json_bytes(signatures))
        credential = (
            f"{MACHINE_CREDENTIAL_PREFIX}.{claims_segment}.{signature_segment}"
        )
        if len(credential.encode("utf-8")) > MACHINE_CREDENTIAL_MAX_BYTES:
            raise MachineCredentialUnavailable(
                "Machine credential exceeds the transport header budget."
            )
        return credential

    def setup_required(self) -> bool:
        return self.settings.any_auth_enabled and not self.store.has_users()

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
        elif "operator" in scopes or "drone" in scopes:
            role = "operator"
        elif "agent" in scopes:
            role = "agent"
        return {
            "kind": "bearer",
            "username": token_record.get("name") or token_record.get("id"),
            "role": role,
            "token": token_record,
            "scopes": sorted(scopes),
        }


def build_auth_service() -> AuthService:
    return AuthService(AuthSettings.from_env())
