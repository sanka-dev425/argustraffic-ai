"""
ArgusTraffic AI - Enterprise Multi-Sector & Station Mesh Aggregator
Provides dynamic, customizable multi-tenant division/sector management with
persistent SQLite storage and real-time mesh aggregation.
Enforces zero-trust boundary isolation while granting National HQ supervisory overview.
"""

import datetime
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from src.utils.paths import get_data_dir

logger = logging.getLogger("argustraffic.mesh")


class PoliceDivisionNode:
    """Represents an operational sector / division operating an edge ArgusTraffic node."""

    def __init__(
        self,
        division_id: str,
        division_name: str,
        jurisdiction: str,
        ip_address: str,
        is_custom: bool = False,
    ):
        self.division_id = division_id
        self.division_name = division_name
        self.jurisdiction = jurisdiction
        self.ip_address = ip_address
        self.is_custom = is_custom
        self.is_online = True
        self.last_heartbeat = time.time()
        self.camera_count = 0
        self.active_incidents_count = 0
        self.total_traffic_flow_vph = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "division_id": self.division_id,
            "division_name": self.division_name,
            "jurisdiction": self.jurisdiction,
            "ip_address": self.ip_address,
            "is_custom": self.is_custom,
            "is_online": self.is_online,
            "last_heartbeat": self.last_heartbeat,
            "camera_count": self.camera_count,
            "active_incidents_count": self.active_incidents_count,
            "total_traffic_flow_vph": self.total_traffic_flow_vph,
        }


