"""
ArgusTraffic AI - National Police HQ & Multi-Station Mesh Aggregator
Connects regional municipal police divisions (e.g. Colombo, Kandy, Galle)
into a unified nationwide tactical command grid.
Enforces multi-tenant data isolation while granting National HQ supervisory overview.
Author: Saptha Sanka (ArgusTraffic Autonomous Systems)
"""

import datetime
import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("argustraffic.mesh")


class PoliceDivisionNode:
    """Represents a regional police division operating an edge ArgusTraffic server."""

    def __init__(self, division_id: str, division_name: str, jurisdiction: str, ip_address: str):
        self.division_id = division_id
        self.division_name = division_name
        self.jurisdiction = jurisdiction
        self.ip_address = ip_address
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
            "is_online": self.is_online,
            "last_heartbeat": self.last_heartbeat,
            "camera_count": self.camera_count,
            "active_incidents_count": self.active_incidents_count,
            "total_traffic_flow_vph": self.total_traffic_flow_vph,
        }


class NationalStationMeshAggregator:
    """
    Central Command Broker aggregating multi-station edge nodes across the country.
    """

    def __init__(self, local_division_id: str = "DIV_COLOMBO_CENTRAL"):
        self.local_division_id = local_division_id
        self.divisions: Dict[str, PoliceDivisionNode] = {}
        self.lock = threading.Lock()
        self._init_national_mesh()

    def _init_national_mesh(self) -> None:
        """Initializes default municipal division nodes across Sri Lanka."""
        defaults = [
            PoliceDivisionNode("DIV_COLOMBO_CENTRAL", "Metropolitan Command HQ", "Capital Metropolitan Sector", "10.0.1.10"),
            PoliceDivisionNode("DIV_KANDY", "North District Command", "Northern Expressway Sector", "10.0.2.10"),
            PoliceDivisionNode("DIV_GALLE", "South District Command", "Southern Coastal Sector", "10.0.3.10"),
            PoliceDivisionNode("DIV_JAFFNA", "Eastern District Command", "Eastern Intermodal Sector", "10.0.4.10"),
        ]
        defaults[0].camera_count = 14
        defaults[0].total_traffic_flow_vph = 2450
        defaults[1].camera_count = 8
        defaults[1].total_traffic_flow_vph = 1120
        defaults[2].camera_count = 6
        defaults[2].total_traffic_flow_vph = 890
        defaults[3].camera_count = 5
        defaults[3].total_traffic_flow_vph = 640

        for d in defaults:
            self.divisions[d.division_id] = d

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
                d.is_online = (now - d.last_heartbeat) < 15.0
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
