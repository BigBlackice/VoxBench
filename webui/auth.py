import argparse
import base64
import getpass
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs

from dotenv import load_dotenv
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from webui.config import PROJECT_DIR


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
PUBLIC_PATHS = {"/login", "/logout"}


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def hash_password(password: str, iterations: int = PASSWORD_ITERATIONS) -> str:
    if not password:
        raise ValueError("Password cannot be empty.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return "$".join(
        (
            PASSWORD_SCHEME,
            str(iterations),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, rounds, encoded_salt, encoded_digest = stored_hash.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        iterations = int(rounds)
        if iterations < 100_000:
            return False
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected = base64.urlsafe_b64decode(encoded_digest.encode("ascii"))
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def valid_password_hash(stored_hash: str) -> bool:
    try:
        scheme, rounds, encoded_salt, encoded_digest = stored_hash.split("$", 3)
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        digest = base64.urlsafe_b64decode(encoded_digest.encode("ascii"))
        return (
            scheme == PASSWORD_SCHEME
            and int(rounds) >= 100_000
            and len(salt) >= 16
            and len(digest) == hashlib.sha256().digest_size
        )
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool
    remote_access: bool
    username: str
    password_hash: str
    session_secret: str
    cookie_secure: bool
    port: int

    @property
    def host(self) -> str:
        return "0.0.0.0" if self.remote_access else "127.0.0.1"


def load_auth_settings(env_path: Path | None = None) -> AuthSettings:
    load_dotenv(env_path or PROJECT_DIR / ".env", override=False)
    enabled = _enabled(os.getenv("VOXBENCH_AUTH_ENABLED"))
    remote_access = _enabled(os.getenv("VOXBENCH_REMOTE_ACCESS"))
    username = (os.getenv("VOXBENCH_USERNAME") or "").strip()
    password_hash = (os.getenv("VOXBENCH_PASSWORD_HASH") or "").strip()
    session_secret = (os.getenv("VOXBENCH_SESSION_SECRET") or "").strip()
    cookie_secure = _enabled(os.getenv("VOXBENCH_COOKIE_SECURE"))
    try:
        port = int(os.getenv("VOXBENCH_PORT", "7860"))
    except ValueError as error:
        raise RuntimeError("VOXBENCH_PORT must be a number.") from error
    if not 1 <= port <= 65535:
        raise RuntimeError("VOXBENCH_PORT must be between 1 and 65535.")
    if remote_access and not enabled:
        raise RuntimeError(
            "VOXBENCH_REMOTE_ACCESS requires VOXBENCH_AUTH_ENABLED=true."
        )
    if enabled:
        if not username:
            raise RuntimeError("VOXBENCH_USERNAME is required when login is enabled.")
        if not valid_password_hash(password_hash):
            raise RuntimeError(
                "VOXBENCH_PASSWORD_HASH is missing or invalid. Generate it "
                "with: python -m webui.auth hash-password"
            )
        if len(session_secret) < 32:
            raise RuntimeError(
                "VOXBENCH_SESSION_SECRET must contain at least 32 characters."
            )
    return AuthSettings(
        enabled=enabled,
        remote_access=remote_access,
        username=username,
        password_hash=password_hash,
        session_secret=session_secret,
        cookie_secure=cookie_secure,
        port=port,
    )


def _safe_destination(value: str | None) -> str:
    destination = value or "/"
    if not destination.startswith("/") or destination.startswith("//"):
        return "/"
    return destination


def login_page(next_path: str, error: str = "") -> HTMLResponse:
    message = (
        '<p class="error">Incorrect username or password.</p>' if error else ""
    )
    escaped_next = (
        next_path.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VoxBench login</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
      background: #0f0f11; color: #f4f4f5; font: 16px system-ui, sans-serif; }}
    form {{ width: min(360px, calc(100vw - 48px)); display: grid; gap: 16px;
      padding: 28px; border: 1px solid #3f3f46; border-radius: 8px; }}
    h1 {{ margin: 0 0 4px; font-size: 24px; }}
    label {{ display: grid; gap: 6px; }}
    input, button {{ box-sizing: border-box; width: 100%; padding: 11px 12px;
      border: 1px solid #3f3f46; border-radius: 6px; background: #1d1d20;
      color: #f4f4f5; font: inherit; }}
    button {{ background: transparent; cursor: pointer; font-weight: 600; }}
    button:hover {{ background: #1d1d20; }}
    .error {{ margin: 0; color: #fca5a5; }}
  </style>
</head>
<body>
  <form method="post" action="/login">
    <h1>VoxBench</h1>
    {message}
    <input type="hidden" name="next" value="{escaped_next}">
    <label>Username<input name="username" autocomplete="username" required></label>
    <label>Password<input type="password" name="password"
      autocomplete="current-password" required></label>
    <button type="submit">Sign in</button>
  </form>
</body>
</html>""",
        status_code=401 if error else 200,
    )


class SharedAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            if scope.get("session", {}).get("voxbench_authenticated"):
                await self.app(scope, receive, send)
            else:
                await send({"type": "websocket.close", "code": 4401})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        if request.url.path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        if request.session.get("voxbench_authenticated"):
            await self.app(scope, receive, send)
            return
        if request.method not in {"GET", "HEAD"}:
            response = HTMLResponse("Authentication required.", status_code=401)
        else:
            destination = request.url.path
            if request.url.query:
                destination = f"{destination}?{request.url.query}"
            from urllib.parse import quote

            response = RedirectResponse(
                f"/login?next={quote(destination, safe='/')}",
                status_code=303,
            )
        await response(scope, receive, send)


async def authenticate_login(request: Request, settings: AuthSettings):
    fields = parse_qs((await request.body()).decode("utf-8"))
    username = fields.get("username", [""])[0]
    password = fields.get("password", [""])[0]
    destination = _safe_destination(fields.get("next", ["/"])[0])
    username_matches = hmac.compare_digest(username, settings.username)
    password_matches = verify_password(password, settings.password_hash)
    if not (username_matches and password_matches):
        return login_page(destination, error="invalid")
    request.session.clear()
    request.session["voxbench_authenticated"] = True
    request.session["voxbench_username"] = settings.username
    return RedirectResponse(destination, status_code=303)


def main() -> None:
    parser = argparse.ArgumentParser(description="VoxBench login utilities")
    parser.add_argument(
        "command",
        choices=("hash-password", "generate-secret"),
    )
    args = parser.parse_args()
    if args.command == "hash-password":
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            raise SystemExit("Passwords do not match.")
        print(hash_password(password))
    else:
        print(secrets.token_urlsafe(48))


if __name__ == "__main__":
    main()
