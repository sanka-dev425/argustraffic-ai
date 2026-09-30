"""
Unit Tests for User-Side & Operator Workflow Upgrades:
1. 1-Click Court-Ready Evidence ZIP Bundle Exporter
2. Bulk Police Hotlist CSV/Text Importer
3. Rapid Incident Triage REST Endpoints
"""

import io
from pathlib import Path
import tempfile
import zipfile
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.core.evidence_bundle import EvidenceBundleExporter, build_legal_attestation
from src.core.hotlist_engine import WantedVehicleHotlistEngine


client = TestClient(app)


def test_build_legal_attestation():
    """Verifies legal attestation text format contains ISO/IEC 27037 declarations."""
    incident = {
        "alert_id": "INC-TEST-9988",
        "timestamp": 1774900000.0,
        "incident_type": "WRONG_WAY",
        "severity": "CRITICAL",
        "license_plate": "CP-ABC-1234",
        "speed_kmh": 85.0,
    }
    text = build_legal_attestation(incident)
    assert "ISO/IEC 27037:2012" in text
    assert "INC-TEST-9988" in text
    assert "CP-ABC-1234" in text
    assert "85.0 km/h" in text


def test_evidence_bundle_exporter_zip():
    """Verifies complete Court Evidence ZIP generation and contents."""
    with tempfile.TemporaryDirectory() as tmpdir:
        exporter = EvidenceBundleExporter(output_dir=Path(tmpdir))
        incident = {
            "alert_id": "INC-ZIP-001",
            "incident_type": "COLLISION_RISK",
            "severity": "HIGH",
            "timestamp": 1774900100.0,
            "license_plate": "WP-TEST-7788",
            "description": "High probability intersection hazard detected.",
            "location": [500.0, 300.0],
            "speed_kmh": 64.0,
        }

        zip_path = exporter.generate_zip_bundle(incident)
        assert zip_path.exists()
        assert zip_path.name.endswith(".zip")

        # Verify ZIP contains required forensic documents
        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            assert "01_Forensic_Investigation_Report.html" in namelist
            assert "02_Court_Legal_Attestation.txt" in namelist
            assert "03_Chain_of_Custody_Certificate.json" in namelist


def test_hotlist_bulk_import():
    """Verifies bulk CSV parsing and registration of wanted vehicle plates."""
    engine = WantedVehicleHotlistEngine()
    csv_sample = """# Stolen Vehicles Morning Shift
CP-XYZ-1122, STOLEN_VEHICLE, CRITICAL, Toyota Corolla, Stolen from Colombo 07, A. Perera
WP-CAR-9900, WANTED_FELON, CRITICAL, Honda Civic, Armed Robbery Suspect, Police CID
SP-VAN-4433, AMBER_ALERT, HIGH, Nissan Caravan, Missing child search, Child Protection
"""
    res = engine.bulk_import_csv(csv_sample, default_agency="National Police Division")
    assert res["success"] is True
    assert res["records_added"] == 3

    # Plate lookup verification
    hit1 = engine.lookup_plate("CP-XYZ-1122")
    assert hit1 is not None
    assert hit1["category"] == "STOLEN_VEHICLE"

    hit2 = engine.lookup_plate("WP-CAR-9900")
    assert hit2 is not None
    assert hit2["category"] == "WANTED_FELON"


def test_api_court_bundle_and_bulk_import():
    """Verifies REST endpoints for evidence bundle and bulk hotlist import."""
    # 1. Bulk Hotlist Import endpoint
    csv_payload = "WP-API-1234, STOLEN_VEHICLE, CRITICAL, Mazda 3, Stolen Vehicle, Traffic Unit\n"
    res_import = client.post("/api/v1/hotlist/bulk-import", json={"csv_content": csv_payload})
    assert res_import.status_code == 200
    data = res_import.json()
    assert data["success"] is True

    # 2. Incident Triage endpoint
    res_triage = client.post(
        "/api/v1/incidents/INC-DEMO-001/triage",
        json={"action": "ACKNOWLEDGE", "operator_name": "Sergeant Silva", "operator_notes": "Patrol alerted"},
    )
    assert res_triage.status_code == 200
    assert res_triage.json()["action_taken"] == "ACKNOWLEDGE"

    # 3. Evidence Bundle Download endpoint
    res_bundle = client.get("/api/v1/evidence/bundle/INC-DEMO-001")
    assert res_bundle.status_code == 200
    assert res_bundle.headers["content-type"] == "application/zip"
    assert len(res_bundle.content) > 100
