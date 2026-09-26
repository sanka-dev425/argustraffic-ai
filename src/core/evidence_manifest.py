"""
ArgusTraffic AI - Cryptographic Evidence Manifest & Chain-of-Custody Integrity
Produces tamper-evident forensic packages with SHA-256 digital hashing,
operator audit metadata, and exportable verification manifests.
"""

from dataclasses import dataclass, field
import datetime
import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

from src.core.interfaces import IncidentEvent, IncidentSeverity, IncidentType

logger = logging.getLogger("argustraffic.evidence.manifest")


@dataclass
class EvidenceItem:
    item_type: str  # e.g., "telemetry_json", "frame_snapshot", "trajectory_trace"
    filename: str
    sha256_hash: str
    byte_size: int
    content_type: str


@dataclass
class EvidencePackage:
    incident_id: str
    incident_type: str
    severity: str
    timestamp_utc: str
    camera_id: str
    location: str
    involved_tracks: List[int]
    manifest_hash: str
    items: List[EvidenceItem] = field(default_factory=list)
    operator_audit_signature: Optional[str] = None
    system_version: str = "1.2.0"

    def verify_integrity(self) -> bool:
        """Re-computes and validates manifest integrity."""
        calculated = compute_manifest_hash(
            incident_id=self.incident_id,
            timestamp_utc=self.timestamp_utc,
            items=self.items,
        )
        return calculated == self.manifest_hash


def compute_sha256_bytes(data: bytes) -> str:
    """Computes standard SHA-256 hexadecimal digest for binary buffers."""
    return hashlib.sha256(data).hexdigest()


def compute_manifest_hash(incident_id: str, timestamp_utc: str, items: List[EvidenceItem]) -> str:
    """Generates a deterministic cryptographic root hash over the entire evidence bundle."""
    item_digests = sorted([f"{item.filename}:{item.sha256_hash}" for item in items])
    payload = f"{incident_id}|{timestamp_utc}|{';'.join(item_digests)}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def create_forensic_evidence_package(
    incident: IncidentEvent,
    snapshot_bytes: Optional[bytes] = None,
    trajectory_data: Optional[Dict[str, Any]] = None,
    operator_id: str = "SYSTEM_AUTOMATION",
) -> EvidencePackage:
    """
    Constructs a complete, tamper-evident forensic evidence package.
    """
    dt = datetime.datetime.fromtimestamp(incident.timestamp, datetime.timezone.utc)
    ts_utc = dt.isoformat()

    items: List[EvidenceItem] = []

    # 1. Telemetry metadata payload
    telemetry_bytes = json.dumps(
        {
            "incident_id": incident.incident_id,
            "incident_type": incident.incident_type.value if hasattr(incident.incident_type, "value") else str(incident.incident_type),
            "severity": incident.severity.value if hasattr(incident.severity, "value") else str(incident.severity),
            "timestamp": incident.timestamp,
            "camera_id": incident.camera_id,
            "location": incident.location,
            "confidence": incident.confidence,
            "telemetry": incident.telemetry,
        },
        sort_keys=True,
    ).encode("utf-8")

    items.append(
        EvidenceItem(
            item_type="telemetry_json",
            filename="telemetry.json",
            sha256_hash=compute_sha256_bytes(telemetry_bytes),
            byte_size=len(telemetry_bytes),
            content_type="application/json",
        )
    )

    # 2. Snapshot frame binary (if available)
    if snapshot_bytes:
        items.append(
            EvidenceItem(
                item_type="frame_snapshot",
                filename="incident_snapshot.jpg",
                sha256_hash=compute_sha256_bytes(snapshot_bytes),
                byte_size=len(snapshot_bytes),
                content_type="image/jpeg",
            )
        )

    # 3. Trajectory kinematic reconstruction
    if trajectory_data:
        traj_bytes = json.dumps(trajectory_data, sort_keys=True).encode("utf-8")
        items.append(
            EvidenceItem(
                item_type="trajectory_trace",
                filename="trajectory.json",
                sha256_hash=compute_sha256_bytes(traj_bytes),
                byte_size=len(traj_bytes),
                content_type="application/json",
            )
        )

    # 4. Generate root manifest hash
    manifest_hash = compute_manifest_hash(incident.incident_id, ts_utc, items)

    # 5. Operator chain-of-custody seal
    operator_seal = hashlib.sha256(
        f"{manifest_hash}:{operator_id}:{ts_utc}".encode("utf-8")
    ).hexdigest()

    inc_type_str = incident.incident_type.value if hasattr(incident.incident_type, "value") else str(incident.incident_type)
    severity_str = incident.severity.value if hasattr(incident.severity, "value") else str(incident.severity)

    return EvidencePackage(
        incident_id=incident.incident_id,
        incident_type=inc_type_str,
        severity=severity_str,
        timestamp_utc=ts_utc,
        camera_id=incident.camera_id,
        location=incident.location,
        involved_tracks=incident.track_ids,
        manifest_hash=manifest_hash,
        items=items,
        operator_audit_signature=operator_seal,
    )
