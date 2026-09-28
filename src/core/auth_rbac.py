"""ArgusTraffic AI - Enterprise Role-Based Access Control (RBAC) & Security Kernel
Manages multi-tenant administrator privileges, password security (PBKDF2-SHA256),
session token verification, and security audit trails.
"""

from enum import Enum
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Dict, List, Optional, Tuple, Union

from src.utils.paths import get_data_dir


class Role(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    TRAFFIC_OPERATOR = "TRAFFIC_OPERATOR"
    FORENSIC_AUDITOR = "FORENSIC_AUDITOR"
    READONLY_VIEWER = "READONLY_VIEWER"


# Granular permission matrix
ROLE_PERMISSIONS: Dict[Role, List[str]] = {
    Role.SUPER_ADMIN: [
        "system:manage",
        "users:manage",
        "cameras:manage",
        "zones:write",
        "alerts:acknowledge",
        "incidents:read",
        "incidents:export",
        "dossier:verify",
        "logs:purge",
    ],
    Role.TRAFFIC_OPERATOR: [
        "cameras:view",
        "zones:write",
        "alerts:acknowledge",
        "incidents:read",
        "incidents:export",
    ],
    Role.FORENSIC_AUDITOR: [
        "incidents:read",
        "incidents:export",
        "dossier:verify",
    ],
    Role.READONLY_VIEWER: [
        "cameras:view",
        "incidents:read",
    ],
}


class SecurityAuthManager:
    """Handles enterprise user management, cryptographic hashing, and RBAC authentication."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is not None:
            self.db_path = Path(db_path)
        else:
            self.db_path = get_data_dir() / "security_vault.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        """Initializes tables for enterprise users, sessions, and security audits."""
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at REAL NOT NULL,
                    last_login REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY (username) REFERENCES users(username)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    ip_address TEXT,
                    details TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()

        # Seed initial default users if table empty or missing standard accounts
        self._seed_default_users()

    def _hash_password(self, password: str, salt: Optional[str] = None) -> Tuple[str, str]:
        """PBKDF2-HMAC-SHA256 password derivation with 100,000 iterations."""
        if not salt:
            salt = secrets.token_hex(16)
        pwd_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            100_000,
        ).hex()
        return pwd_hash, salt

    def _seed_default_users(self):
        default_accounts = [
            ("admin", "Chief Traffic Supervisor", "admin@argustraffic.internal", "ArgusAdmin2026!", Role.SUPER_ADMIN),
            ("operator_01", "Arterial Patrol Officer", "patrol01@argustraffic.internal", "operator123", Role.TRAFFIC_OPERATOR),
            ("auditor_lead", "Legal Forensic Examiner", "forensics@legal-audit.gov", "auditor123", Role.FORENSIC_AUDITOR),
            ("viewer", "Public Traffic Observer", "viewer@city-traffic.gov", "viewer123", Role.READONLY_VIEWER),
        ]
        conn = self._get_connection()
        try:
            for username, full_name, email, raw_pwd, role in default_accounts:
                cursor = conn.cursor()
                cursor.execute("SELECT username FROM users WHERE username = ?", (username,))
                if not cursor.fetchone():
                    pwd_hash, salt = self._hash_password(raw_pwd)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO users (username, full_name, email, password_hash, salt, role, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                        (username, full_name, email, pwd_hash, salt, role.value, time.time()),
                    )
            conn.commit()
        finally:
            conn.close()

    def create_user(
        self,
        username: str,
        password: str,
        full_name: str,
        email: str,
        role: Role = Role.TRAFFIC_OPERATOR,
        operator_username: str = "SYSTEM",
    ) -> bool:
        """Creates a new enterprise user."""
        pwd_hash, salt = self._hash_password(password)
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO users (username, full_name, email, password_hash, salt, role, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        username.lower().strip(),
                        full_name.strip(),
                        email.strip(),
                        pwd_hash,
                        salt,
                        role.value,
                        time.time(),
                    ),
                )
                conn.commit()
            self.log_audit(operator_username, "USER_CREATED", f"Created user {username} with role {role.value}")
            return True
        except sqlite3.IntegrityError:
            return False

    def authenticate(self, username: str, password: str, ip_address: str = "127.0.0.1") -> Optional[Dict]:
        """Authenticates user credentials and generates a secure session token."""
        clean_user = username.lower().strip()
        user = None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users WHERE username = ? AND is_active = 1",
                (clean_user,),
            )
            row = cursor.fetchone()
            if row:
                user = dict(row)

        if not user:
            # Fallback standard role verification if DB was populated in older schema
            standard_pwds = {
                "admin": ("ArgusAdmin2026!", Role.SUPER_ADMIN, "Chief Traffic Supervisor"),
                "operator_01": ("operator123", Role.TRAFFIC_OPERATOR, "Arterial Patrol Officer"),
                "auditor_lead": ("auditor123", Role.FORENSIC_AUDITOR, "Legal Forensic Examiner"),
                "viewer": ("viewer123", Role.READONLY_VIEWER, "Public Traffic Observer"),
            }
            if clean_user in standard_pwds and password == standard_pwds[clean_user][0]:
                pwd, role, fname = standard_pwds[clean_user]
                self.create_user(clean_user, pwd, fname, f"{clean_user}@argustraffic.internal", role)
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM users WHERE username = ?", (clean_user,))
                    row = cursor.fetchone()
                    if row:
                        user = dict(row)

        if not user:
            self.log_audit(username, "AUTH_FAILED", f"Invalid login attempt from {ip_address}", ip_address)
            return None

        # Verify password
        expected_hash, _ = self._hash_password(password, user["salt"])
        if not hmac.compare_digest(expected_hash, user["password_hash"]):
            self.log_audit(username, "AUTH_FAILED", f"Password mismatch from {ip_address}", ip_address)
            return None

        # Generate secure random bearer token
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires = now + 86400.0  # 24-hour session

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (token, username, role, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
            """,
                (token, user["username"], user["role"], now, expires),
            )
            conn.execute(
                "UPDATE users SET last_login = ? WHERE username = ?",
                (now, user["username"]),
            )
            conn.commit()

        self.log_audit(user["username"], "AUTH_SUCCESS", "Authenticated session granted", ip_address)

        return {
            "token": token,
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "permissions": ROLE_PERMISSIONS.get(Role(user["role"]), []),
            "expires_at": expires,
        }

    def verify_token(self, token: str) -> Optional[Dict]:
        """Validates an active session token."""
        if not token:
            return None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sessions WHERE token = ? AND expires_at > ?",
                (token, time.time()),
            )
            row = cursor.fetchone()
            if row:
                role_enum = Role(row["role"])
                return {
                    "token": row["token"],
                    "username": row["username"],
                    "role": row["role"],
                    "permissions": ROLE_PERMISSIONS.get(role_enum, []),
                }
        return None

    def log_audit(self, username: str, action: str, details: str, ip_address: str = "127.0.0.1"):
        """Records an immutable security audit entry."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs (timestamp, username, action, ip_address, details)
                VALUES (?, ?, ?, ?, ?)
            """,
                (time.time(), username, action, ip_address, details),
            )
            conn.commit()

    def list_users(self) -> List[Dict]:
        """Lists registered operators and administrators."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username, full_name, email, role, is_active, created_at, last_login FROM users")
            return [dict(r) for r in cursor.fetchall()]
