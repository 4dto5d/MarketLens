"""OAuth boundary checks use locally signed identities and synthetic credentials."""
import json
import threading
import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from filelock import FileLock

from local_presence_miner.services.chatgpt_auth_service import (
    ISSUER,
    PLAN_SCOPE,
    ChatGPTAuth,
    ProtectedCredentialStore,
)


class MemoryStore:
    def __init__(self, tmp_path):
        self.value = {"host_id": "urn:uuid:fixed-host", "active": "", "accounts": {}}
        self.lock = FileLock(str(tmp_path / "auth.lock"))

    def read(self):
        return json.loads(json.dumps(self.value))

    def write(self, value):
        self.value = json.loads(json.dumps(value))


class Response:
    status_code = 200

    def __init__(self, payload=None, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload


class IdentityHTTP:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key())) | {"kid": "test-key"}
        self.claims = {"iss": ISSUER, "aud": "issued-client", "sub": "test-person", "nonce": "nonce",
                       "exp": time.time() + 300, "iat": time.time(), "email": "synthetic@example.invalid"}
        self.scope = PLAN_SCOPE
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("openid-configuration"):
            return Response({"issuer": ISSUER, "jwks_uri": ISSUER + "/keys", "revocation_endpoint": ISSUER + "/revoke"})
        if url.endswith("/keys"):
            return Response({"keys": [self.public]})
        if url.endswith("/revoke"):
            return Response()
        return Response({"access_token": "synthetic-access", "refresh_token": "synthetic-refresh", "token_type": "Bearer",
                         "scope": self.scope, "expires_in": 300,
                         "id_token": jwt.encode(self.claims, self.key, algorithm="RS256", headers={"kid": "test-key"})})


def exchange(auth, **changes):
    args = dict(callback={"state": "state", "code": "synthetic-code", "client_id": "issued-client"},
                state="state", nonce="nonce", verifier="pkce-verifier", redirect_uri="http://127.0.0.1:1234/auth/callback",
                previous=None, host="urn:uuid:fixed-host")
    args.update(changes)
    return auth._exchange(**args)


def test_issued_client_pkce_identity_and_scope(tmp_path):
    http = IdentityHTTP()
    auth = ChatGPTAuth(store=MemoryStore(tmp_path), http=http)
    record = exchange(auth)
    assert record["subject"] == "test-person"
    form = http.calls[0][2]["data"]
    assert form["client_id"] == "issued-client" and form["code_verifier"] == "pkce-verifier"
    assert form["redirect_uri"] == "http://127.0.0.1:1234/auth/callback"
    assert "secret" not in form and "resource" in form


@pytest.mark.parametrize("field,value", [("nonce", "wrong"), ("iss", "https://evil.invalid"),
    ("aud", "wrong-client"), ("exp", 1), ("sub", "")])
def test_invalid_identities_preserve_active_account(tmp_path, field, value):
    http, store = IdentityHTTP(), MemoryStore(tmp_path)
    http.claims[field] = value
    auth = ChatGPTAuth(store=store, http=http)
    with pytest.raises(ValueError, match="identity validation"):
        exchange(auth)
    assert store.value["accounts"] == {}


def test_signature_failure(tmp_path):
    http = IdentityHTTP()
    http.public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(
        rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key())) | {"kid": "test-key"}
    with pytest.raises(ValueError, match="identity validation"):
        exchange(ChatGPTAuth(store=MemoryStore(tmp_path), http=http))


@pytest.mark.parametrize("callback", [{"state": "wrong", "code": "secret"}, {"state": "state", "error": "access_denied"},
    {"state": "state", "code": "secret"}, {"state": "state", "code": "secret", "client_id": "dynamic_agent_client"}])
def test_callback_rejection_before_token_exchange(tmp_path, callback):
    http = IdentityHTTP()
    with pytest.raises(ValueError):
        exchange(ChatGPTAuth(store=MemoryStore(tmp_path), http=http), callback=callback)
    assert not http.calls


def test_identity_only_grant_cannot_infer(tmp_path):
    http = IdentityHTTP()
    http.scope = "openid profile email"
    with pytest.raises(ValueError, match="plan usage"):
        exchange(ChatGPTAuth(store=MemoryStore(tmp_path), http=http))


def test_returning_client_and_subject_must_match(tmp_path):
    auth = ChatGPTAuth(store=MemoryStore(tmp_path), http=IdentityHTTP())
    with pytest.raises(ValueError, match="registration"):
        exchange(auth, previous={"client_id": "another-client", "subject": "test-person"})
    with pytest.raises(ValueError, match="account did not match"):
        exchange(auth, previous={"client_id": "issued-client", "subject": "another-person"})


