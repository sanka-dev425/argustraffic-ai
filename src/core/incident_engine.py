"""
ArgusTraffic AI - Autonomous Incident Detection Engine
Evaluates spatial-temporal rules over tracked objects and geometric zones:
- Wrong-way driving
- Vehicle collisions / multi-car accidents
- Stalled / stranded vehicle lane blockage
- Pedestrian jaywalking & vehicle near-miss proximity
- Emergency vehicle corridor priority
"""

from collections import defaultdict
from dataclasses import dataclass, field
import datetime
import math
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from src.core.detector import Detection
from src.core.tracker import SpatialTracker, Track, compute_iou
from src.core.zone_manager import TrafficZone, ZoneManager
from src.core.speed_engine import SpeedRadarEngine
from src.core.anpr_engine import ANPREngine
from src.core.anomaly_engine import AnomalyEngine


@dataclass
class IncidentAlert:
    alert_id: str
    incident_type: str  # 'WRONG_WAY', 'COLLISION', 'STALLED_VEHICLE', 'PEDESTRIAN_HAZARD', 'EMERGENCY_CORRIDOR', 'SPEED_VIOLATION', 'ABNORMAL_SWERVE'
    severity: str  # 'CRITICAL', 'WARNING', 'INFO'
    timestamp: float
    description: str
    location: Tuple[float, float]  # (x, y) coordinates
    involved_track_ids: List[int]
    zone_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    speed_kmh: Optional[float] = None
    license_plate: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        dt = datetime.datetime.fromtimestamp(self.timestamp)
        return {
            "alert_id": self.alert_id,
            "incident_type": self.incident_type,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "formatted_time": dt.strftime("%H:%M:%S.%f")[:-3],
            "description": self.description,
            "location": self.location,
            "involved_track_ids": self.involved_track_ids,
            "zone_id": self.zone_id,
            "metadata": self.metadata,
            "speed_kmh": self.speed_kmh,
            "license_plate": self.license_plate,
        }


