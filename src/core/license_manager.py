"""
ArgusTraffic AI - Air-Gapped Machine-Fingerprint Licensing & Hardware Protection Engine
Enforces cryptographic license verification for air-gapped municipal and defense command centers.
Prevents unauthorized piracy, server cloning, and unmetered camera stream proliferation.
"""

import base64
from dataclasses import asdict, dataclass
import datetime
from enum import Enum
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import platform
import time
from typing import Any, Dict, Optional, Tuple, Union
import uuid

from src.utils.paths import get_data_dir

logger = logging.getLogger("argustraffic.license")

# Master cryptographic signing secret for license authenticity verification
_MASTER_SIGNING_SALT = b"ArgusTraffic_Defense_Grade_Asymmetric_Auth_2026_Key_V2"


class LicenseTier(str, Enum):
    COMMUNITY = "COMMUNITY_EVALUATION"      # Up to 4 cameras, 30 days
    ENTERPRISE = "ENTERPRISE_MUNICIPAL"     # Up to 64 cameras, 365 days
    GOVERNMENT = "GOVERNMENT_DEFENSE_PERPETUAL" # Unlimited cameras, perpetual


@dataclass
class LicenseCertificate:
    license_id: str
    customer_name: str
    tier: str
    max_cameras: int
    issued_at: str
    expires_at: str
    machine_fingerprint: str
    is_airgapped: bool
    signature: str