def test_real_loopback_flow_and_stable_host(tmp_path):
    http, store = IdentityHTTP(), MemoryStore(tmp_path)
    workers = []

    def browser(url):
        params = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert params["client_id"] == "dynamic_agent_client"
        assert params["ext_agent_host_id"] == "urn:uuid:fixed-host"
        assert params["code_challenge_method"] == "S256" and len(params["code_challenge"]) == 43
        assert urlsplit(params["redirect_uri"]).hostname == "127.0.0.1"
        http.claims["nonce"] = params["nonce"]
        target = params["redirect_uri"] + "?state=" + params["state"] + "&code=synthetic&client_id=issued-client"
        worker = threading.Thread(target=lambda: requests.get(target, timeout=5))
        workers.append(worker)
        worker.start()
        return True

    auth = ChatGPTAuth(store=store, http=http, browser=browser)
    connected = auth.sign_in(threading.Event())
    for worker in workers:
        worker.join(5)
    assert auth.account() == connected
    assert "synthetic-access" not in str(connected)
    assert store.value["host_id"] == "urn:uuid:fixed-host"


def test_refresh_rotates_and_signout_removes_credentials(tmp_path):
    http, store = IdentityHTTP(), MemoryStore(tmp_path)
    auth = ChatGPTAuth(store=store, http=http)
    record = exchange(auth)
    binding = auth._public(record)["binding"]
    record["expires_at"] = 0
    store.value.update(active=binding, accounts={binding: record})
    assert auth.access_token() == "synthetic-access"
    refresh = next(c for c in http.calls if c[2].get("data", {}).get("grant_type") == "refresh_token")
    assert refresh[2]["data"]["client_id"] == "issued-client"
    assert auth.sign_out()
    assert auth.account() is None
    assert "access_token" not in store.value["accounts"][binding]
    assert store.value["accounts"][binding]["client_id"] == "issued-client"


def test_windows_store_is_ciphertext_and_rejects_plaintext(tmp_path):
    import os
    if os.name != "nt":
        pytest.skip("Windows DPAPI integration")
    store = ProtectedCredentialStore(tmp_path)
    store.write({"host_id": "urn:uuid:fixed-host", "active": "synthetic-access", "accounts": {}})
    assert "synthetic-access" not in store.path.read_text()
    assert store.read()["active"] == "synthetic-access"
    store.path.write_text('{"access_token":"secret"}')
    with pytest.raises(ValueError, match="protected"):
        store.read()


def test_registration_binding_checked_under_token_lock(tmp_path):
    store, http = MemoryStore(tmp_path), IdentityHTTP()
    auth = ChatGPTAuth(store=store, http=http)
    first = exchange(auth)
    second = first | {"client_id": "second-client", "access_token": "second-access"}
    a, b = auth._public(first)["binding"], auth._public(second)["binding"]
    store.value.update(active=a, accounts={a: first, b: second})
    assert len(auth.accounts()) == 2
    auth.select_account(b)
    with pytest.raises(ValueError, match="registration changed"):
        auth.access_token(expected_binding=a)
    assert auth.access_token(expected_binding=b) == "second-access"
    assert "second-access" not in str(auth.accounts())


def test_revocation_failure_is_reported_and_local_tokens_removed(tmp_path):
    store, http = MemoryStore(tmp_path), IdentityHTTP()
    auth = ChatGPTAuth(store=store, http=http)
    record = exchange(auth)
    binding = auth._public(record)["binding"]
    store.value.update(active=binding, accounts={binding: record})
    previous = http.request

    def unavailable(method, url, **kwargs):
        return Response(status=503) if url.endswith('/revoke') else previous(method, url, **kwargs)

    http.request = unavailable
    assert auth.sign_out() is False
    assert auth.account() is None
    assert not any(key in store.value['accounts'][binding] for key in ['access_token', 'refresh_token', 'id_token'])


def test_default_auth_construction_does_not_open_platform_store(monkeypatch):
    import local_presence_miner.services.chatgpt_auth_service as module
    calls = []

    def unsupported_platform():
        calls.append(True)
        raise ValueError("Windows protected storage unavailable")

    monkeypatch.setattr(module, 'intelligence_data_dir', unsupported_platform)
    auth = module.ChatGPTAuth()
    assert calls == []
    with pytest.raises(ValueError, match='Windows protected storage'):
        auth.account()
    assert calls == [True]
