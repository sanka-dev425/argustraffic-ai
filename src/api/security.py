"""
ArgusTraffic AI - Enterprise Zero-Trust Cybersecurity Layer
Provides security headers, rate limiting, timing-safe API key verification,
and strict input sanitization.
"""

from collections import defaultdict
import hmac
import logging
import os
import time
from typing import Callable, Optional

from fastapi import HTTPException, Request, Response, Security
from fastapi.security.api_key import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("argustraffic.security")

# Configurable API Key (Default can be empty for local development, or set via ARGUS_API_KEY env)
API_KEY_ENV = os.getenv("ARGUS_API_KEY", "")
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects defense-grade HTTP security headers on all responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class RateLimiter:
    """Sliding-window IP rate limiter to mitigate brute-force and DoS attacks."""

    def __init__(self, requests_per_minute: int = 120):
        self.rpm = requests_per_minute
        self.requests = defaultdict(list)

    def is_allowed(self, client_ip: str) -> bool:
        now = time.time()
        window_start = now - 60.0
        # Prune old timestamps
        self.requests[client_ip] = [t for t in self.requests[client_ip] if t > window_start]
        if len(self.requests[client_ip]) >= self.rpm:
            return False
        self.requests[client_ip].append(now)
        return True


rate_limiter = RateLimiter(requests_per_minute=180)


async def verify_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)) -> Optional[str]:
    """
    Enforces timing-safe API key validation if ARGUS_API_KEY environment variable is configured.
    If no key is configured in the environment, anonymous local access is permitted.
    """
    expected_key = os.getenv("ARGUS_API_KEY", "").strip()
    if not expected_key:
        return None  # Development mode: auth optional

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Missing X-API-Key header in request.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Timing-safe constant-time string comparison against side-channel attacks
    if not hmac.compare_digest(api_key.encode("utf-8"), expected_key.encode("utf-8")):
        logger.warning("Failed API Key authentication attempt.")
        raise HTTPException(status_code=403, detail="Forbidden: Invalid credentials.")

    return api_key


def sanitize_polygon(points: list) -> list:
    """
    Validates geometric polygon coordinate boundaries to prevent
    buffer overflows or malicious coordinate injection.
    """
    if not isinstance(points, list) or len(points) < 3:
        raise HTTPException(status_code=400, detail="Polygon must contain at least 3 coordinate pairs.")
    if len(points) > 50:
        raise HTTPException(status_code=400, detail="Polygon cannot exceed 50 vertices.")

    sanitized = []
    for pt in points:
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            raise HTTPException(status_code=400, detail="Each vertex must be an (x, y) coordinate pair.")
        try:
            x, y = float(pt[0]), float(pt[1])
            # Check coordinate limits (e.g. within 16k resolution)
            if not (-1000 <= x <= 16000 and -1000 <= y <= 16000):
                raise HTTPException(status_code=400, detail=f"Coordinate ({x}, {y}) out of realistic visual bounds.")
            sanitized.append((x, y))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Coordinate values must be valid real numbers.")
    return sanitized