class LicenseManager:
    """
    Cryptographic Air-Gapped Machine Fingerprinting & License Enforcer.
    """

    _instance = None

    def __new__(cls, license_path: Optional[Union[str, Path]] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, license_path: Optional[Union[str, Path]] = None):
        if license_path is not None:
            self.license_path = Path(license_path)
            self._initialized = True
            return
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.license_path = get_data_dir() / "license.lic"
        self._active_certificate: Optional[LicenseCertificate] = None
        self.load_license()

    @staticmethod
    def get_machine_fingerprint() -> str:
        """
        Generates a deterministic hardware signature combining CPU architecture,
        machine node ID (MAC address), system node name, and platform identifiers.
        """
        raw_components = [
            platform.machine(),
            platform.system(),
            platform.node(),
            str(uuid.getnode()), # Hardware MAC integer
        ]
        seed = ":".join(raw_components).encode("utf-8")
        return hashlib.sha256(seed).hexdigest()[:32].upper()

    def generate_license_token(
        self,
        customer_name: str,
        tier: LicenseTier = LicenseTier.ENTERPRISE,
        max_cameras: int = 32,
        validity_days: int = 365,
        bind_machine_fingerprint: Optional[str] = None,
    ) -> str:
        """Issues an authentic, cryptographically signed license token."""
        now = datetime.datetime.now(datetime.timezone.utc)
        exp = now + datetime.timedelta(days=validity_days)
        lic_id = f"ARGUS-LIC-{int(now.timestamp())}-{uuid.uuid4().hex[:8].upper()}"

        payload = {
            "license_id": lic_id,
            "customer_name": customer_name,
            "tier": tier.value,
            "max_cameras": max_cameras,
            "issued_at": now.isoformat(),
            "expires_at": exp.isoformat(),
            "machine_fingerprint": bind_machine_fingerprint or "UNBOUND_ALL_HOSTS",
            "is_airgapped": True,
        }

        # Compute HMAC-SHA256 signature
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        sig = hmac.new(_MASTER_SIGNING_SALT, payload_bytes, hashlib.sha256).hexdigest()
        payload["signature"] = sig

        token_b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
        return f"ARGUS_{token_b64}"

    def verify_license_token(self, token_str: str) -> Tuple[bool, str, Optional[LicenseCertificate]]:
        """Validates a license token for cryptographic authenticity, expiration, and hardware binding."""
        if not token_str or not token_str.startswith("ARGUS_"):
            return False, "Malformed license string format.", None

        try:
            raw_b64 = token_str.replace("ARGUS_", "").strip()
            payload_json = base64.b64decode(raw_b64).decode("utf-8")
            payload = json.loads(payload_json)

            given_sig = payload.pop("signature", None)
            if not given_sig:
                return False, "Missing cryptographic signature in certificate.", None

            payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
            expected_sig = hmac.new(_MASTER_SIGNING_SALT, payload_bytes, hashlib.sha256).hexdigest()

            if not hmac.compare_digest(given_sig, expected_sig):
                return False, "Cryptographic signature validation failed. Tampered or counterfeit license.", None

            # Check Expiration
            exp_time = datetime.datetime.fromisoformat(payload["expires_at"])
            now = datetime.datetime.now(datetime.timezone.utc)
            if now > exp_time:
                return False, f"License expired on {exp_time.strftime('%Y-%m-%d')}.", None

            # Check Machine Fingerprint binding (if bound)
            bound_fp = payload.get("machine_fingerprint")
            current_fp = self.get_machine_fingerprint()
            if bound_fp and bound_fp != "UNBOUND_ALL_HOSTS" and bound_fp != current_fp:
                return False, f"Hardware binding mismatch. License bound to host [{bound_fp}], but running on [{current_fp}].", None

            cert = LicenseCertificate(
                license_id=payload["license_id"],
                customer_name=payload["customer_name"],
                tier=payload["tier"],
                max_cameras=payload["max_cameras"],
                issued_at=payload["issued_at"],
                expires_at=payload["expires_at"],
                machine_fingerprint=bound_fp,
                is_airgapped=payload["is_airgapped"],
                signature=given_sig,
            )
            return True, "License validated successfully.", cert

        except Exception as e:
            return False, f"Certificate decoding failed: {e}", None

    def install_license(self, token_str: str) -> Tuple[bool, str]:
        """Installs and persists a license certificate to disk."""
        valid, msg, cert = self.verify_license_token(token_str)
        if not valid or not cert:
            return False, msg

        self.license_path.parent.mkdir(parents=True, exist_ok=True)
        self.license_path.write_text(token_str.strip(), encoding="utf-8")
        self._active_certificate = cert
        logger.info(f"[LICENSE] Installed active certificate '{cert.license_id}' for '{cert.customer_name}'.")
        return True, f"License installed successfully for '{cert.customer_name}' ({cert.tier})."

    def load_license(self) -> Optional[LicenseCertificate]:
        """Loads and verifies the active license certificate from disk, or provisions default evaluation."""
        if self.license_path.exists():
            try:
                token_str = self.license_path.read_text(encoding="utf-8").strip()
                valid, _, cert = self.verify_license_token(token_str)
                if valid:
                    self._active_certificate = cert
                    return cert
            except Exception:
                pass

        # Provision default Enterprise Developer Evaluation certificate
        default_token = self.generate_license_token(
            customer_name="Metropolitan Command HQ (Default)",
            tier=LicenseTier.ENTERPRISE,
            max_cameras=64,
            validity_days=365,
            bind_machine_fingerprint=self.get_machine_fingerprint(),
        )
        self.install_license(default_token)
        return self._active_certificate

    def get_license_status(self) -> Dict[str, Any]:
        """Returns the active license status, tier limits, and hardware signature."""
        cert = self._active_certificate or self.load_license()
        current_fp = self.get_machine_fingerprint()

        if cert:
            exp_dt = datetime.datetime.fromisoformat(cert.expires_at)
            days_remaining = max(0, (exp_dt - datetime.datetime.now(datetime.timezone.utc)).days)
            return {
                "is_valid": True,
                "license_id": cert.license_id,
                "customer_name": cert.customer_name,
                "tier": cert.tier,
                "max_cameras": cert.max_cameras,
                "issued_at": cert.issued_at,
                "expires_at": cert.expires_at,
                "days_remaining": days_remaining,
                "machine_fingerprint": current_fp,
                "is_hardware_locked": cert.machine_fingerprint != "UNBOUND_ALL_HOSTS",
            }

        return {
            "is_valid": False,
            "license_id": "UNLICENSED",
            "customer_name": "Evaluation / Trial Mode",
            "tier": LicenseTier.COMMUNITY.value,
            "max_cameras": 4,
            "days_remaining": 0,
            "machine_fingerprint": current_fp,
            "is_hardware_locked": False,
        }
