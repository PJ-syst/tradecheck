"""Binance OAuth metadata discovery. No account or trading tools are called."""

import json
import re
import argparse
import base64
import hashlib
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError
from urllib.parse import urlparse, urlencode, parse_qs
from urllib.request import Request, build_opener

from backend.interpreter import NoRedirect

ENDPOINT = "https://agent.binance.com/mcp/agentic"
CLIENT_ID = "https://pj-syst.github.io/tradecheck/oauth-client.json"
REDIRECT = "http://127.0.0.1:8765/callback"


def official_url(value):
    if not isinstance(value, str):
        raise ValueError("Missing Binance OAuth URL.")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or not (parsed.hostname == "binance.com" or parsed.hostname.endswith(".binance.com")) or parsed.username or parsed.password or parsed.fragment or parsed.port not in {None, 443}:
        raise ValueError("OAuth metadata points outside the supported Binance HTTPS hosts.")
    return value


def read_json(url):
    with build_opener(NoRedirect()).open(Request(official_url(url), headers={"Accept": "application/json"}), timeout=10) as response:
        body = response.read(262145)
        if len(body) > 262144:
            raise ValueError("OAuth metadata is too large.")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ValueError("Invalid OAuth metadata.")
        return result


def discover():
    request = Request(ENDPOINT, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "TradeCheck", "version": "0.3"}}}).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=10):
            raise ValueError("MCP did not advertise an OAuth challenge.")
    except HTTPError as exc:
        challenge = exc.headers.get("WWW-Authenticate", "")
        status = exc.code
        exc.close()
        if status != 401:
            raise ValueError(f"MCP discovery returned HTTP {status}.") from None
    match = re.search(r'resource_metadata="([^"]+)"', challenge)
    if not match:
        raise ValueError("MCP did not advertise protected-resource metadata.")
    resource = read_json(match[1])
    servers = resource.get("authorization_servers")
    if not isinstance(servers, list) or len(servers) != 1:
        raise ValueError("Expected one advertised Binance authorization server.")
    issuer = official_url(servers[0]).rstrip("/")
    parsed = urlparse(issuer)
    metadata = read_json(f"https://{parsed.netloc}/.well-known/oauth-authorization-server{parsed.path}")
    if metadata.get("issuer", "").rstrip("/") != issuer:
        raise ValueError("OAuth issuer mismatch.")
    for name in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
        if name in metadata:
            official_url(metadata[name])
    official_url(resource.get("resource"))
    return {"resource": resource, "authorization_server": metadata}


def authorization_parameters(state, verifier):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return {"response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT,
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "resource": ENDPOINT}


def callback_code(path, expected_state):
    parsed = urlparse(path)
    query = parse_qs(parsed.query)
    if parsed.path != "/callback" or len(query.get("state", [])) != 1 or not secrets.compare_digest(query["state"][0], expected_state):
        raise ValueError("Invalid sign-in callback state.")
    if "error" in query:
        raise ValueError("Binance sign-in was declined or could not complete.")
    codes = query.get("code", [])
    if len(codes) != 1 or not 1 <= len(codes[0]) <= 8192:
        raise ValueError("Binance did not return a valid authorization code.")
    return codes[0]


def login(open_browser=True):
    raise ValueError("Binance rejected TradeCheck's custom client as unsupported (3346001). Use the supported Codex client: codex mcp add binance --url https://agent.binance.com/mcp/agentic. Do not copy Codex tokens into TradeCheck.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect Binance OAuth metadata or sign in locally")
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        if args.login:
            login(not args.no_browser)
        else:
            print(json.dumps(discover(), indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(1, (f"Binance sign-in returned HTTP {exc.code}." if isinstance(exc, HTTPError) else str(exc)) + "\n")
