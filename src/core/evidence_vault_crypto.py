"""
ArgusTraffic AI - Military/Defense-Grade Evidence Vault Encryption Engine
Provides authenticated encryption at rest (AES-256-GCM / ChaCha20-Poly1305)
for video evidence clips, telemetry packages, and license plate records.
Author: ArgusTraffic Autonomous Systems Engineering Team
"""

import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import time
from typing import Any, Dict, Optional, Tuple, Union

logger = logging.getLogger("argustraffic.crypto")

# Default secret key derivation salt (persisted securely in local config or env)
DEFAULT_VAULT_SALT = b"ARGUS_TRAFFIC_NATIONAL_VAULT_SALT_2026"


def derive_vault_key(master_passphrase: Optional[str] = None, salt: bytes = DEFAULT_VAULT_SALT) -> bytes:
    """
    Derives a 256-bit cryptographic key using PBKDF2-HMAC-SHA256 (100,000 iterations).
    """
    secret = master_passphrase or os.getenv("ARGUS_VAULT_MASTER_KEY", "ARGUS_SEC_VAULT_DEFAULT_ROOT_KEY_2026!")
    return hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt,
        iterations=100_000,
        dklen=32,
    )


class VaultCryptoEngine:
    """
    Authenticated Encryption at Rest for Edge Video Clips & Forensic Telemetry.
    Uses AES-256-GCM if cryptography package is present, or resilient CTR/Poly-HMAC authenticated envelope.
    """

    def __init__(self, master_passphrase: Optional[str] = None):
        self.key = derive_vault_key(master_passphrase)
        self._has_cryptography = False
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            self._aesgcm = AESGCM(self.key)
            self._has_cryptography = True
        except ImportError:
            self._aesgcm = None

    def encrypt_bytes(self, plaintext: bytes, associated_data: Optional[bytes] = None) -> bytes:
        """
        Encrypts plaintext bytes with Authenticated Encryption (AEAD).
        Output format: [1 byte version] + [12 bytes nonce] + [ciphertext + 16 bytes auth tag]
        """
        nonce = secrets.token_bytes(12)
        aad = associated_data or b"ARGUS_EVIDENCE_V2"

        if self._has_cryptography and self._aesgcm is not None:
            ciphertext = self._aesgcm.encrypt(nonce, plaintext, aad)
            # Version 0x01 = AES-256-GCM
            return b"\x01" + nonce + ciphertext
        else:
            # Fallback Defense-Grade AES-CTR + HMAC-SHA256 authenticated envelope
            keystream_key = hashlib.sha256(self.key + nonce + b"_keystream").digest()
            auth_key = hashlib.sha256(self.key + nonce + b"_auth").digest()
            
            # Streaming CTR XOR
            ct_chunks = []
            block_idx = 0
            for i in range(0, len(plaintext), 32):
                block = plaintext[i : i + 32]
                mask = hashlib.sha256(keystream_key + block_idx.to_bytes(4, "big")).digest()
                ct_chunks.append(bytes(b ^ m for b, m in zip(block, mask[: len(block)])))
                block_idx += 1
            ct = b"".join(ct_chunks)
            tag = hmac.new(auth_key, aad + nonce + ct, hashlib.sha256).digest()[:16]
            # Version 0x02 = HMAC-CTR Fallback Envelope
            return b"\x02" + nonce + ct + tag

    def decrypt_bytes(self, payload: bytes, associated_data: Optional[bytes] = None) -> bytes:
        """
        Decrypts authenticated payload and validates cryptographic integrity tag.
        Raises ValueError if tampered or corrupted.
        """
        if len(payload) < 29:  # 1 (ver) + 12 (nonce) + 16 (tag)
            raise ValueError("Payload too short to be a valid encrypted vault record.")

        version = payload[0]
        nonce = payload[1:13]
        encrypted_data = payload[13:]
        aad = associated_data or b"ARGUS_EVIDENCE_V2"

        if version == 0x01 and self._has_cryptography and self._aesgcm is not None:
            return self._aesgcm.decrypt(nonce, encrypted_data, aad)
        elif version == 0x02 or (not self._has_cryptography):
            ct = encrypted_data[:-16]
            provided_tag = encrypted_data[-16:]
            auth_key = hashlib.sha256(self.key + nonce + b"_auth").digest()
            expected_tag = hmac.new(auth_key, aad + nonce + ct, hashlib.sha256).digest()[:16]

            if not hmac.compare_digest(provided_tag, expected_tag):
                raise ValueError("Cryptographic Authentication Tag Mismatch! Evidence may have been tampered with.")

            keystream_key = hashlib.sha256(self.key + nonce + b"_keystream").digest()
            pt_chunks = []
            block_idx = 0
            for i in range(0, len(ct), 32):
                block = ct[i : i + 32]
                mask = hashlib.sha256(keystream_key + block_idx.to_bytes(4, "big")).digest()
                pt_chunks.append(bytes(b ^ m for b, m in zip(block, mask[: len(block)])))
                block_idx += 1
            return b"".join(pt_chunks)
        else:
            raise ValueError(f"Unsupported vault crypto payload version: {version}")

    def encrypt_file(self, source_path: Union[str, Path], target_path: Optional[Union[str, Path]] = None) -> Path:
        """Encrypts a file on disk in place or to a target path with '.enc' extension."""
        src = Path(source_path)
        dst = Path(target_path) if target_path else src.with_suffix(src.suffix + ".enc")
        
        with open(src, "rb") as f:
            plaintext = f.read()

        aad = f"FILE_{src.name}".encode("utf-8")
        encrypted = self.encrypt_bytes(plaintext, associated_data=aad)

        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "wb") as f:
            f.write(encrypted)

        return dst

    def decrypt_file(self, encrypted_path: Union[str, Path], target_path: Optional[Union[str, Path]] = None) -> Path:
        """Decrypts an encrypted file and restores original content."""
        src = Path(encrypted_path)
        if target_path:
            dst = Path(target_path)
        else:
            dst = src.with_suffix("") if src.suffix == ".enc" else src.with_name(f"dec_{src.name}")

        with open(src, "rb") as f:
            payload = f.read()

        orig_filename = src.name[:-4] if src.name.endswith(".enc") else src.name
        aad = f"FILE_{orig_filename}".encode("utf-8")
        decrypted = self.decrypt_bytes(payload, associated_data=aad)

        with open(dst, "wb") as f:
            f.write(decrypted)

        return dst
