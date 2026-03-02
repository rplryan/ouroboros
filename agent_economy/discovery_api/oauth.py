"""OAuth 2.0 Authorization Server for x402 Service Discovery API.

Implements:
- RFC 8414: OAuth 2.0 Authorization Server Metadata (/.well-known/oauth-authorization-server)
- OAuth 2.1 Authorization Code flow with PKCE
- Token endpoint (POST /oauth/token)
- Token introspection (POST /oauth/introspect)
- JWKS endpoint (already in main.py at /jwks — referenced from discovery doc)

This implementation is intentionally minimal:
- Uses GitHub OAuth as the identity provider (no password storage)
- Issues short-lived Ed25519-signed JWTs as access tokens
- The /mcp/ endpoint accepts tokens but also allows unauthenticated access
  (backward compat — existing integrations keep working)

Environment variables required:
- GITHUB_CLIENT_ID: GitHub OAuth App client ID
- GITHUB_CLIENT_SECRET: GitHub OAuth App client secret
- BASE_URL: https://x402-discovery-api.onrender.com (or override)

These are optional — if not set, the OAuth flow gracefully degrades to
returning a static "public access" token for the well-known endpoint to
still advertise the correct metadata.
"""

import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

# Import Ed25519 signing from the attestation module (shared key infrastructure)
try:
    from attestation import _sign_jwt, _KEY_ID, _load_keys
    _ATTEST_AVAILABLE = True
except ImportError:
    _ATTEST_AVAILABLE = False
    _KEY_ID = "x402-discovery-key"