class NationalStationMeshAggregator:
    """
    Central Command Broker aggregating multi-station edge nodes across jurisdictions.
    Supports dynamic runtime creation, modification, and deletion of custom sectors.
    """

    def __init__(self, local_division_id: str = "DIV_COLOMBO_CENTRAL", db_path: Optional[Path] = None):
        self.local_division_id = local_division_id
        self.db_path = db_path or (get_data_dir() / "station_mesh.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.divisions: Dict[str, PoliceDivisionNode] = {}
        self.lock = threading.Lock()
        self._init_db()
        self._load_divisions()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        """Initializes tables for persistent sectors/divisions."""
        conn = self._get_connection()
        try:
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
            except Exception:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS divisions (
                    division_id TEXT PRIMARY KEY,
                    division_name TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    is_custom INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_updated REAL NOT NULL
                )
            """)
            conn.commit()
            self._seed_default_divisions(conn)
        finally:
            conn.close()

    def _seed_default_divisions(self, conn: sqlite3.Connection) -> None:
        """Seeds standard enterprise command sectors if empty."""
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM divisions")
        if cursor.fetchone()[0] == 0:
            now = time.time()
            defaults = [
                ("DIV_COLOMBO_CENTRAL", "Metropolitan Command HQ", "Capital Metropolitan Sector", "10.0.1.10", 0),
                ("DIV_KANDY", "North District Command", "Northern Expressway Sector", "10.0.2.10", 0),
                ("DIV_GALLE", "South District Command", "Southern Coastal Sector", "10.0.3.10", 0),
                ("DIV_JAFFNA", "Eastern District Command", "Eastern Intermodal Sector", "10.0.4.10", 0),
            ]
            for row in defaults:
                conn.execute(
                    """
                    INSERT INTO divisions (division_id, division_name, jurisdiction, ip_address, is_custom, created_at, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (row[0], row[1], row[2], row[3], row[4], now, now),
                )
            conn.commit()

    def _load_divisions(self) -> None:
        """Loads all divisions from SQLite into active in-memory cache."""
        with self.lock:
            self.divisions.clear()
            conn = self._get_connection()
            try:
                cursor = conn.execute("SELECT * FROM divisions ORDER BY created_at ASC")
                for row in cursor.fetchall():
                    node = PoliceDivisionNode(
                        division_id=row["division_id"],
                        division_name=row["division_name"],
                        jurisdiction=row["jurisdiction"],
                        ip_address=row["ip_address"],
                        is_custom=bool(row["is_custom"]),
                    )
                    if node.division_id == "DIV_COLOMBO_CENTRAL":
                        node.camera_count = 14
                        node.total_traffic_flow_vph = 2450
                    elif node.division_id == "DIV_KANDY":
                        node.camera_count = 8
                        node.total_traffic_flow_vph = 1120
                    elif node.division_id == "DIV_GALLE":
                        node.camera_count = 6
                        node.total_traffic_flow_vph = 890
                    elif node.division_id == "DIV_JAFFNA":
                        node.camera_count = 5
                        node.total_traffic_flow_vph = 640

                    self.divisions[node.division_id] = node
            finally:
                conn.close()

    def list_divisions(self) -> List[Dict[str, Any]]:
        """Returns all configured sectors/divisions."""
        with self.lock:
            now = time.time()
            res = []
            for d in self.divisions.values():
                d.is_online = (now - d.last_heartbeat) < 60.0 or not d.is_custom
                res.append(d.to_dict())
            return res

    def get_division(self, division_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single division by ID."""
        with self.lock:
            d = self.divisions.get(division_id)
            return d.to_dict() if d else None

    def add_division(
        self,
        division_id: str,
        division_name: str,
        jurisdiction: str,
        ip_address: str = "127.0.0.1",
        is_custom: bool = True,
    ) -> Tuple[bool, str]:
        """Dynamically registers a new custom sector/division."""
        clean_id = division_id.strip().upper()
        if not clean_id.startswith("DIV_"):
            clean_id = f"DIV_{clean_id}"

        now = time.time()
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO divisions (division_id, division_name, jurisdiction, ip_address, is_custom, created_at, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (clean_id, division_name.strip(), jurisdiction.strip(), ip_address.strip(), 1 if is_custom else 0, now, now),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return False, f"Division ID '{clean_id}' already exists."
        finally:
            conn.close()

        with self.lock:
            node = PoliceDivisionNode(
                division_id=clean_id,
                division_name=division_name.strip(),
                jurisdiction=jurisdiction.strip(),
                ip_address=ip_address.strip(),
                is_custom=is_custom,
            )
            self.divisions[clean_id] = node

        logger.info(f"Dynamically created division: {clean_id} ({division_name})")
        return True, "Division created successfully."

    def update_division(
        self,
        division_id: str,
        updates: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Updates an existing division name, jurisdiction, or IP."""
        clean_id = division_id.strip().upper()
        with self.lock:
            if clean_id not in self.divisions:
                return False, f"Division '{clean_id}' not found."

        allowed = {"division_name", "jurisdiction", "ip_address"}
        set_clauses = []
        params = []
        for k, v in updates.items():
            if k in allowed and v is not None:
                set_clauses.append(f"{k} = ?")
                params.append(str(v).strip())

        if not set_clauses:
            return False, "No valid update fields provided."

        set_clauses.append("last_updated = ?")
        params.append(time.time())
        params.append(clean_id)

        conn = self._get_connection()
        try:
            conn.execute(
                f"UPDATE divisions SET {', '.join(set_clauses)} WHERE division_id = ?",
                params,
            )
            conn.commit()
        finally:
            conn.close()

        with self.lock:
            node = self.divisions[clean_id]
            if "division_name" in updates and updates["division_name"]:
                node.division_name = str(updates["division_name"]).strip()
            if "jurisdiction" in updates and updates["jurisdiction"]:
                node.jurisdiction = str(updates["jurisdiction"]).strip()
            if "ip_address" in updates and updates["ip_address"]:
                node.ip_address = str(updates["ip_address"]).strip()

        logger.info(f"Updated division: {clean_id}")
        return True, "Division updated successfully."

    def delete_division(self, division_id: str) -> Tuple[bool, str]:
        """Deletes a custom division."""
        clean_id = division_id.strip().upper()
        if clean_id == "DIV_COLOMBO_CENTRAL":
            return False, "Cannot delete primary root division."

        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM divisions WHERE division_id = ?", (clean_id,))
            conn.commit()
        finally:
            conn.close()

        with self.lock:
            self.divisions.pop(clean_id, None)

        logger.info(f"Deleted division: {clean_id}")
        return True, "Division removed successfully."

    def record_heartbeat(self, division_id: str, payload: Dict[str, Any]) -> bool:
        """Processes an incoming heartbeat from a regional division edge node."""
        with self.lock:
            div = self.divisions.get(division_id)
            if not div:
                div = PoliceDivisionNode(
                    division_id=division_id,
                    division_name=payload.get("division_name", f"Division {division_id}"),
                    jurisdiction=payload.get("jurisdiction", "Regional"),
                    ip_address=payload.get("ip_address", "127.0.0.1"),
                )
                self.divisions[division_id] = div

            div.last_heartbeat = time.time()
            div.is_online = True
            div.camera_count = payload.get("camera_count", div.camera_count)
            div.active_incidents_count = payload.get("active_incidents", div.active_incidents_count)
            div.total_traffic_flow_vph = payload.get("traffic_flow_vph", div.total_traffic_flow_vph)
            return True

    def get_national_overview(self) -> Dict[str, Any]:
        """Compiles aggregated nationwide traffic intelligence for Police Headquarters (NOC)."""
        with self.lock:
            now = time.time()
            total_cams = sum(d.camera_count for d in self.divisions.values())
            total_active_incidents = sum(d.active_incidents_count for d in self.divisions.values())
            total_vph = sum(d.total_traffic_flow_vph for d in self.divisions.values())

            division_list = []
            for d in self.divisions.values():
                d.is_online = (now - d.last_heartbeat) < 60.0 or not d.is_custom
                division_list.append(d.to_dict())

            return {
                "mesh_status": "ONLINE",
                "total_connected_divisions": len(division_list),
                "total_monitored_cameras": total_cams,
                "active_national_incidents": total_active_incidents,
                "aggregate_traffic_flow_vph": total_vph,
                "local_station_id": self.local_division_id,
                "divisions": division_list,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }

    def filter_for_user_role(self, raw_data: List[Dict[str, Any]], user_role: str, user_division: str) -> List[Dict[str, Any]]:
        """
        Enforces Zero-Trust division isolation:
        - SUPER_ADMIN / NATIONAL_HQ: sees all data nationwide.
        - DIVISION_CHIEF / OPERATOR: sees only data matching their assigned division.
        """
        if user_role in ("SUPER_ADMIN", "NATIONAL_HQ", "AUDITOR"):
            return raw_data

        return [item for item in raw_data if item.get("division_id") == user_division]
