"""
ArgusTraffic AI - Real-Time Wanted Vehicle Hotlist & Instant Interception Engine
Provides:
1. Sub-millisecond plate lookup with OCR optical noise tolerance (Fuzzy Levenshtein matching).
2. Multi-tier classification: STOLEN_VEHICLE, WANTED_FELON, AMBER_ALERT, EXPIRED_REVENUE.
3. Automated Interception alert generator with GPS coordinates, camera ID, and tactical dispatch.
Author: ArgusTraffic Autonomous Systems Engineering Team
"""

import datetime
import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("argustraffic.hotlist")


def normalize_plate(plate: str) -> str:
    """Removes spaces, hyphens, and converts to uppercase for canonical matching."""
    if not plate:
        return ""
    return re.sub(r"[^A-Z0-9]", "", plate.upper())


def compute_ocr_distance(s1: str, s2: str) -> int:
    """
    Computes Levenshtein edit distance with optical OCR confusions:
    Treats ('O', '0'), ('I', '1'), ('B', '8'), ('S', '5'), ('Z', '2') as near-zero cost.
    """
    # Optical equivalence map
    equiv = {"0": "O", "1": "I", "8": "B", "5": "S", "2": "Z"}
    
    n1 = "".join(equiv.get(c, c) for c in s1)
    n2 = "".join(equiv.get(c, c) for c in s2)
    
    if n1 == n2:
        return 0

    # Standard Levenshtein
    m, n = len(n1), len(n2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if n1[i - 1] == n2[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,      # Deletion
                dp[i][j - 1] + 1,      # Insertion
                dp[i - 1][j - 1] + cost # Substitution
            )
    return dp[m][n]


class WantedVehicleHotlistEngine:
    """
    High-Performance Police Hotlist Database & Real-Time Interception Trigger.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.hotlist: Dict[str, Dict[str, Any]] = {}
        self.total_queries = 0
        self.total_matches = 0
        self._load_default_hotlist()

    def _load_default_hotlist(self) -> None:
        """Populates national traffic police sample hotlist records."""
        defaults = [
            {
                "plate": "CP-HVY-3012",
                "category": "STOLEN_VEHICLE",
                "severity": "CRITICAL",
                "description": "Reported stolen commercial freight van (Regional APB)",
                "vehicle_model": "Commercial Freight Van (Red)",
                "owner_name": "Commercial Logistics Corp",
                "reported_date": "2026-09-27T08:30:00Z",
                "flagged_by": "National Law Enforcement Network",
            },
            {
                "plate": "WP-CAR-7821",
                "category": "EXPIRED_REVENUE_LICENSE",
                "severity": "MEDIUM",
                "description": "Commercial registration expired > 180 days (Department of Motor Vehicles)",
                "vehicle_model": "Midsize Sedan (Silver)",
                "owner_name": "Commercial Transport Fleet",
                "reported_date": "2026-09-01T00:00:00Z",
                "flagged_by": "DMV Compliance Bureau",
            },
            {
                "plate": "NW-SUV-9014",
                "category": "WANTED_FELON",
                "severity": "CRITICAL",
                "description": "Wanted vehicle alert - Inter-agency high priority advisory",
                "vehicle_model": "Utility SUV (Dark Blue)",
                "owner_name": "Inter-Agency Advisory",
                "reported_date": "2026-09-28T14:15:00Z",
                "flagged_by": "Special Operations Command",
            },
        ]
        for d in defaults:
            self.add_record(d["plate"], d)

    def add_record(self, plate: str, record_data: Dict[str, Any]) -> str:
        """Adds or updates a vehicle plate record in the hotlist."""
        norm = normalize_plate(plate)
        with self.lock:
            self.hotlist[norm] = {
                "plate_raw": plate,
                "plate_normalized": norm,
                **record_data,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        logger.info(f"Hotlist registered plate: {plate} [{record_data.get('category')}]")
        return norm

    def remove_record(self, plate: str) -> bool:
        """Removes a vehicle plate record from the hotlist."""
        norm = normalize_plate(plate)
        with self.lock:
            if norm in self.hotlist:
                del self.hotlist[norm]
                return True
        return False

    def lookup_plate(
        self,
        plate: str,
        allow_fuzzy: bool = True,
        max_edit_distance: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        Sub-millisecond plate matching.
        1. Exact canonical normalized match.
        2. Optical OCR fuzzy match (if allow_fuzzy is True).
        """
        self.total_queries += 1
        query_norm = normalize_plate(plate)
        if not query_norm:
            return None

        # 1. Exact match
        with self.lock:
            if query_norm in self.hotlist:
                self.total_matches += 1
                rec = dict(self.hotlist[query_norm])
                rec["match_type"] = "EXACT"
                rec["confidence"] = 1.0
                return rec

            # 2. Fuzzy match
            if allow_fuzzy and len(query_norm) >= 4:
                for target_norm, data in self.hotlist.items():
                    if abs(len(target_norm) - len(query_norm)) <= max_edit_distance:
                        dist = compute_ocr_distance(query_norm, target_norm)
                        if dist <= max_edit_distance:
                            self.total_matches += 1
                            rec = dict(data)
                            rec["match_type"] = "FUZZY_OCR"
                            rec["edit_distance"] = dist
                            rec["confidence"] = round(1.0 - (dist * 0.15), 2)
                            return rec

        return None

    def generate_interception_payload(
        self,
        plate: str,
        camera_id: str,
        gps_coords: Optional[Tuple[float, float]] = None,
        speed_kmh: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Checks plate against hotlist and constructs an urgent police dispatch payload if positive.
        """
        hit = self.lookup_plate(plate)
        if not hit:
            return None

        return {
            "alert_type": "WANTED_VEHICLE_INTERCEPTION",
            "category": hit.get("category", "SECURITY_ALERT"),
            "severity": hit.get("severity", "CRITICAL"),
            "detected_plate": plate,
            "matched_plate": hit.get("plate_raw"),
            "match_confidence": hit.get("confidence", 1.0),
            "match_type": hit.get("match_type", "EXACT"),
            "camera_id": camera_id,
            "vehicle_model": hit.get("vehicle_model", "Unknown Model"),
            "description": hit.get("description", ""),
            "owner_name": hit.get("owner_name", ""),
            "flagged_by": hit.get("flagged_by", "National Police Central"),
            "gps_location": gps_coords or (6.9271, 79.8612),  # Default Metropolitan Command Sector
            "speed_kmh": round(speed_kmh, 1) if speed_kmh else None,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "interception_priority": "PRIORITY_1_HIGH_IMPACT",
        }

    def get_all_records(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.hotlist.values())

    def get_statistics(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "total_records": len(self.hotlist),
                "total_queries": self.total_queries,
                "total_matches": self.total_matches,
                "match_rate_pct": round((self.total_matches / max(1, self.total_queries)) * 100, 2),
            }