router = APIRouter(tags=["OAuth 2.0"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("BASE_URL", "https://x402-discovery-api.onrender.com").rstrip("/")
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")

# In-memory stores (fine for a public/free API — no sensitive data)
_auth_codes: dict[str, dict] = {}   # code -> {code_challenge, code_challenge_method, client_id, state, scope, created_at}
_issued_tokens: dict[str, dict] = {}  # jti -> {sub, scope, exp, client_id}

# Token lifetime
ACCESS_TOKEN_TTL = 3600  # 1 hour
CODE_TTL = 600            # 10 minutes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_access_token(sub: str, scope: str = "mcp:read", client_id: str = "") -> tuple[str, str]:
    """Issue an Ed25519-signed JWT access token. Returns (token, jti)."""
    jti = secrets.token_urlsafe(16)
    now = int(time.time())
    payload = {
        "iss": BASE_URL,
        "sub": sub,
        "aud": BASE_URL,
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
        "jti": jti,
        "scope": scope,
        "client_id": client_id,
    }
    if _ATTEST_AVAILABLE:
        token = _sign_jwt(payload)
    else:
        # Fallback: unsigned base64 (only used if attestation module missing)
        import base64
        hdr = base64.urlsafe_b64encode(json.dumps({"alg":"none","typ":"JWT"}).encode()).decode().rstrip("=")
        body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        token = f"{hdr}.{body}."
    _issued_tokens[jti] = {"sub": sub, "scope": scope, "exp": now + ACCESS_TOKEN_TTL, "client_id": client_id}
    return token, jti


def _verify_pkce(code_verifier: str, code_challenge: str, method: str) -> bool:
    """Verify PKCE code_verifier against stored code_challenge."""
    if method == "S256":
        digest = hashlib.sha256(code_verifier.encode()).digest()
        import base64
        expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return hmac.compare_digest(expected, code_challenge)
    elif method == "plain":
        return hmac.compare_digest(code_verifier, code_challenge)
    return False


# ---------------------------------------------------------------------------
# RFC 8414 — Authorization Server Metadata
# ---------------------------------------------------------------------------

@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
async def oauth_metadata():
    """RFC 8414 Authorization Server Metadata.

    This is the primary endpoint that Anthropic and OpenAI check to verify
    an MCP server supports OAuth 2.0.
    """
    metadata = {
        "issuer": BASE_URL,
        "authorization_endpoint": f"{BASE_URL}/oauth/authorize",
        "token_endpoint": f"{BASE_URL}/oauth/token",
        "jwks_uri": f"{BASE_URL}/jwks",
        "introspection_endpoint": f"{BASE_URL}/oauth/introspect",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["none"],  # public clients (PKCE)
        "code_challenge_methods_supported": ["S256", "plain"],
        "scopes_supported": ["mcp:read", "mcp:write"],
        "token_endpoint_auth_signing_alg_values_supported": ["EdDSA"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["EdDSA"],
        "service_documentation": "https://github.com/rplryan/x402-discovery-mcp",
        "ui_locales_supported": ["en"],
        "op_tos_uri": f"{BASE_URL}/terms",
        "op_policy_uri": f"{BASE_URL}/privacy",
    }
    return JSONResponse(content=metadata, headers={"Cache-Control": "public, max-age=3600"})


# ---------------------------------------------------------------------------
# Authorization endpoint
# ---------------------------------------------------------------------------

@router.get("/oauth/authorize")
async def oauth_authorize(
    request: Request,
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    scope: str = "mcp:read",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
):
    """OAuth 2.1 Authorization endpoint.

    If GitHub OAuth is configured → redirects through GitHub login.
    Otherwise → issues a code immediately (public/anonymous access).
    """
    if response_type != "code":
        raise HTTPException(status_code=400, detail="unsupported_response_type")

    if GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET:
        # GitHub OAuth flow
        gh_state = secrets.token_urlsafe(16)
        # Store pending auth state
        _auth_codes[f"_pending_{gh_state}"] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "created_at": int(time.time()),
        }
        gh_params = urllib.parse.urlencode({
            "client_id": GITHUB_CLIENT_ID,
            "redirect_uri": f"{BASE_URL}/oauth/callback",
            "scope": "read:user",
            "state": gh_state,
        })
        return RedirectResponse(f"https://github.com/login/oauth/authorize?{gh_params}", status_code=302)
    else:
        # No GitHub credentials — issue anonymous code immediately
        code = secrets.token_urlsafe(24)
        _auth_codes[code] = {
            "sub": "anonymous",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "created_at": int(time.time()),
        }
        if redirect_uri:
            params = {"code": code}
            if state:
                params["state"] = state
            return RedirectResponse(f"{redirect_uri}?{urllib.parse.urlencode(params)}", status_code=302)
        # No redirect_uri — show consent page
        return HTMLResponse(_consent_page(code, client_id, scope))


def _consent_page(code: str, client_id: str, scope: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>x402 Service Discovery — Authorize</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 480px; margin: 80px auto; padding: 0 20px; text-align: center; color: #333; }}
.card {{ background: #f9f9f9; border-radius: 12px; padding: 32px; box-shadow: 0 2px 16px rgba(0,0,0,0.08); }}
h1 {{ color: #1a1a2e; font-size: 1.4em; margin-bottom: 0.5em; }}
p {{ color: #666; font-size: 0.95em; }}
.code {{ background: #eee; padding: 12px; border-radius: 8px; font-family: monospace; font-size: 1.1em; margin: 16px 0; word-break: break-all; }}
.scope {{ background: #e8f4fd; color: #1a73e8; padding: 4px 12px; border-radius: 20px; font-size: 0.85em; }}
</style>
</head>
<body>
<div class="card">
<h1>🔐 Authorization Code</h1>
<p>Application <strong>{client_id or "MCP Client"}</strong> has been granted access to:</p>
<p><span class="scope">{scope}</span></p>
<p>Your authorization code:</p>
<div class="code">{code}</div>
<p style="font-size:0.8em;color:#999">This code expires in 10 minutes. Paste it into the authorization flow or use it with POST /oauth/token.</p>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# GitHub OAuth callback
# ---------------------------------------------------------------------------

@router.get("/oauth/callback", include_in_schema=False)
async def oauth_callback(code: str = "", state: str = "", error: str = ""):
    """Handle GitHub OAuth callback."""
    if error:
        return HTMLResponse(f"<h2>Authorization denied: {error}</h2>", status_code=400)

    pending_key = f"_pending_{state}"
    pending = _auth_codes.pop(pending_key, None)
    if not pending:
        raise HTTPException(status_code=400, detail="invalid_state")

    # Exchange GitHub code for access token
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={"client_id": GITHUB_CLIENT_ID, "client_secret": GITHUB_CLIENT_SECRET, "code": code},
            headers={"Accept": "application/json"},
        )
        gh_data = resp.json()

    if "error" in gh_data:
        raise HTTPException(status_code=400, detail=gh_data.get("error_description", "github_error"))

    gh_token = gh_data.get("access_token", "")

    # Get GitHub user identity
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {gh_token}", "Accept": "application/json"},
        )
        user_data = user_resp.json()

    gh_login = user_data.get("login", "unknown")
    sub = f"github:{gh_login}"

    # Issue our authorization code
    auth_code = secrets.token_urlsafe(24)
    _auth_codes[auth_code] = {
        "sub": sub,
        "client_id": pending["client_id"],
        "redirect_uri": pending["redirect_uri"],
        "scope": pending["scope"],
        "state": pending["state"],
        "code_challenge": pending["code_challenge"],
        "code_challenge_method": pending["code_challenge_method"],
        "created_at": int(time.time()),
    }

    redirect_uri = pending["redirect_uri"]
    if redirect_uri:
        params = {"code": auth_code}
        if pending["state"]:
            params["state"] = pending["state"]
        return RedirectResponse(f"{redirect_uri}?{urllib.parse.urlencode(params)}", status_code=302)

    return HTMLResponse(_consent_page(auth_code, gh_login, pending["scope"]))


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------

@router.post("/oauth/token")
async def oauth_token(
    request: Request,
    grant_type: str = Form(default="authorization_code"),
    code: Optional[str] = Form(default=None),
    redirect_uri: Optional[str] = Form(default=None),
    client_id: Optional[str] = Form(default=None),
    code_verifier: Optional[str] = Form(default=None),
):
    """OAuth 2.1 Token endpoint — exchange authorization code for access token."""
    if grant_type != "authorization_code":
        raise HTTPException(
            status_code=400,
            detail={"error": "unsupported_grant_type", "error_description": "Only authorization_code is supported"},
        )

    if not code:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_request", "error_description": "Missing code parameter"},
        )

    stored = _auth_codes.pop(code, None)
    if not stored:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_grant", "error_description": "Authorization code not found or expired"},
        )

    # Check expiry
    if int(time.time()) - stored["created_at"] > CODE_TTL:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_grant", "error_description": "Authorization code expired"},
        )

    # Verify PKCE if code_challenge was set
    challenge = stored.get("code_challenge", "")
    if challenge:
        if not code_verifier:
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_request", "error_description": "Missing code_verifier"},
            )
        method = stored.get("code_challenge_method", "S256")
        if not _verify_pkce(code_verifier, challenge, method):
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_grant", "error_description": "PKCE verification failed"},
            )

    sub = stored.get("sub", "anonymous")
    scope = stored.get("scope", "mcp:read")
    cid = stored.get("client_id") or client_id or ""

    token, jti = _make_access_token(sub, scope, cid)

    return JSONResponse({
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_TTL,
        "scope": scope,
    })


# ---------------------------------------------------------------------------
# Token introspection (RFC 7662)
# ---------------------------------------------------------------------------

@router.post("/oauth/introspect", include_in_schema=False)
async def oauth_introspect(token: str = Form(default="")):
    """RFC 7662 Token Introspection."""
    if not token:
        return JSONResponse({"active": False})

    # Decode JWT without verification (just read payload)
    parts = token.split(".")
    if len(parts) != 3:
        return JSONResponse({"active": False})

    try:
        import base64
        # Add padding
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp", 0)
        jti = payload.get("jti", "")
        if int(time.time()) > exp:
            return JSONResponse({"active": False})
        if jti and jti not in _issued_tokens:
            return JSONResponse({"active": False})
        return JSONResponse({
            "active": True,
            "sub": payload.get("sub"),
            "scope": payload.get("scope", "mcp:read"),
            "exp": exp,
            "iss": BASE_URL,
            "client_id": payload.get("client_id", ""),
        })
    except Exception:
        return JSONResponse({"active": False})