class IncidentEngine:
    """Evaluates multi-hazard traffic rules in real time."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.incidents_cfg = self.config.get("incidents", {})

        # Enterprise Intelligence Subsystems
        self.speed_radar = SpeedRadarEngine(
            pixels_per_meter=float(self.config.get("speed_radar", {}).get("pixels_per_meter", 18.5)),
            speed_limit_kmh=float(self.config.get("speed_radar", {}).get("speed_limit_kmh", 60.0)),
        )
        self.anpr_engine = ANPREngine(confidence_threshold=0.85)
        self.anomaly_detector = AnomalyEngine(
            swerve_variance_threshold=float(self.config.get("anomaly", {}).get("swerve_variance_threshold", 450.0)),
            deceleration_threshold_ms2=6.5,
        )

        # State tracking for duration-based incidents
        self.stationary_track_frames: Dict[int, int] = defaultdict(int)
        self.collision_pairs_frames: Dict[Tuple[int, int], int] = defaultdict(int)
        self.wrong_way_sustained_frames: Dict[int, int] = defaultdict(int)

        # Incident history log (retains most recent 500 events)
        self.active_alerts: List[IncidentAlert] = []
        self.alert_counter = 1

        # Incident suppression to avoid spamming the same event every single frame
        self.last_alert_time: Dict[str, float] = {}
        self.suppression_cooldown_sec = 2.5

    def analyze_frame(
        self,
        frame_idx: int,
        detections: List[Detection],
        tracker: SpatialTracker,
        zone_manager: ZoneManager,
        fps: float = 30.0,
    ) -> List[IncidentAlert]:
        """
        Analyzes the current frame for all traffic hazards and anomalies.
        Returns a list of newly triggered alerts for this frame.
        """
        now = time.time()
        new_alerts: List[IncidentAlert] = []

        vehicles: List[Detection] = []
        pedestrians: List[Detection] = []
        emergency_vehicles: List[Detection] = []

        for d in detections:
            cls = d.class_name.lower()
            if cls in ["car", "truck", "bus", "motorcycle"]:
                vehicles.append(d)
            elif cls in ["pedestrian", "bicycle", "person"]:
                pedestrians.append(d)
            elif "ambulance" in cls or "police" in cls or "fire" in cls:
                emergency_vehicles.append(d)

        # 1. Wrong-Way Driving Analysis
        if self.incidents_cfg.get("wrong_way", {}).get("enabled", True):
            for v in vehicles:
                alert = self._check_wrong_way(v, tracker, zone_manager, now)
                if alert:
                    new_alerts.append(alert)

        # 2. Stalled Vehicle / Highway Obstruction Analysis
        if self.incidents_cfg.get("stalled_vehicle", {}).get("enabled", True):
            for v in vehicles:
                alert = self._check_stalled_vehicle(v, tracker, zone_manager, fps, now)
                if alert:
                    new_alerts.append(alert)

        # 3. Collision / Accident Analysis
        if self.incidents_cfg.get("collision", {}).get("enabled", True):
            collision_alerts = self._check_collisions(vehicles, tracker, now)
            new_alerts.extend(collision_alerts)

        # 4. Pedestrian Danger / Jaywalking / Near-Miss
        if self.incidents_cfg.get("pedestrian_danger", {}).get("enabled", True):
            ped_alerts = self._check_pedestrian_hazards(pedestrians, vehicles, tracker, zone_manager, now)
            new_alerts.extend(ped_alerts)

        # 5. Emergency Corridor Priority
        if self.incidents_cfg.get("emergency_vehicle", {}).get("enabled", True):
            for ev in emergency_vehicles:
                alert = self._check_emergency_corridor(ev, tracker, zone_manager, now)
                if alert:
                    new_alerts.append(alert)

        # 6. Optical Speed Radar & ANPR Plate Attribution
        active_track_ids = []
        for v in vehicles:
            if v.track_id is not None:
                active_track_ids.append(v.track_id)
                # Compute optical speed
                spd = self.speed_radar.update_track(v.track_id, v.center[0], v.center[1], now)
                # Plate recognition
                plate_rec = self.anpr_engine.recognize_plate(v.track_id, v.class_name, v.confidence)
                plate_no = plate_rec.get("plate_number")

                # Check Speed Violation
                is_speeding, obs_speed, limit = self.speed_radar.is_speeding(v.track_id)
                if is_speeding:
                    key = f"speed_{v.track_id}"
                    if now - self.last_alert_time.get(key, 0) > self.suppression_cooldown_sec * 3:
                        self.last_alert_time[key] = now
                        alert = IncidentAlert(
                            alert_id=f"ALT-{self.alert_counter:05d}",
                            incident_type="SPEED_VIOLATION",
                            severity="WARNING" if obs_speed < limit + 25 else "CRITICAL",
                            timestamp=now,
                            description=(
                                f"Speed Limit Exceeded! Vehicle #{v.track_id} [{plate_no}] "
                                f"clocked at {obs_speed:.1f} km/h (Limit: {limit:.0f} km/h)"
                            ),
                            location=v.center,
                            involved_track_ids=[v.track_id],
                            speed_kmh=obs_speed,
                            license_plate=plate_no,
                            metadata={"speed_kmh": obs_speed, "limit_kmh": limit, "excess": round(obs_speed - limit, 1)},
                        )
                        self.alert_counter += 1
                        new_alerts.append(alert)

                # Check Trajectory Anomalies (Erratic Swerve / U-Turn / Sudden Braking)
                tr = tracker.get_track(v.track_id)
                if tr:
                    vx, vy = tr.velocity
                    anomalies = self.anomaly_detector.ingest_vector(
                        v.track_id, v.center[0], v.center[1], vx, vy, spd, now
                    )
                    for anom in anomalies:
                        key = f"anom_{anom['type']}_{v.track_id}"
                        if now - self.last_alert_time.get(key, 0) > self.suppression_cooldown_sec * 3:
                            self.last_alert_time[key] = now
                            alert = IncidentAlert(
                                alert_id=f"ALT-{self.alert_counter:05d}",
                                incident_type=anom["type"],
                                severity=anom["severity"],
                                timestamp=now,
                                description=f"{anom['details']} by Vehicle #{v.track_id} [{plate_no}]",
                                location=v.center,
                                involved_track_ids=[v.track_id],
                                speed_kmh=spd,
                                license_plate=plate_no,
                                metadata={"score": anom["score"], "plate": plate_no},
                            )
                            self.alert_counter += 1
                            new_alerts.append(alert)

        # Clean stale track caches
        if active_track_ids:
            self.speed_radar.purge_stale_tracks(active_track_ids)
            self.anpr_engine.purge_stale_tracks(active_track_ids)
            self.anomaly_detector.purge_stale_tracks(active_track_ids)

        # Enrich all alerts with license plate and speed if associated with a vehicle track
        for a in new_alerts:
            if not a.license_plate and a.involved_track_ids:
                first_tid = a.involved_track_ids[0]
                a.license_plate = self.anpr_engine.recognize_plate(first_tid, "car", 0.9).get("plate_number")
                a.speed_kmh = self.speed_radar.get_speed(first_tid)

        # Store in active history
        for a in new_alerts:
            self.active_alerts.append(a)
            if len(self.active_alerts) > 500:
                self.active_alerts.pop(0)

        return new_alerts

    def _check_wrong_way(
        self,
        vehicle: Detection,
        tracker: SpatialTracker,
        zone_manager: ZoneManager,
        now: float,
    ) -> Optional[IncidentAlert]:
        """Detects if a vehicle is travelling against the designated lane flow."""
        if not vehicle.track_id:
            return None

        track = tracker.get_track(vehicle.track_id)
        if not track or len(track.history) < 6:
            return None

        # Determine which zones contain the vehicle center
        zones = zone_manager.get_zones_for_point(track.center)
        lane_zone = next((z for z in zones if z.zone_type == "lane" and z.expected_flow), None)
        if not lane_zone or not lane_zone.expected_flow:
            return None

        # Check vehicle velocity magnitude
        vx, vy = track.velocity
        speed = math.hypot(vx, vy)
        min_speed = self.incidents_cfg.get("wrong_way", {}).get("min_speed_px", 2.0)
        if speed < min_speed:
            self.wrong_way_sustained_frames[vehicle.track_id] = 0
            return None

        # Calculate angle between vehicle trajectory and expected lane flow
        expected_flow = lane_zone.expected_flow
        dot_product = (vx * expected_flow.dx) + (vy * expected_flow.dy)
        norms = speed * expected_flow.magnitude
        if norms <= 0:
            return None

        cosine_sim = np.clip(dot_product / norms, -1.0, 1.0)
        angle_deg = math.degrees(math.acos(cosine_sim))

        dev_angle_threshold = self.incidents_cfg.get("wrong_way", {}).get("deviation_angle_deg", 130.0)

        if angle_deg >= dev_angle_threshold:
            self.wrong_way_sustained_frames[vehicle.track_id] += 1
            if self.wrong_way_sustained_frames[vehicle.track_id] >= 6:
                key = f"wrong_way_{vehicle.track_id}"
                if now - self.last_alert_time.get(key, 0) > self.suppression_cooldown_sec:
                    self.last_alert_time[key] = now
                    alert = IncidentAlert(
                        alert_id=f"ALT-{self.alert_counter:05d}",
                        incident_type="WRONG_WAY",
                        severity="CRITICAL",
                        timestamp=now,
                        description=(
                            f"Wrong-way driver detected! Vehicle #{vehicle.track_id} ({vehicle.class_name}) "
                            f"opposing traffic in {lane_zone.name} (Angle: {angle_deg:.1f}°)"
                        ),
                        location=track.center,
                        involved_track_ids=[vehicle.track_id],
                        zone_id=lane_zone.zone_id,
                        metadata={
                            "speed_px": round(speed, 2),
                            "deviation_angle": round(angle_deg, 1),
                            "vehicle_class": vehicle.class_name,
                        },
                    )
                    self.alert_counter += 1
                    return alert
        else:
            self.wrong_way_sustained_frames[vehicle.track_id] = 0

        return None

    def _check_stalled_vehicle(
        self,
        vehicle: Detection,
        tracker: SpatialTracker,
        zone_manager: ZoneManager,
        fps: float,
        now: float,
    ) -> Optional[IncidentAlert]:
        """Detects stationary or stalled vehicles blocking active traffic lanes."""
        if not vehicle.track_id:
            return None

        track = tracker.get_track(vehicle.track_id)
        if not track:
            return None

        # Check if inside active lane
        zones = zone_manager.get_zones_for_point(track.center)
        lane_zone = next((z for z in zones if z.zone_type == "lane"), None)
        if not lane_zone:
            self.stationary_track_frames[vehicle.track_id] = 0
            return None

        # Check speed
        speed = math.hypot(track.velocity[0], track.velocity[1])
        max_drift = self.incidents_cfg.get("stalled_vehicle", {}).get("max_drift_px", 1.8)

        if speed < max_drift:
            self.stationary_track_frames[vehicle.track_id] += 1
            threshold_frames = int(self.incidents_cfg.get("stalled_vehicle", {}).get("duration_seconds", 3.0) * fps)

            if self.stationary_track_frames[vehicle.track_id] >= threshold_frames:
                key = f"stalled_{vehicle.track_id}"
                if now - self.last_alert_time.get(key, 0) > self.suppression_cooldown_sec:
                    self.last_alert_time[key] = now
                    stalled_duration_sec = self.stationary_track_frames[vehicle.track_id] / fps
                    alert = IncidentAlert(
                        alert_id=f"ALT-{self.alert_counter:05d}",
                        incident_type="STALLED_VEHICLE",
                        severity="WARNING",
                        timestamp=now,
                        description=(
                            f"Stalled vehicle lane obstruction: Vehicle #{vehicle.track_id} stationary for "
                            f"{stalled_duration_sec:.1f}s in {lane_zone.name}"
                        ),
                        location=track.center,
                        involved_track_ids=[vehicle.track_id],
                        zone_id=lane_zone.zone_id,
                        metadata={
                            "stalled_duration_seconds": round(stalled_duration_sec, 1),
                            "vehicle_class": vehicle.class_name,
                        },
                    )
                    self.alert_counter += 1
                    return alert
        else:
            self.stationary_track_frames[vehicle.track_id] = 0

        return None

    def _check_collisions(
        self,
        vehicles: List[Detection],
        tracker: SpatialTracker,
        now: float,
    ) -> List[IncidentAlert]:
        """Detects abnormal vehicle box collisions / crashes."""
        alerts: List[IncidentAlert] = []
        iou_thresh = self.incidents_cfg.get("collision", {}).get("overlap_iou_threshold", 0.12)

        for i in range(len(vehicles)):
            for j in range(i + 1, len(vehicles)):
                v1, v2 = vehicles[i], vehicles[j]
                if not v1.track_id or not v2.track_id:
                    continue

                iou = compute_iou(v1.bbox, v2.bbox)
                pair_key = (min(v1.track_id, v2.track_id), max(v1.track_id, v2.track_id))

                if iou >= iou_thresh:
                    self.collision_pairs_frames[pair_key] += 1
                    if self.collision_pairs_frames[pair_key] >= 5:
                        sup_key = f"collision_{pair_key[0]}_{pair_key[1]}"
                        if now - self.last_alert_time.get(sup_key, 0) > self.suppression_cooldown_sec:
                            self.last_alert_time[sup_key] = now
                            collision_center = (
                                (v1.center[0] + v2.center[0]) / 2.0,
                                (v1.center[1] + v2.center[1]) / 2.0,
                            )
                            alert = IncidentAlert(
                                alert_id=f"ALT-{self.alert_counter:05d}",
                                incident_type="COLLISION",
                                severity="CRITICAL",
                                timestamp=now,
                                description=(
                                    f"CRITICAL: Traffic accident/collision detected between Vehicle #{v1.track_id} "
                                    f"({v1.class_name}) and Vehicle #{v2.track_id} ({v2.class_name})! (IoU: {iou:.2f})"
                                ),
                                location=collision_center,
                                involved_track_ids=[v1.track_id, v2.track_id],
                                metadata={"iou": round(iou, 3), "vehicles": [v1.class_name, v2.class_name]},
                            )
                            self.alert_counter += 1
                            alerts.append(alert)
                else:
                    self.collision_pairs_frames[pair_key] = max(0, self.collision_pairs_frames[pair_key] - 1)

        return alerts

    def _check_pedestrian_hazards(
        self,
        pedestrians: List[Detection],
        vehicles: List[Detection],
        tracker: SpatialTracker,
        zone_manager: ZoneManager,
        now: float,
    ) -> List[IncidentAlert]:
        """Identifies jaywalking and high-risk near-miss proximity incidents."""
        alerts: List[IncidentAlert] = []
        prox_critical = self.incidents_cfg.get("pedestrian_danger", {}).get("proximity_critical_px", 60.0)

        for ped in pedestrians:
            ped_center = ped.center
            zones = zone_manager.get_zones_for_point(ped_center)
            in_crosswalk = any(z.zone_type == "crosswalk" for z in zones)
            in_active_lane = any(z.zone_type == "lane" for z in zones)

            # Check Near-Miss proximity with moving vehicles
            for veh in vehicles:
                dist = math.hypot(ped_center[0] - veh.center[0], ped_center[1] - veh.center[1])
                veh_track = tracker.get_track(veh.track_id) if veh.track_id else None
                veh_speed = veh_track.speed if veh_track else 0.0

                if dist < prox_critical and veh_speed > 2.0:
                    sup_key = f"near_miss_{ped.track_id}_{veh.track_id}"
                    if now - self.last_alert_time.get(sup_key, 0) > self.suppression_cooldown_sec:
                        self.last_alert_time[sup_key] = now
                        alert = IncidentAlert(
                            alert_id=f"ALT-{self.alert_counter:05d}",
                            incident_type="PEDESTRIAN_HAZARD",
                            severity="CRITICAL",
                            timestamp=now,
                            description=(
                                f"CRITICAL: Pedestrian near-miss! Pedestrian #{ped.track_id or '?'} in direct path "
                                f"of Vehicle #{veh.track_id} (Distance: {dist:.1f}px)"
                            ),
                            location=ped_center,
                            involved_track_ids=[x for x in [ped.track_id, veh.track_id] if x is not None],
                            metadata={"distance_px": round(dist, 1), "vehicle_speed_px": round(veh_speed, 2)},
                        )
                        self.alert_counter += 1
                        alerts.append(alert)

            # Check Jaywalking (pedestrian walking on active traffic lane outside crosswalk)
            if in_active_lane and not in_crosswalk:
                sup_key = f"jaywalk_{ped.track_id}"
                if now - self.last_alert_time.get(sup_key, 0) > self.suppression_cooldown_sec * 2:
                    self.last_alert_time[sup_key] = now
                    alert = IncidentAlert(
                        alert_id=f"ALT-{self.alert_counter:05d}",
                        incident_type="PEDESTRIAN_HAZARD",
                        severity="WARNING",
                        timestamp=now,
                        description=(
                            f"Hazardous Jaywalking: Pedestrian #{ped.track_id or '?'} walking inside active traffic lane "
                            f"outside designated crosswalk!"
                        ),
                        location=ped_center,
                        involved_track_ids=[ped.track_id] if ped.track_id else [],
                        metadata={"in_lane": True, "in_crosswalk": False},
                    )
                    self.alert_counter += 1
                    alerts.append(alert)

        return alerts

    def _check_emergency_corridor(
        self,
        ev: Detection,
        tracker: SpatialTracker,
        zone_manager: ZoneManager,
        now: float,
    ) -> Optional[IncidentAlert]:
        """Detects emergency vehicles and raises green-wave corridor alert."""
        sup_key = f"emergency_{ev.track_id}"
        if now - self.last_alert_time.get(sup_key, 0) > self.suppression_cooldown_sec * 3:
            self.last_alert_time[sup_key] = now
            alert = IncidentAlert(
                alert_id=f"ALT-{self.alert_counter:05d}",
                incident_type="EMERGENCY_CORRIDOR",
                severity="INFO",
                timestamp=now,
                description=f"Emergency Vehicle Detected ({ev.class_name}) - Activating Green-Wave priority corridor!",
                location=ev.center,
                involved_track_ids=[ev.track_id] if ev.track_id else [],
                metadata={"class_name": ev.class_name, "priority": "EMERGENCY_DISPATCH"},
            )
            self.alert_counter += 1
            return alert
        return None
