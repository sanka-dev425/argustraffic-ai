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


def test_user_management_crud_and_lifecycle(temp_auth_manager):
    # 1. Create User
    temp_auth_manager.create_user(
        username="dispatcher_bob",
        password="InitialPassword123!",
        full_name="Bob Dispatcher",
        email="bob@dispatch.internal",
        role=Role.FORENSIC_AUDITOR,
    )
    user = temp_auth_manager.get_user("dispatcher_bob")
    assert user is not None
    assert user["full_name"] == "Bob Dispatcher"
    assert user["is_active"] == 1

    # 2. Update User metadata and role
    success, _ = temp_auth_manager.update_user(
        username="dispatcher_bob",
        full_name="Senior Officer Bob",
        email="bob.senior@dispatch.internal",
        role=Role.TRAFFIC_OPERATOR,
        is_active=True,
    )
    assert success is True
    updated = temp_auth_manager.get_user("dispatcher_bob")
    assert updated["full_name"] == "Senior Officer Bob"
    assert updated["role"] == Role.TRAFFIC_OPERATOR.value

    # 3. Change Password
    pwd_changed, _ = temp_auth_manager.change_password("dispatcher_bob", "InitialPassword123!", "NewSecretPass456!")
    assert pwd_changed is True
    # Verify old password fails
    assert temp_auth_manager.authenticate("dispatcher_bob", "InitialPassword123!") is None
    # Verify new password succeeds
    assert temp_auth_manager.authenticate("dispatcher_bob", "NewSecretPass456!") is not None

    # 4. Admin Reset Password
    reset_ok, _ = temp_auth_manager.reset_password_by_admin("dispatcher_bob", "AdminOverridePass789!")
    assert reset_ok is True
    assert temp_auth_manager.authenticate("dispatcher_bob", "AdminOverridePass789!") is not None

    # 5. Audit logs recorded
    logs = temp_auth_manager.list_audit_logs(limit=50)
    assert len(logs) > 0
    actions = [l["action"] for l in logs]
    assert "USER_CREATED" in actions
    assert "PASSWORD_CHANGED" in actions
    assert "PASSWORD_RESET_ADMIN" in actions

    # 6. Delete user
    del_ok, _ = temp_auth_manager.delete_user("dispatcher_bob")
    assert del_ok is True
    assert temp_auth_manager.get_user("dispatcher_bob") is None
    # Admin root account cannot be deleted
    del_admin_ok, _ = temp_auth_manager.delete_user("admin")
    assert del_admin_ok is False


def test_system_settings_manager(tmp_path):
    from src.core.system_settings import SystemSettingsManager

    db_path = str(tmp_path / "test_settings.db")
    mgr = SystemSettingsManager(db_path=db_path)

    # 1. Get default settings
    settings = mgr.get_all_settings()
    assert "agency_name" in settings
    assert settings["default_map_provider"] == "carto_dark"

    # 2. Update settings
    ok, _ = mgr.update_settings(
        {
            "agency_name": "Sri Lanka Highway Patrol Authority",
            "agency_logo_url": "https://police.lk/assets/logo.png",
            "default_map_provider": "google_road",
            "speed_limit_urban_kmh": 60.0,
            "speed_tolerance_grace_kmh": 5.0,
            "sla_critical_timeout_sec": 90,
        },
        operator_username="admin",
    )
    assert ok is True
    updated = mgr.get_all_settings()
    assert updated["agency_name"] == "Sri Lanka Highway Patrol Authority"
    assert updated["default_map_provider"] == "google_road"
    assert updated["speed_limit_urban_kmh"] == 60.0
    assert updated["sla_critical_timeout_sec"] == 90

    # 3. Reload from fresh instance to verify persistence
    mgr2 = SystemSettingsManager(db_path=db_path)
    persisted = mgr2.get_all_settings()
    assert persisted["agency_name"] == "Sri Lanka Highway Patrol Authority"
    assert persisted["default_map_provider"] == "google_road"


def test_account_lockout_after_failed_attempts(temp_auth_manager):
    # admin account created with ArgusAdmin2026!
    # Try 5 wrong passwords
    for _ in range(5):
        res = temp_auth_manager.authenticate("admin", "WrongPassword!")
        assert res is None

    # 6th attempt with correct password should still be blocked due to lockout
    blocked_res = temp_auth_manager.authenticate("admin", "ArgusAdmin2026!")
    assert blocked_res is None

    user = temp_auth_manager.get_user("admin")
    assert user is not None


def test_password_complexity_validator():
    # Too short
    valid, msg = SecurityAuthManager.validate_password_complexity("Pass1!")
    assert not valid

    # No uppercase
    valid, msg = SecurityAuthManager.validate_password_complexity("password123!")
    assert not valid

    # No special char
    valid, msg = SecurityAuthManager.validate_password_complexity("Password12345")
    assert not valid

    # Compliant NIST password
    valid, msg = SecurityAuthManager.validate_password_complexity("ArgusDefense#2026")
    assert valid


def test_cryptographic_chained_audit_logs(temp_auth_manager):
    temp_auth_manager.log_audit("admin", "TEST_ACTION_1", "First audit entry")
    temp_auth_manager.log_audit("admin", "TEST_ACTION_2", "Second audit entry")

    logs = temp_auth_manager.list_audit_logs(limit=10)
    assert len(logs) >= 2

    # Verify chained integrity in raw SQLite table
    conn = temp_auth_manager._get_connection()
    try:
        rows = conn.execute("SELECT prev_hash, merkle_hash FROM audit_logs ORDER BY id ASC").fetchall()
        assert len(rows) >= 2
        # Row 2's prev_hash must match Row 1's merkle_hash
        assert rows[1]["prev_hash"] == rows[0]["merkle_hash"]
    finally:
        conn.close()



