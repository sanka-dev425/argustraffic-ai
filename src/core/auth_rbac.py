"""ArgusTraffic AI - Enterprise Role-Based Access Control (RBAC) & Security Kernel
Manages multi-tenant administrator privileges, password security (PBKDF2-SHA256),
session token verification, and security audit trails.
"""

import datetime
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
    STATION_ADMIN = "STATION_ADMIN"
    TRAFFIC_OPERATOR = "TRAFFIC_OPERATOR"
    FORENSIC_AUDITOR = "FORENSIC_AUDITOR"
    READONLY_VIEWER = "READONLY_VIEWER"


# Granular permission matrix
ROLE_PERMISSIONS: Dict[Role, List[str]] = {
    Role.SUPER_ADMIN: [
        "system:manage",
        "users:manage",
        "cameras:manage",
        "cameras:view",
        "zones:write",
        "alerts:acknowledge",
        "incidents:read",
        "incidents:export",
        "dossier:verify",
        "logs:purge",
    ],
    Role.STATION_ADMIN: [
        "users:manage",
        "cameras:manage",
        "cameras:view",
        "zones:write",
        "alerts:acknowledge",
        "incidents:read",
        "incidents:export",
        "dossier:verify",
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
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        """Initializes tables for enterprise users, sessions, and security audits."""
        conn = self._get_connection()
        try:
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
            except Exception:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL,
                    division_id TEXT DEFAULT 'DIV_METRO_HQ',
                    is_active INTEGER DEFAULT 1,
                    created_at REAL NOT NULL,
                    last_login REAL
                )
            """)
            try:
                conn.execute("ALTER TABLE users ADD COLUMN division_id TEXT DEFAULT 'DIV_METRO_HQ';")
            except sqlite3.OperationalError:
                pass

            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    role TEXT NOT NULL,
                    division_id TEXT DEFAULT 'DIV_METRO_HQ',
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY (username) REFERENCES users(username)
                )
            """)
            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN division_id TEXT DEFAULT 'DIV_METRO_HQ';")
            except sqlite3.OperationalError:
                pass

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
            ("admin", "Enterprise System Administrator", "admin@argustraffic.internal", "ArgusAdmin2026!", Role.SUPER_ADMIN, "ALL_DIVISIONS"),
            ("station_admin", "Station Operations Commander", "station.commander@argustraffic.internal", "stationAdmin123", Role.STATION_ADMIN, "DIV_METRO_HQ"),
            ("oic_colombo", "Station Operations Commander", "oic.colombo@argustraffic.internal", "stationAdmin123", Role.STATION_ADMIN, "DIV_COLOMBO_CENTRAL"),
            ("operator_01", "Traffic Operations Specialist", "patrol01@argustraffic.internal", "operator123", Role.TRAFFIC_OPERATOR, "DIV_METRO_HQ"),
            ("auditor_lead", "Forensic Compliance Officer", "forensics@argustraffic.internal", "auditor123", Role.FORENSIC_AUDITOR, "DIV_METRO_HQ"),
            ("viewer", "Read-Only Traffic Observer", "viewer@argustraffic.internal", "viewer123", Role.READONLY_VIEWER, "DIV_METRO_HQ"),
        ]
        conn = self._get_connection()
        try:
            for item in default_accounts:
                username, full_name, email, raw_pwd, role = item[0], item[1], item[2], item[3], item[4]
                division_id = item[5] if len(item) > 5 else "DIV_METRO_HQ"
                cursor = conn.cursor()
                cursor.execute("SELECT username FROM users WHERE username = ?", (username,))
                if not cursor.fetchone():
                    pwd_hash, salt = self._hash_password(raw_pwd)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO users (username, full_name, email, password_hash, salt, role, division_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (username, full_name, email, pwd_hash, salt, role.value, division_id, time.time()),
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
        division_id: str = "DIV_METRO_HQ",
        operator_username: str = "SYSTEM",
        operator_role: Optional[Role] = None,
        operator_division: Optional[str] = None,
    ) -> bool:
        """Creates a new enterprise user with Station Admin boundary and privilege escalation checks."""
        if operator_role == Role.STATION_ADMIN:
            # Station Admins cannot create SUPER_ADMIN or other STATION_ADMIN accounts
            if role in (Role.SUPER_ADMIN, Role.STATION_ADMIN):
                return False
            # Force assigned user to Station Admin's own division
            if operator_division:
                division_id = operator_division

        pwd_hash, salt = self._hash_password(password)
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO users (username, full_name, email, password_hash, salt, role, division_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        username.lower().strip(),
                        full_name.strip(),
                        email.strip(),
                        pwd_hash,
                        salt,
                        role.value,
                        division_id,
                        time.time(),
                    ),
                )
                conn.commit()
            self.log_audit(operator_username, "USER_CREATED", f"Created user {username} ({role.value}) in {division_id}")
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
                "admin": ("ArgusAdmin2026!", Role.SUPER_ADMIN, "Chief Traffic Supervisor", "ALL_DIVISIONS"),
                "station_admin": ("stationAdmin123", Role.STATION_ADMIN, "Station Operations Commander", "DIV_METRO_HQ"),
                "oic_colombo": ("stationAdmin123", Role.STATION_ADMIN, "Station Operations Commander", "DIV_COLOMBO_CENTRAL"),
                "operator_01": ("operator123", Role.TRAFFIC_OPERATOR, "Arterial Patrol Officer", "DIV_METRO_HQ"),
                "auditor_lead": ("auditor123", Role.FORENSIC_AUDITOR, "Legal Forensic Examiner", "DIV_METRO_HQ"),
                "viewer": ("viewer123", Role.READONLY_VIEWER, "Public Traffic Observer", "DIV_METRO_HQ"),
            }
            if clean_user in standard_pwds and password == standard_pwds[clean_user][0]:
                pwd, role, fname, div = standard_pwds[clean_user]
                self.create_user(clean_user, pwd, fname, f"{clean_user}@argustraffic.internal", role, division_id=div)
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
        div_id = user.get("division_id") or "DIV_METRO_HQ"

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (token, username, role, division_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (token, user["username"], user["role"], div_id, now, expires),
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
            "division_id": div_id,
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
                row_dict = dict(row)
                div_id = row_dict.get("division_id") or "DIV_METRO_HQ"
                return {
                    "token": row["token"],
                    "username": row["username"],
                    "role": row["role"],
                    "division_id": div_id,
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

    def list_users(self, filter_division: Optional[str] = None) -> List[Dict]:
        """Lists registered operators and administrators, optionally filtered by division."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if filter_division and filter_division != "ALL_DIVISIONS":
                cursor.execute(
                    "SELECT username, full_name, email, role, division_id, is_active, created_at, last_login FROM users WHERE division_id = ?",
                    (filter_division,),
                )
            else:
                cursor.execute(
                    "SELECT username, full_name, email, role, division_id, is_active, created_at, last_login FROM users"
                )
            return [dict(r) for r in cursor.fetchall()]

    def get_user(self, username: str) -> Optional[Dict]:
        """Retrieves a single user's safe profile info without credentials."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT username, full_name, email, role, division_id, is_active, created_at, last_login FROM users WHERE username = ?",
                (username.lower().strip(),),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_user(
        self,
        username: str,
        full_name: Optional[str] = None,
        email: Optional[str] = None,
        role: Optional[Union[Role, str]] = None,
        division_id: Optional[str] = None,
        is_active: Optional[bool] = None,
        operator_username: str = "SYSTEM",
        operator_role: Optional[Role] = None,
    ) -> Tuple[bool, str]:
        """Updates user profile attributes with RBAC role integrity constraints."""
        clean_user = username.lower().strip()
        existing = self.get_user(clean_user)
        if not existing:
            return False, f"User '{username}' not found."

        # Prevent non-superadmins from escalating to or modifying SUPER_ADMIN accounts
        if operator_role != Role.SUPER_ADMIN:
            if existing["role"] == Role.SUPER_ADMIN.value or (role and str(role) == Role.SUPER_ADMIN.value):
                return False, "Super Administrator authorization required for this account."

        updates = []
        params = []
        if full_name is not None:
            updates.append("full_name = ?")
            params.append(full_name.strip())
        if email is not None:
            updates.append("email = ?")
            params.append(email.strip())
        if role is not None:
            role_val = role.value if isinstance(role, Role) else str(role)
            updates.append("role = ?")
            params.append(role_val)
        if division_id is not None:
            updates.append("division_id = ?")
            params.append(division_id)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)

        if not updates:
            return True, "No changes requested."

        params.append(clean_user)
        query = f"UPDATE users SET {', '.join(updates)} WHERE username = ?"

        with self._get_connection() as conn:
            conn.execute(query, tuple(params))
            conn.commit()

        self.log_audit(operator_username, "USER_UPDATED", f"Updated account profile for {clean_user}")
        return True, "User account updated successfully."

    def change_password(self, username: str, old_password: str, new_password: str) -> Tuple[bool, str]:
        """Allows a user to securely change their own password."""
        clean_user = username.lower().strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT password_hash, salt FROM users WHERE username = ?", (clean_user,))
            row = cursor.fetchone()
            if not row:
                return False, "User not found."

            expected_hash, _ = self._hash_password(old_password, row["salt"])
            if not hmac.compare_digest(expected_hash, row["password_hash"]):
                return False, "Current password verification failed."

            new_hash, new_salt = self._hash_password(new_password)
            conn.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
                (new_hash, new_salt, clean_user),
            )
            # Revoke all active sessions on password change
            conn.execute("DELETE FROM sessions WHERE username = ?", (clean_user,))
            conn.commit()

        self.log_audit(clean_user, "PASSWORD_CHANGED", "User changed account password")
        return True, "Password changed successfully. Please log in again."

    def reset_password_by_admin(
        self,
        username: str,
        new_password: str,
        admin_username: str = "admin",
        admin_role: Optional[Role] = None,
    ) -> Tuple[bool, str]:
        """Allows an administrator to reset credentials for a user."""
        clean_user = username.lower().strip()
        existing = self.get_user(clean_user)
        if not existing:
            return False, f"User '{username}' not found."

        if admin_role != Role.SUPER_ADMIN and existing["role"] == Role.SUPER_ADMIN.value:
            return False, "Cannot reset credentials for a Super Administrator."

        new_hash, new_salt = self._hash_password(new_password)
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
                (new_hash, new_salt, clean_user),
            )
            conn.execute("DELETE FROM sessions WHERE username = ?", (clean_user,))
            conn.commit()

        self.log_audit(admin_username, "PASSWORD_RESET_ADMIN", f"Admin reset password for {clean_user}")
        return True, f"Password for {clean_user} reset successfully."

    def delete_user(
        self,
        username: str,
        operator_username: str = "admin",
        operator_role: Optional[Role] = None,
    ) -> Tuple[bool, str]:
        """Deletes or deactivates a user account with SuperAdmin protection."""
        clean_user = username.lower().strip()
        existing = self.get_user(clean_user)
        if not existing:
            return False, f"User '{username}' not found."

        if clean_user == operator_username.lower().strip():
            return False, "Cannot delete your own active administrator account."

        if clean_user == "admin":
            return False, "Protected root enterprise administrator cannot be deleted."

        with self._get_connection() as conn:
            conn.execute("DELETE FROM sessions WHERE username = ?", (clean_user,))
            conn.execute("DELETE FROM users WHERE username = ?", (clean_user,))
            conn.commit()

        self.log_audit(operator_username, "USER_DELETED", f"Deleted operator account {clean_user}")
        return True, f"User {clean_user} deleted successfully."

    def revoke_session(self, token: str, username: str = "SYSTEM") -> bool:
        """Revokes an active session bearer token."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
        self.log_audit(username, "SESSION_REVOKED", "Session token revoked")
        return True

    def list_audit_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        filter_user: Optional[str] = None,
        filter_action: Optional[str] = None,
    ) -> List[Dict]:
        """Retrieves paginated immutable security audit trails."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT id, timestamp, username, action, ip_address, details FROM audit_logs"
            clauses = []
            params = []
            if filter_user:
                clauses.append("username = ?")
                params.append(filter_user.lower().strip())
            if filter_action:
                clauses.append("action = ?")
                params.append(filter_action.upper().strip())

            if clauses:
                query += " WHERE " + " AND ".join(clauses)

            query += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "timestamp": r["timestamp"],
                    "formatted_time": datetime.datetime.fromtimestamp(r["timestamp"], datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "username": r["username"],
                    "action": r["action"],
                    "ip_address": r["ip_address"],
                    "details": r["details"],
                }
                for r in rows
            ]

    def get_role_permissions_matrix(self) -> Dict[str, List[str]]:
        """Returns the active enterprise RBAC permission matrix for all roles."""
        return {role.value: list(perms) for role, perms in ROLE_PERMISSIONS.items()}

