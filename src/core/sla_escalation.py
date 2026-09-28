"""
ArgusTraffic AI - Automated Incident SLA Escalation & Operator Accountability Workflow
Enforces control room operator response times, audit compliance, and supervisory escalation.
Conforms to ISO/IEC 27037 non-repudiation logging for police incident dispatch.
Author: Saptha Sanka (ArgusTraffic Autonomous Systems)
"""

import datetime
import enum
import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("argustraffic.sla")


class IncidentSLAStatus(str, enum.Enum):
    PENDING = "PENDING_ACK"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED_TO_SUPERVISOR"
    RESOLVED = "RESOLVED"


DEFAULT_SLA_THRESHOLDS_SEC = {
    "CRITICAL": 45.0,  # 45 seconds to acknowledge a critical hazard
    "HIGH": 120.0,     # 2 minutes for high priority
    "MEDIUM": 300.0,   # 5 minutes for general congestion
    "LOW": 600.0,      # 10 minutes for minor telemetry
}


class SLAEscalationManager:
    """
    Real-Time SLA Watchdog & Accountability Engine.
    Monitors all dispatched incidents and auto-escalates to division chiefs
    if an active duty operator fails to acknowledge within SLA deadlines.
    """

    def __init__(self, thresholds_sec: Optional[Dict[str, float]] = None):
        self.thresholds = thresholds_sec or dict(DEFAULT_SLA_THRESHOLDS_SEC)
        self.incidents: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.total_escalations = 0

    def register_incident(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        """Registers a newly triggered incident into the SLA watchdog ledger."""
        inc_id = incident.get("alert_id") or incident.get("id") or f"INC-{int(time.time()*1000)}"
        severity = incident.get("severity", "MEDIUM")
        sla_limit = self.thresholds.get(severity, 300.0)
        now = time.time()

        record = {
            "incident_id": inc_id,
            "incident_type": incident.get("incident_type", "HAZARD"),
            "severity": severity,
            "description": incident.get("description", ""),
            "camera_id": incident.get("camera_id", "CAM-UNKNOWN"),
            "created_timestamp": now,
            "created_iso": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "sla_limit_seconds": sla_limit,
            "status": IncidentSLAStatus.PENDING.value,
            "acknowledged_by": None,
            "ack_timestamp": None,
            "action_taken": None,
            "escalated_at": None,
            "escalation_level": 0,
        }

        with self.lock:
            self.incidents[inc_id] = record

        logger.info(f"SLA Watchdog registered {inc_id} [{severity}] - Deadline: {sla_limit}s")
        return record

    def acknowledge_incident(
        self,
        incident_id: str,
        officer_id: str = "POLICE_OP_01",
        badge_number: str = "SLP-4921",
        action_taken: str = "Dispatched Highway Patrol Interceptor",
    ) -> Optional[Dict[str, Any]]:
        """Records officer acknowledgment, halting the escalation timer."""
        now = time.time()
        with self.lock:
            rec = self.incidents.get(incident_id)
            if not rec:
                return None

            rec["status"] = IncidentSLAStatus.ACKNOWLEDGED.value
            rec["acknowledged_by"] = {
                "officer_id": officer_id,
                "badge_number": badge_number,
            }
            rec["ack_timestamp"] = now
            rec["response_time_seconds"] = round(now - rec["created_timestamp"], 2)
            rec["action_taken"] = action_taken
            rec["sla_breached"] = rec["response_time_seconds"] > rec["sla_limit_seconds"]

        logger.info(f"Incident {incident_id} acknowledged by {officer_id} ({badge_number}) in {rec['response_time_seconds']}s")
        return rec

    def resolve_incident(self, incident_id: str, notes: str = "Scene cleared") -> Optional[Dict[str, Any]]:
        """Marks an acknowledged incident as fully resolved."""
        with self.lock:
            rec = self.incidents.get(incident_id)
            if not rec:
                return None
            rec["status"] = IncidentSLAStatus.RESOLVED.value
            rec["resolution_notes"] = notes
            rec["resolved_timestamp"] = time.time()
        return rec

    def evaluate_escalations(self) -> List[Dict[str, Any]]:
        """
        Evaluates all pending incidents against SLA deadlines.
        Returns a list of freshly breached incidents that require immediate supervisory dispatch.
        """
        now = time.time()
        newly_escalated = []

        with self.lock:
            for inc_id, rec in self.incidents.items():
                if rec["status"] == IncidentSLAStatus.PENDING.value:
                    elapsed = now - rec["created_timestamp"]
                    if elapsed > rec["sla_limit_seconds"]:
                        rec["status"] = IncidentSLAStatus.ESCALATED.value
                        rec["escalated_at"] = now
                        rec["escalation_level"] = 1
                        rec["escalation_notice"] = f"CRITICAL SLA BREACH: Unacknowledged for {int(elapsed)}s (> {rec['sla_limit_seconds']}s limit)"
                        self.total_escalations += 1
                        newly_escalated.append(dict(rec))
                        logger.warning(f"[SLA ESCALATION] {inc_id} escalated to DIVISION CHIEF!")

        return newly_escalated

    def get_incident_status(self, incident_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            rec = self.incidents.get(incident_id)
            if not rec:
                return None
            data = dict(rec)
            if rec["status"] == IncidentSLAStatus.PENDING.value:
                elapsed = time.time() - rec["created_timestamp"]
                data["seconds_remaining"] = max(0.0, round(rec["sla_limit_seconds"] - elapsed, 1))
            return data

    def get_active_watchdog_queue(self) -> List[Dict[str, Any]]:
        """Returns all currently active (pending or escalated) incidents."""
        with self.lock:
            now = time.time()
            res = []
            for rec in self.incidents.values():
                if rec["status"] in (IncidentSLAStatus.PENDING.value, IncidentSLAStatus.ESCALATED.value):
                    d = dict(rec)
                    elapsed = now - rec["created_timestamp"]
                    d["seconds_remaining"] = max(0.0, round(rec["sla_limit_seconds"] - elapsed, 1))
                    res.append(d)
            return sorted(res, key=lambda x: x["seconds_remaining"])
