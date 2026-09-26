"""
Unit & Integration Tests for ArgusTraffic AI V2 Platform:
World Model, Digital Twin What-If Simulation, V2X Gateway & Traffic Copilot.
"""

import pytest

from src.core.world_model import (
    ArgusWorldModel,
    DynamicWorldEntity,
    LaneMovement,
    TrafficState,
)
from src.core.digital_twin import (
    ArgusDigitalTwin,
    ScenarioIntervention,
    SimulationResult,
)
from src.core.v2x_gateway import (
    BasicSafetyMessage,
    RoadSafetyAdvisory,
    V2XGateway,
)
from src.core.copilot import TrafficCopilot, CopilotResponse


def test_world_model_topology_and_lane_metrics():
    wm = ArgusWorldModel(city_name="TestCity")
    assert len(wm.corridors) > 0
    assert len(wm.intersections) > 0
    assert len(wm.lanes) > 0

    # Verify lane entity
    lane = wm.lanes["LANE_J1_NB_1"]
    assert lane.movement_type == LaneMovement.STRAIGHT
    assert lane.speed_limit_kmh == 60.0

    # Update lane metrics with heavy queue
    updated = wm.update_lane_metrics(
        lane_id="LANE_J1_NB_1",
        vehicle_count=25,
        queue_meters=140.0,
        is_blocked=False,
    )
    assert updated is not None
    assert updated.current_occupancy_ratio > 0.80

    # Evaluate corridor state
    state = wm.evaluate_corridor_state("CORRIDOR_GRAND_CENTRAL")
    assert state in [TrafficState.CONGESTED, TrafficState.GRIDLOCK, TrafficState.SLOW]


def test_world_model_dynamic_entity_fusion():
    wm = ArgusWorldModel()
    entity = DynamicWorldEntity(
        entity_id="VEH_SIM_99",
        entity_type="emergency",
        location_utm=(-73.9772, 40.7527),
        velocity_mps=(15.0, 0.0),
        speed_kmh=54.0,
        heading_deg=90.0,
        confidence=0.98,
        source_sensor_id="CAM_TEST_01",
    )
    wm.update_dynamic_entity(entity)
    assert "VEH_SIM_99" in wm.dynamic_entities
    assert wm.dynamic_entities["VEH_SIM_99"].speed_kmh == 54.0


def test_digital_twin_what_if_lane_closure():
    wm = ArgusWorldModel()
    twin = ArgusDigitalTwin(world_model=wm)

    intervention = ScenarioIntervention(
        action_type="LANE_CLOSURE",
        target_id="LANE_J1_NB_1",
    )

    result = twin.run_what_if_scenario(
        scenario_name="Test Lane Closure",
        interventions=[intervention],
        duration_minutes=20,
    )

    assert isinstance(result, SimulationResult)
    assert result.simulated_delay_sec > result.baseline_delay_sec
    assert result.delay_change_percent > 0
    assert result.max_queue_length_m >= 0
    assert len(result.recommendations) > 0


def test_digital_twin_weather_degradation():
    wm = ArgusWorldModel()
    twin = ArgusDigitalTwin(world_model=wm)

    intervention = ScenarioIntervention(
        action_type="WEATHER_DEGRADATION",
        target_id="CORRIDOR_GRAND_CENTRAL",
        parameters={"condition": "HEAVY_RAIN"},
    )

    result = twin.run_what_if_scenario(
        scenario_name="Heavy Rain Test",
        interventions=[intervention],
        duration_minutes=15,
    )

    assert result.simulated_throughput_vph < result.baseline_throughput_vph
    assert any("advisory speed" in r.lower() for r in result.recommendations)


def test_v2x_gateway_bsm_ingestion():
    wm = ArgusWorldModel()
    gateway = V2XGateway(world_model=wm)

    bsm = BasicSafetyMessage(
        vehicle_id="CONN_VEH_77",
        latitude=40.7520,
        longitude=-73.9770,
        elevation_m=10.0,
        speed_kmh=48.0,
        heading_deg=0.0,
        brake_active=False,
        transmission_state="FORWARD",
    )

    success = gateway.ingest_bsm(bsm)
    assert success is True
    assert "CONN_VEH_77" in gateway.connected_vehicle_registry
    # Verify fused dynamic entity in world model
    assert "V2X_CONN_VEH_77" in wm.dynamic_entities


def test_v2x_gateway_advisory_broadcasting():
    gateway = V2XGateway()
    advisory = gateway.broadcast_road_safety_advisory(
        hazard_type="WRONG_WAY_DRIVER",
        location=(-73.9772, 40.7527),
        radius_m=500.0,
        recommended_speed=20.0,
        urgency="CRITICAL",
        duration_sec=30.0,
    )

    assert advisory.hazard_type == "WRONG_WAY_DRIVER"
    assert advisory.urgency_level == "CRITICAL"
    assert len(gateway.get_active_advisories()) == 1


def test_traffic_copilot_decision_support():
    wm = ArgusWorldModel()
    copilot = TrafficCopilot(world_model=wm)

    # 1. Congestion inquiry
    resp = copilot.ask("Why is traffic slow on Grand Central corridor?")
    assert isinstance(resp, CopilotResponse)
    assert resp.confidence_score > 0.8
    assert len(resp.causal_factors) > 0
    assert len(resp.recommendations) > 0
    assert resp.recommendations[0].requires_human_approval is True
    assert "SAFETY NOTICE" in resp.execution_notice

    # 2. General overview inquiry
    overview = copilot.ask("What is the system network status?")
    assert "World Model" in overview.current_status
