"""App-owned ChatGPT plan authorization. Tokens never enter the prospect database."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import jwt
import requests
from filelock import FileLock

from local_presence_miner.config import protect_secret, unprotect_secret

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"


def intelligence_data_dir() -> Path:
    """Independent of the configurable/synced project data location."""
    if os.name != "nt" or not os.getenv("LOCALAPPDATA"):
        raise ValueError("ChatGPT connection requires Windows protected local storage.")
    root = Path(os.environ["LOCALAPPDATA"]).resolve() / "LocalPresenceMiner" / "intelligence"
    if any("onedrive" in part.lower() for part in root.parts):
        raise ValueError("ChatGPT credentials cannot be stored in OneDrive.")
    return root


class ProtectedCredentialStore:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or intelligence_data_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "connection.dpapi"
        self.lock = FileLock(str(self.directory / "connection.lock"), timeout=15)

    def read(self) -> dict:
        if not self.path.exists():
            return {"host_id": "urn:uuid:" + str(uuid4()), "active": "", "accounts": {}}
        try:
            encrypted = self.path.read_text(encoding="utf-8")
            if not encrypted.startswith("dpapi:"):
                raise ValueError
            value = json.loads(unprotect_secret(encrypted))
            if not isinstance(value, dict) or not isinstance(value.get("accounts"), dict) or not value.get("host_id"):
                raise ValueError
            return value
        except (ValueError, OSError, KeyError) as exc:
            raise ValueError("The protected ChatGPT connection could not be read; reconnect it.") from exc

    def write(self, value: dict) -> None:
        protected = protect_secret(json.dumps(value, separators=(",", ":")))
        if not protected.startswith("dpapi:"):
            raise ValueError("Protected Windows credential storage is unavailable.")
        temporary = self.path.with_name("connection." + secrets.token_hex(8) + ".tmp")
        try:
            temporary.write_text(protected, encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


class ChatGPTAuth:
    def __init__(self, *, store=None, store_factory=None, http=None, browser=None, clock=None):
        self._store = store
        self._store_factory = store_factory or ProtectedCredentialStore
        self.http = http or requests.Session()
        self.browser = browser or webbrowser.open
        self.clock = clock or time.time

    @property
    def store(self):
        # Merely opening an Off panel must not require Windows credentials.
        # Actual connection use still fails closed without protected storage.
        if self._store is None:
            self._store = self._store_factory()
        return self._store

    @staticmethod
    def _public(record: dict) -> dict:
        return {"binding": hashlib.sha256((record["client_id"] + ":" + record["subject"]).encode()).hexdigest(),
                "label": record.get("email") or "ChatGPT account"}

    def _expiry(self, tokens: dict) -> float:
        value = tokens.get("expires_in")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("ChatGPT returned invalid session expiry information.")
        return float(self.clock()) + float(value)

    def account(self) -> dict | None:
        with self.store.lock:
            data = self.store.read()
            record = data["accounts"].get(data["active"])
            return self._public(record) if record and record.get("access_token") else None

    def accounts(self) -> list[dict]:
        with self.store.lock:
            return [self._public(row) for row in self.store.read()["accounts"].values() if row.get("access_token")]

    def select_account(self, binding: str) -> None:
        with self.store.lock:
            data = self.store.read()
            if binding not in data["accounts"] or not data["accounts"][binding].get("access_token"):
                raise ValueError("Choose a connected ChatGPT registration.")
            data["active"] = binding
            self.store.write(data)

    def _json(self, method: str, url: str, **kwargs) -> dict:
        try:
            response = self.http.request(method, url, timeout=15, allow_redirects=False, **kwargs)
            if response.status_code != 200:
                raise ValueError("ChatGPT authorization was unavailable or rejected. Reconnect explicitly.")
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError("ChatGPT authorization returned an invalid response.")
            return value
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise ValueError("ChatGPT authorization could not be completed. No inference was sent.") from exc

    def _discovery(self) -> dict:
        data = self._json("GET", ISSUER + "/.well-known/openid-configuration")
        if data.get("issuer") != ISSUER:
            raise ValueError("Unexpected ChatGPT authorization issuer.")
        for name in ("jwks_uri", "revocation_endpoint"):
            parsed = urlsplit(data.get(name, ""))
            if parsed.scheme != "https" or parsed.netloc != "auth.openai.com" or parsed.fragment or parsed.username:
                raise ValueError("Unexpected ChatGPT authorization endpoint.")
        return data

    def _identity(self, token: str, client_id: str, nonce: str) -> dict:
        try:
            discovery = self._discovery()
            keys = self._json("GET", discovery["jwks_uri"])["keys"]
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not header.get("kid"):
                raise ValueError("Unsupported identity signature.")
            matches = [key for key in keys if key.get("kid") == header["kid"] and key.get("kty") == "RSA"
                       and key.get("use") in {None, "sig"} and key.get("alg") in {None, "RS256"}]
            if len(matches) != 1:
                raise ValueError("Unknown identity signature.")
            key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256").key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=client_id, issuer=ISSUER,
                                options={"require": ["exp", "iat", "sub", "nonce", "iss", "aud"]})
            if not isinstance(claims["sub"], str) or not claims["sub"] or not hmac.compare_digest(str(claims["nonce"]), nonce):
                raise ValueError("Identity nonce mismatch.")
            return dict(claims)
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
            raise ValueError("ChatGPT identity validation failed; the active account was preserved.") from exc

    def _exchange(self, callback: dict, *, state: str, nonce: str, verifier: str, redirect_uri: str,
                  previous: dict | None, host: str) -> dict:
        if not hmac.compare_digest(callback.get("state", ""), state):
            raise ValueError("ChatGPT callback state did not match.")
        if callback.get("error") or not callback.get("code"):
            raise ValueError("ChatGPT authorization was declined or incomplete.")
        client = callback.get("client_id") or (previous or {}).get("client_id")
        if not client or client == "dynamic_agent_client" or (previous and client != previous["client_id"]):
            raise ValueError("ChatGPT callback registration did not match.")
        tokens = self._json("POST", ISSUER + "/api/accounts/oauth/token", data={
            "grant_type": "authorization_code", "client_id": client, "code": callback["code"],
            "code_verifier": verifier, "redirect_uri": redirect_uri, "resource": RESOURCE})
        scopes = str(tokens.get("scope", "")).split()
        if PLAN_SCOPE not in scopes or tokens.get("token_type", "").lower() != "bearer":
            raise ValueError("This connection did not grant ChatGPT plan usage.")
        identity = self._identity(tokens.get("id_token", ""), client, nonce)
        if previous and identity["sub"] != previous["subject"]:
            raise ValueError("The returned ChatGPT account did not match the selected registration.")
        if any(not isinstance(tokens.get(key), str) or not tokens[key] for key in ("access_token", "refresh_token", "id_token")):
            raise ValueError("ChatGPT returned incomplete session credentials.")
        return {"client_id": client, "subject": identity["sub"], "email": identity.get("email", ""),
                "access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"],
                "id_token": tokens["id_token"], "scopes": scopes, "host_id": host,
                "expires_at": self._expiry(tokens)}

    def sign_in(self, cancel: Event, *, new_account: bool = False) -> dict:
        # The lock also prevents overlapping callbacks and refresh-token races across processes.
        with self.store.lock:
            data = self.store.read()
            self.store.write(data)  # Persist host ID before the first browser launch.
            previous = None if new_account else data["accounts"].get(data["active"])
            state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64)
            callback: dict[str, str] = {}

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    parsed = urlsplit(self.path)
                    try:
                        values = parse_qs(parsed.query, max_num_fields=20)
                    except ValueError:
                        values = {}
                    valid = (parsed.path == "/auth/callback" and not callback
                             and all(len(v) == 1 for v in values.values())
                             and hmac.compare_digest(values.get("state", [""])[0], state))
                    if valid:
                        callback.update({k: v[0] for k, v in values.items()})
                    self.send_response(200 if valid else 400)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(b"Return to MarketLens to complete the connection." if valid else b"Invalid callback.")

                def log_message(self, *_args):
                    pass  # Authorization codes and URLs must never enter server logs.

            class LoopbackServer(HTTPServer):
                def get_request(self):
                    connection, address = super().get_request()
                    connection.settimeout(1)
                    return connection, address

                def handle_error(self, *_args):
                    pass  # A malformed callback cannot disclose its URL through a traceback.

            with LoopbackServer(("127.0.0.1", 0), Handler) as server:
                server.timeout = 0.25
                uri = f"http://127.0.0.1:{server.server_port}/auth/callback"
                parameters = {"client_id": previous["client_id"] if previous else "dynamic_agent_client",
                              "ext_agent_host_id": data["host_id"], "response_type": "code", "redirect_uri": uri,
                              "scope": SCOPE, "resource": RESOURCE, "state": state, "nonce": nonce,
                              "code_challenge_method": "S256",
                              "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")}
                if previous:
                    if previous.get("id_token"):
                        parameters["id_token_hint"] = previous["id_token"]
                else:
                    parameters["agent_name_hint"] = "MarketLens Local"
                if cancel.is_set() or not self.browser(ISSUER + "/api/accounts/authorize?" + urlencode(parameters)):
                    raise ValueError("ChatGPT sign-in was cancelled or the browser could not open.")
                deadline = time.monotonic() + 180
                while not callback and not cancel.is_set() and time.monotonic() < deadline:
                    server.handle_request()
                if cancel.is_set() or not callback:
                    raise ValueError("ChatGPT sign-in was cancelled or timed out.")
                record = self._exchange(callback, state=state, nonce=nonce, verifier=verifier,
                                        redirect_uri=uri, previous=previous, host=data["host_id"])
                if cancel.is_set():
                    raise ValueError("ChatGPT sign-in was cancelled; the active account was preserved.")
                public = self._public(record)
                data["accounts"][public["binding"]] = record
                data["active"] = public["binding"]
                self.store.write(data)
                return public

    def access_token(self, expected_binding: str | None = None) -> str:
        with self.store.lock:
            data = self.store.read()
            record = data["accounts"].get(data["active"])
            if not record or PLAN_SCOPE not in record.get("scopes", []) or not record.get("access_token"):
                raise ValueError("Continue with ChatGPT and grant plan usage first.")
            if expected_binding is not None and self._public(record)["binding"] != expected_binding:
                raise ValueError("The active ChatGPT registration changed. Review a new request preview.")
            if record["expires_at"] <= self.clock() + 60:
                tokens = self._json("POST", ISSUER + "/api/accounts/oauth/token", data={
                    "grant_type": "refresh_token", "client_id": record["client_id"],
                    "refresh_token": record["refresh_token"], "resource": RESOURCE})
                scopes = tokens.get("scope", " ".join(record["scopes"])).split()
                if (PLAN_SCOPE not in scopes or any(not isinstance(tokens.get(key), str) or not tokens[key]
                                                   for key in ("access_token", "refresh_token"))):
                    raise ValueError("ChatGPT refresh requires a new explicit sign-in.")
                record.update(access_token=tokens["access_token"], refresh_token=tokens["refresh_token"],
                              scopes=scopes, expires_at=self._expiry(tokens))
                # A refresh response is not a new login; retain the original validated identity hint.
                self.store.write(data)
            return str(record["access_token"])

    def sign_out(self) -> bool:
        with self.store.lock:
            data = self.store.read()
            record = data["accounts"].get(data["active"])
            revoked = True
            if record and record.get("refresh_token"):
                try:
                    endpoint = self._discovery()["revocation_endpoint"]
                    response = self.http.request("POST", endpoint, data={"token": record["refresh_token"],
                        "token_type_hint": "refresh_token", "client_id": record["client_id"]}, timeout=15, allow_redirects=False)
                    revoked = response.status_code == 200
                except (ValueError, requests.RequestException):
                    revoked = False
                for key in ("access_token", "refresh_token", "id_token"):
                    record.pop(key, None)
                self.store.write(data)
            return revoked
