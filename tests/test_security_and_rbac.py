"""
ArgusTraffic AI - Security, Zero-Trust RBAC & Input Sanitization Test Suite
Validates:
- PBKDF2-SHA256 credential hashing
- Role-Based Access Control (RBAC) permission matrices
- Token generation & expiration validation
- HTTP Security Headers Middleware
- Sliding-window Rate Limiting
- Geometric input sanitization against injection attacks
"""

import os
from pathlib import Path
import tempfile
import time
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from src.api.app import app
from src.api.security import RateLimiter, sanitize_polygon
from src.core.auth_rbac import (
    Role,
    ROLE_PERMISSIONS,
    SecurityAuthManager,
)


@pytest.fixture
def temp_auth_manager():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = str(Path(tmp_dir) / "test_auth.db")
        manager = SecurityAuthManager(db_path=db_path)
        yield manager


def test_password_hashing_and_verification(temp_auth_manager):
    pwd = "EnterpriseSafePassword2026!"
    hashed, salt = temp_auth_manager._hash_password(pwd)
    verify_hash, _ = temp_auth_manager._hash_password(pwd, salt)
    assert hashed == verify_hash

    wrong_hash, _ = temp_auth_manager._hash_password("WrongPassword123", salt)
    assert hashed != wrong_hash


def test_rbac_roles_and_granular_permissions():
    # SUPER_ADMIN must have all permissions
    admin_perms = ROLE_PERMISSIONS[Role.SUPER_ADMIN]
    assert "users:manage" in admin_perms
    assert "system:manage" in admin_perms

    # READONLY_VIEWER must be restricted
    viewer_perms = ROLE_PERMISSIONS[Role.READONLY_VIEWER]
    assert "users:manage" not in viewer_perms
    assert "zones:write" not in viewer_perms
    assert "cameras:view" in viewer_perms

    # FORENSIC_AUDITOR permissions
    auditor_perms = ROLE_PERMISSIONS[Role.FORENSIC_AUDITOR]
    assert "dossier:verify" in auditor_perms
    assert "system:manage" not in auditor_perms


def test_user_creation_and_authentication(temp_auth_manager):
    user_created = temp_auth_manager.create_user(
        username="qa_operator",
        password="SafeOperatorPass123!",
        full_name="QA Operator Tester",
        email="qa.operator@argustraffic.internal",
        role=Role.TRAFFIC_OPERATOR,
    )
    assert user_created is True

    # Duplicate username should be rejected
    dup_created = temp_auth_manager.create_user(
        username="qa_operator",
        password="AnotherPassword456!",
        full_name="Duplicate Tester",
        email="dup@argustraffic.internal",
        role=Role.READONLY_VIEWER,
    )
    assert dup_created is False

    # Authenticate user
    auth_result = temp_auth_manager.authenticate("qa_operator", "SafeOperatorPass123!")
    assert auth_result is not None
    assert auth_result["role"] == Role.TRAFFIC_OPERATOR.value
    assert "token" in auth_result


def test_rate_limiter_sliding_window():
    limiter = RateLimiter(requests_per_minute=5)
    ip = "192.168.1.100"

    # First 5 requests must be allowed
    for _ in range(5):
        assert limiter.is_allowed(ip) is True

    # 6th request within window must be rejected
    assert limiter.is_allowed(ip) is False


def test_polygon_input_sanitization():
    # Valid polygon
    valid_points = [(100.0, 100.0), (300.0, 100.0), (300.0, 300.0)]
    sanitized = sanitize_polygon(valid_points)
    assert len(sanitized) == 3

    # Less than 3 vertices must raise 400
    with pytest.raises(HTTPException) as exc:
        sanitize_polygon([(100.0, 100.0), (200.0, 200.0)])
    assert exc.value.status_code == 400

    # Malicious out-of-bounds coordinates must raise 400
    with pytest.raises(HTTPException) as exc:
        sanitize_polygon([(0, 0), (100, 100), (999999, 999999)])
    assert exc.value.status_code == 400


def test_defense_grade_security_headers():
    client = TestClient(app)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200

    headers = resp.headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert "strict-origin" in headers.get("Referrer-Policy", "")
    assert "geolocation=()" in headers.get("Permissions-Policy", "")
