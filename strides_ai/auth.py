"""Strava OAuth2 flow with local token storage and auto-refresh."""

import json
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

import httpx

TOKEN_FILE = Path.home() / ".strides_ai" / "token.json"
AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
REDIRECT_PORT = 8282
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
SCOPES = "read,activity:read_all"


def _load_token() -> dict | None:
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return None


def _save_token(token: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(token, indent=2))


def _is_expired(token: dict) -> bool:
    # Refresh 60 seconds before actual expiry
    return token.get("expires_at", 0) < time.time() + 60


def _refresh_token(client_id: str, client_secret: str, token: dict) -> dict:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
        },
    )
    resp.raise_for_status()
    new_token = resp.json()
    _save_token(new_token)
    return new_token


class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        if "error" in params:
            _CallbackHandler.error = params["error"][0]
            body = b"<h2>Authorization denied. You can close this tab.</h2>"
        elif "code" in params:
            _CallbackHandler.code = params["code"][0]
            body = b"<h2>Authorization successful! You can close this tab.</h2>"
        else:
            body = b"<h2>Unexpected response. You can close this tab.</h2>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # suppress request logs
        pass


def _run_callback_server() -> str:
    """Start a local HTTP server and block until the OAuth callback arrives."""
    _CallbackHandler.code = None
    _CallbackHandler.error = None
    server = HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
    # Keep handling requests until we get the code (browsers often fire
    # extra requests like favicon that we need to skip past).
    while _CallbackHandler.code is None and _CallbackHandler.error is None:
        server.handle_request()
    server.server_close()
    if _CallbackHandler.error:
        raise RuntimeError(f"Strava authorization denied: {_CallbackHandler.error}")
    return _CallbackHandler.code


def _open_browser(url: str) -> None:
    """Try to open a URL in the system browser; silently ignore failures."""
    try:
        version_info = Path("/proc/version").read_text().lower()
        is_wsl = "microsoft" in version_info or "wsl" in version_info
    except OSError:
        is_wsl = False

    if is_wsl:
        # Try wslview (wslu), then cmd.exe by full path, then powershell
        candidates = [
            ["wslview", url],
            ["/mnt/c/Windows/System32/cmd.exe", "/c", "start", "", url],
            [
                "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
                "-NoProfile",
                "-Command",
                f"Start-Process '{url}'",
            ],
        ]
        for cmd in candidates:
            try:
                subprocess.run(cmd, check=False, capture_output=True)
                return
            except OSError:
                continue
    elif sys.platform == "darwin":
        subprocess.run(["open", url], check=False)
    else:
        try:
            subprocess.run(["xdg-open", url], check=False)
        except OSError:
            pass  # URL is already printed; user can paste it manually


def _exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
    )
    resp.raise_for_status()
    token = resp.json()
    _save_token(token)
    return token


def get_access_token(client_id: str, client_secret: str) -> str:
    """
    Return a valid Strava access token, running the OAuth flow if needed.

    - If a stored token exists and is still valid, return it immediately.
    - If stored but expired, auto-refresh and return the new token.
    - If no stored token, open a browser to Strava's auth page, wait for the
      local redirect, exchange the code, persist, and return the token.
    """
    token = _load_token()

    if token:
        if _is_expired(token):
            token = _refresh_token(client_id, client_secret, token)
        return token["access_token"]

    # First-time auth: build the authorization URL and open the browser
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": SCOPES,
    }
    auth_url = f"{AUTH_URL}?{urlencode(params)}"

    print(f"\nOpening Strava authorization page in your browser…")
    print(f"If it doesn't open automatically, paste this URL in your browser:\n\n  {auth_url}\n")
    _open_browser(auth_url)

    code = _run_callback_server()
    token = _exchange_code(client_id, client_secret, code)
    print("Strava authorization successful. Token saved.\n")
    return token["access_token"]
