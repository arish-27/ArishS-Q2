import pytest
import urllib.request
import json
import uuid

def http_request(url, method="GET", data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(err_body)
        except Exception:
            return e.code, {"detail": err_body}

def test_auth_registration_and_login(server):
    email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    password = "SecurePassword123!"

    # 1. Register
    status, res = http_request(f"{server}/api/v1/auth/register", method="POST", data={
        "email": email,
        "password": password,
        "full_name": "Test User"
    })
    assert status == 201
    assert "access_token" in res
    assert res["user"]["email"] == email
    token = res["access_token"]

    # 2. Duplicate registration fails
    status_dup, res_dup = http_request(f"{server}/api/v1/auth/register", method="POST", data={
        "email": email,
        "password": password
    })
    assert status_dup == 400
    assert "already exists" in res_dup["detail"]

    # 3. Login with correct credentials
    status_login, res_login = http_request(f"{server}/api/v1/auth/login", method="POST", data={
        "email": email,
        "password": password
    })
    assert status_login == 200
    assert "access_token" in res_login

    # 4. Login with incorrect password fails
    status_fail, res_fail = http_request(f"{server}/api/v1/auth/login", method="POST", data={
        "email": email,
        "password": "WrongPassword!"
    })
    assert status_fail == 401

    # 5. Fetch /auth/me with token
    status_me, res_me = http_request(f"{server}/api/v1/auth/me", method="GET", token=token)
    assert status_me == 200
    assert res_me["email"] == email

    # 6. Fetch /auth/me without token fails
    status_no_auth, _ = http_request(f"{server}/api/v1/auth/me", method="GET")
    assert status_no_auth == 401
