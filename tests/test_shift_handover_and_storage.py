"""
ArgusTraffic AI - Shift Handover & Storage Watchdog Test Suite
Verifies:
1. ShiftHandoverEngine operational statistics aggregation and HMAC integrity signature.
2. HTML dossier generation.
3. Legal Hold protection during FIFO disk purging.
4. Storage status and capacity calculation.
"""

import os
from pathlib import Path
import tempfile
import pytest

from src.core.auth_rbac import Role
from src.core.shift_handover import ShiftHandoverEngine, ShiftHandoverReport
from src.core.storage_watchdog import StorageWatchdogManager, StorageHealthStatus


def test_shift_handover_generation_and_signature():
    engine = ShiftHandoverEngine(secret_key="TEST_SHIFT_KEY_123")
    app_state = {
        "incident_engine": None,
        "camera_watchdog": None,
        "hotlist_engine": None,
    }

    report = engine.generate_shift_handover(
        app_state=app_state,
        operator_username="OFFICER_SILVA",
        operator_role=Role.STATION_ADMIN,
        operator_division="DIV_COLOMBO_CENTRAL",
        station_name="Fort Traffic Command",
        duration_hours=8.0,
        outgoing_notes="Corridor Alpha clear. Radar active.",
    )

    assert isinstance(report, ShiftHandoverReport)
    assert report.operator_username == "OFFICER_SILVA"
    assert report.division_id == "DIV_COLOMBO_CENTRAL"
    assert len(report.handover_hmac_signature) == 64 # SHA256 hex string
    assert report.duration_hours == 8.0


def test_shift_handover_html_dossier():
    engine = ShiftHandoverEngine()
    app_state = {}
    report = engine.generate_shift_handover(
        app_state=app_state,
        operator_username="SUPERVISOR_PERERA",
        outgoing_notes="Shift nominal. Rain expected on coastal highway.",
    )
    html = engine.generate_html_dossier(report)

    assert "<!DOCTYPE html>" in html
    assert "SHIFT HANDOVER DOSSIER" in html
    assert "SUPERVISOR_PERERA" in html
    assert "Shift nominal. Rain expected" in html
    assert report.handover_hmac_signature[:16] in html


def test_storage_watchdog_legal_hold_protection(tmp_path):
    storage_dir = tmp_path / "argus_data"
    storage_dir.mkdir()
    snapshots_dir = storage_dir / "snapshots"
    snapshots_dir.mkdir()

    # Create dummy regular files and a legal hold file
    file1 = snapshots_dir / "unflagged_clip_01.mp4"
    file1.write_bytes(b"A" * 1024 * 100) # 100 KB

    file2 = snapshots_dir / "unflagged_clip_02.mp4"
    file2.write_bytes(b"B" * 1024 * 100) # 100 KB

    legal_hold_file = snapshots_dir / "court_evidence_critical.mp4"
    legal_hold_file.write_bytes(b"C" * 1024 * 200) # 200 KB

    mgr = StorageWatchdogManager(data_dir=str(storage_dir))
    mgr.add_legal_hold(legal_hold_file)

    assert mgr.is_protected_file(legal_hold_file) is True
    assert mgr.is_protected_file(file1) is False

    # Execute purge forcing cleanup
    res = mgr.execute_fifo_purge(max_target_used_pct=0.0001, dry_run=False)
    assert res["purge_executed"] is True

    # Regular files should be pruned, legal hold must be intact
    assert not file1.exists()
    assert not file2.exists()
    assert legal_hold_file.exists() # PRESERVED BY LEGAL HOLD!


def test_storage_watchdog_status(tmp_path):
    mgr = StorageWatchdogManager(data_dir=str(tmp_path))
    status = mgr.get_storage_status()

    assert "status" in status
    assert "percent_used" in status
    assert "free_gb" in status
    assert "total_managed_files" in status
