"""
ArgusTraffic AI - Enterprise System Customization & Settings Kernel
Manages persistent agency branding, map tile provider configurations,
optical speed tolerances, SLA alert thresholds, and multi-division preferences.
"""

import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, Optional, Tuple, Union

from src.utils.paths import get_data_dir

logger = logging.getLogger("argustraffic.settings")


DEFAULT_SYSTEM_SETTINGS: Dict[str, Any] = {
    # Organization Branding
    "agency_name": "National Traffic Operations & Municipal Police Command",
    "agency_sub_title": "Autonomous Edge Telemetry & Incident Intelligence Center",
    "agency_logo_url": "",
    "header_badge_text": "METROPOLITAN COMMAND HQ",
    "contact_emergency_phone": "+94 11 243 3333",
    "contact_email": "command.ops@argustraffic.internal",

    # GIS Map Providers & Custom Tile Server
    "default_map_provider": "carto_dark",  # carto_dark | google_road | google_satellite | esri_satellite | osm_standard | custom_wms
    "custom_tile_url": "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    "google_maps_api_key": "",
    "map_center_lat": 6.9271,
    "map_center_lng": 79.8612,
    "map_default_zoom": 13,
    "enable_gis_corridor_polylines": True,
    "enable_gis_radar_sweep_anim": True,

    # Optical Speed Radar & Violation Tolerances
    "speed_limit_urban_kmh": 60.0,
    "speed_limit_expressway_kmh": 100.0,
    "speed_tolerance_grace_kmh": 5.0,  # Grace speed before issuing fine
    "speed_radar_calibration_factor": 1.0,

    # Emergency SLA Timers & Alarms
    "sla_critical_timeout_sec": 120,  # 2-minute default SLA
    "sla_warning_timeout_sec": 300,
    "enable_audio_alarms": False,
    "enable_v2x_broadcasting": True,

    # UI Customization & Appearance
    "ui_theme": "cyberpunk_dark",  # cyberpunk_dark | slate_pro | light_command
    "default_report_template": "tpl_executive_summary",
    "auto_refresh_telemetry_ms": 2000,
}


class SystemSettingsManager:
    """Persistent SQLite-backed Enterprise Settings Manager."""

    _instance = None

    def __new__(cls, db_path: Optional[Union[str, Path]] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is not None:
            self.db_path = Path(db_path)
            self._initialized = True
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
            return
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.db_path = get_data_dir() / "system_settings.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        conn = self._get_connection()
        try:
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
            except Exception:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    updated_by TEXT DEFAULT 'SYSTEM'
                )
            """)
            conn.commit()
        finally:
            conn.close()

        self._seed_default_settings()

    def _seed_default_settings(self):
        with self._get_connection() as conn:
            for k, v in DEFAULT_SYSTEM_SETTINGS.items():
                cursor = conn.cursor()
                cursor.execute("SELECT setting_key FROM settings WHERE setting_key = ?", (k,))
                if not cursor.fetchone():
                    conn.execute(
                        "INSERT INTO settings (setting_key, setting_value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                        (k, json.dumps(v), time.time(), "SYSTEM"),
                    )
            conn.commit()

    def get_all_settings(self) -> Dict[str, Any]:
        """Returns all system settings merged with defaults."""
        result = dict(DEFAULT_SYSTEM_SETTINGS)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT setting_key, setting_value FROM settings")
            for row in cursor.fetchall():
                try:
                    result[row["setting_key"]] = json.loads(row["setting_value"])
                except Exception:
                    result[row["setting_key"]] = row["setting_value"]
        return result

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Retrieves a single system setting value."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT setting_value FROM settings WHERE setting_key = ?", (key,))
            row = cursor.fetchone()
            if row:
                try:
                    return json.loads(row["setting_value"])
                except Exception:
                    return row["setting_value"]
        return DEFAULT_SYSTEM_SETTINGS.get(key, default)

    def update_settings(self, updates: Dict[str, Any], operator_username: str = "SYSTEM") -> Tuple[bool, str]:
        """Updates multiple system settings persistently."""
        with self._get_connection() as conn:
            now = time.time()
            for k, v in updates.items():
                val_json = json.dumps(v)
                conn.execute(
                    """
                    INSERT INTO settings (setting_key, setting_value, updated_at, updated_by)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(setting_key) DO UPDATE SET
                        setting_value = excluded.setting_value,
                        updated_at = excluded.updated_at,
                        updated_by = excluded.updated_by
                """,
                    (k, val_json, now, operator_username),
                )
            conn.commit()
        return True, "System settings updated successfully."
