"""
ArgusTraffic AI - Enterprise Incident Audit Database
Thread-safe SQLite persistent store for forensic event investigation,
historical reporting, and compliance audits.
"""

from dataclasses import asdict
import json
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from src.utils.paths import get_data_dir

logger = logging.getLogger("argustraffic.db")


class IncidentDatabase:
    """Persistent SQLite incident store with indices and query filters."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (get_data_dir() / "incidents.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
            except Exception:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    alert_id TEXT PRIMARY KEY,
                    incident_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    formatted_time TEXT NOT NULL,
                    description TEXT NOT NULL,
                    location_x REAL,
                    location_y REAL,
                    involved_tracks TEXT,
                    zone_id TEXT,
                    metadata_json TEXT,
                    snapshot_path TEXT,
                    license_plate TEXT,
                    speed_kmh REAL
                )
            """)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(incidents)")
            cols = [row["name"] for row in cursor.fetchall()]
            if "license_plate" not in cols:
                conn.execute("ALTER TABLE incidents ADD COLUMN license_plate TEXT")
            if "speed_kmh" not in cols:
                conn.execute("ALTER TABLE incidents ADD COLUMN speed_kmh REAL")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON incidents(timestamp DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_severity ON incidents(severity)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_type ON incidents(incident_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_plate ON incidents(license_plate)")
            conn.commit()
        finally:
            conn.close()
        logger.info(f"Incident database initialized at: {self.db_path}")

    def save_incident(self, alert_dict: Dict[str, Any], snapshot_path: Optional[str] = None) -> None:
        """Inserts an incident into persistent audit log."""
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO incidents (
                    alert_id, incident_type, severity, timestamp, formatted_time,
                    description, location_x, location_y, involved_tracks, zone_id,
                    metadata_json, snapshot_path, license_plate, speed_kmh
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_dict["alert_id"],
                    alert_dict["incident_type"],
                    alert_dict["severity"],
                    alert_dict["timestamp"],
                    alert_dict.get("formatted_time", ""),
                    alert_dict["description"],
                    float(alert_dict.get("location", [0, 0])[0]),
                    float(alert_dict.get("location", [0, 0])[1]),
                    json.dumps(alert_dict.get("involved_track_ids", [])),
                    alert_dict.get("zone_id"),
                    json.dumps(alert_dict.get("metadata", {})),
                    snapshot_path or "",
                    alert_dict.get("license_plate"),
                    alert_dict.get("speed_kmh"),
                ),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to persist incident {alert_dict.get('alert_id')}: {e}")
        finally:
            conn.close()

    def query_incidents(
        self,
        severity: Optional[str] = None,
        incident_type: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        license_plate: Optional[str] = None,
        zone_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Queries historical incidents with multi-attribute filtering."""
        query = "SELECT * FROM incidents WHERE 1=1"
        params: List[Any] = []

        if severity:
            query += " AND severity = ?"
            params.append(severity.upper())
        if incident_type:
            query += " AND incident_type = ?"
            params.append(incident_type.upper())
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)
        if license_plate:
            query += " AND license_plate = ?"
            params.append(license_plate.strip().upper())
        if zone_id:
            query += " AND zone_id = ?"
            params.append(zone_id)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        results = []
        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            for row in cursor.fetchall():
                results.append({
                    "alert_id": row["alert_id"],
                    "incident_type": row["incident_type"],
                    "severity": row["severity"],
                    "timestamp": row["timestamp"],
                    "formatted_time": row["formatted_time"],
                    "description": row["description"],
                    "location": [row["location_x"], row["location_y"]],
                    "involved_track_ids": json.loads(row["involved_tracks"] or "[]"),
                    "zone_id": row["zone_id"],
                    "metadata": json.loads(row["metadata_json"] or "{}"),
                    "snapshot_path": row["snapshot_path"],
                    "license_plate": row["license_plate"] if "license_plate" in row.keys() else None,
                    "speed_kmh": row["speed_kmh"] if "speed_kmh" in row.keys() else None,
                })
        finally:
            conn.close()
        return results

    def get_stats(self) -> Dict[str, Any]:
        """Calculates historical incident aggregates."""
        conn = self._get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
            critical = conn.execute("SELECT COUNT(*) FROM incidents WHERE severity = 'CRITICAL'").fetchone()[0]
            warning = conn.execute("SELECT COUNT(*) FROM incidents WHERE severity = 'WARNING'").fetchone()[0]
            return {
                "total_recorded": total,
                "critical_count": critical,
                "warning_count": warning,
            }
        finally:
            conn.close()

    def get_analytics_summary(self) -> Dict[str, Any]:
        """Calculates multi-dimensional statistical summaries across incident history."""
        conn = self._get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
            severity_rows = conn.execute(
                "SELECT severity, COUNT(*) as cnt FROM incidents GROUP BY severity"
            ).fetchall()
            severity_breakdown = {row["severity"]: row["cnt"] for row in severity_rows}

            type_rows = conn.execute(
                "SELECT incident_type, COUNT(*) as cnt FROM incidents GROUP BY incident_type ORDER BY cnt DESC LIMIT 10"
            ).fetchall()
            type_breakdown = {row["incident_type"]: row["cnt"] for row in type_rows}

            speed_stats = conn.execute(
                "SELECT AVG(speed_kmh) as avg_speed, MAX(speed_kmh) as max_speed FROM incidents WHERE speed_kmh IS NOT NULL AND speed_kmh > 0"
            ).fetchone()

            avg_spd = round(float(speed_stats["avg_speed"] or 0.0), 1)
            max_spd = round(float(speed_stats["max_speed"] or 0.0), 1)

            speeds = [
                row[0]
                for row in conn.execute(
                    "SELECT speed_kmh FROM incidents WHERE speed_kmh IS NOT NULL AND speed_kmh > 0 ORDER BY speed_kmh ASC"
                ).fetchall()
            ]
            p85_speed = round(speeds[int(len(speeds) * 0.85)], 1) if speeds else 0.0

            return {
                "total_events": total,
                "severity_distribution": severity_breakdown,
                "type_distribution": type_breakdown,
                "speed_metrics": {
                    "average_kmh": avg_spd,
                    "max_observed_kmh": max_spd,
                    "p85_percentile_kmh": p85_speed,
                },
            }
        finally:
            conn.close()

    def export_geojson(self, limit: int = 500) -> Dict[str, Any]:
        """Exports spatial incident points as an RFC 7946 GeoJSON FeatureCollection."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM incidents WHERE location_x IS NOT NULL AND location_y IS NOT NULL ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            features = []
            for row in cursor.fetchall():
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(row["location_x"]), float(row["location_y"])],
                    },
                    "properties": {
                        "alert_id": row["alert_id"],
                        "incident_type": row["incident_type"],
                        "severity": row["severity"],
                        "timestamp": row["timestamp"],
                        "formatted_time": row["formatted_time"],
                        "license_plate": row["license_plate"] if "license_plate" in row.keys() else None,
                        "speed_kmh": row["speed_kmh"] if "speed_kmh" in row.keys() else None,
                        "zone_id": row["zone_id"],
                    },
                })
            return {
                "type": "FeatureCollection",
                "features": features,
            }
        finally:
            conn.close()
