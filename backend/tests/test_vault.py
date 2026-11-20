import pytest
import urllib.request
import json
import uuid
from app.core.security import encrypt_secret, decrypt_secret, mask_secret

def http_request(url, method="GET", data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            content = response.read().decode("utf-8")
            return response.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(err_body)
        except Exception:
            return e.code, {"detail": err_body}

def test_fernet_crypto_primitives():
    secret = "sk-proj-supersecretkey1234567890abcdef"
    encrypted = encrypt_secret(secret)
    assert encrypted != secret
    decrypted = decrypt_secret(encrypted)
    assert decrypted == secret

    masked = mask_secret(secret)
    assert masked.startswith("sk-p")
    assert masked.endswith("cdef")
    assert "supersecretkey" not in masked

def test_api_key_vault_endpoints(server):
    email = f"vault_user_{uuid.uuid4().hex[:8]}@example.com"
    _, res = http_request(f"{server}/api/v1/auth/register", method="POST", data={
        "email": email,
        "password": "Password123!"
    })
    token = res["access_token"]

    raw_key = "sk-proj-testkey9876543210zyxwvutsrq"

    # 1. Store API key
    status, res_key = http_request(
        f"{server}/api/v1/auth/secrets",
        method="POST",
        data={"provider": "openai", "api_key": raw_key},
        token=token
    )
    assert status == 200
    assert res_key["provider"] == "openai"
    assert "masked_key" in res_key
    assert raw_key not in res_key["masked_key"]
    assert res_key["masked_key"].startswith("sk-p")

    # 2. List API keys
    status_list, keys = http_request(f"{server}/api/v1/auth/secrets", method="GET", token=token)
    assert status_list == 200
    assert len(keys) == 1
    assert keys[0]["provider"] == "openai"
    assert "••••" in keys[0]["masked_key"]

    # 3. Delete API key
    status_del, _ = http_request(f"{server}/api/v1/auth/secrets/openai", method="DELETE", token=token)
    assert status_del == 204

    # 4. List again is empty
    _, keys_after = http_request(f"{server}/api/v1/auth/secrets", method="GET", token=token)
    assert len(keys_after) == 0
