import asyncio
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware

from app.errors import AppError, error_payload

logger = structlog.get_logger()
REQUEST_COUNT = Counter(
    "http_requests_total",
    "HTTP requests",
    ("route", "method", "status"),
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ("route",),
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        request.state.request_id = request_id
        content_length = int(request.headers.get("content-length", "0") or 0)
        content_type = request.headers.get("content-type", "")
        maximum = (
            request.app.state.settings.max_upload_mb * 1024 * 1024
            if "multipart/form-data" in content_type
            else 1024 * 1024
        )
        if content_length > maximum:
            error = AppError(
                "MAX_BODY_EXCEEDED",
                "Request body exceeds the configured limit.",
                status_code=413,
                details={"max_bytes": maximum},
            )
            return Response(
                content=__import__("json").dumps(error_payload(request, error)),
                status_code=413,
                media_type="application/json",
                headers={"X-Request-Id": request_id},
            )
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        REQUEST_COUNT.labels(route_path, request.method, str(response.status_code)).inc()
        REQUEST_LATENCY.labels(route_path).observe(elapsed)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.app.state.settings.env == "prod":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        await logger.ainfo(
            "request.completed",
            request_id=request_id,
            route=route_path,
            method=request.method,
            status=response.status_code,
            latency_ms=round(elapsed * 1000, 2),
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Process-local fallback limiter; Redis-backed limits can replace this at the proxy layer."""

    def __init__(self, app: object) -> None:
        super().__init__(app)
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self.lock = asyncio.Lock()

    @staticmethod
    def rule(request: Request) -> tuple[int, int]:
        path = request.url.path
        if path.endswith("/healthz") or path.endswith("/readyz") or path.endswith("/metrics"):
            return 600, 60
        if "/auth/login" in path or "/auth/password/" in path:
            return 10, 900
        if "/public/apply" in path and request.method == "POST":
            return 5, 3600
        if "/search/" in path:
            return 60, 60
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            return 60, 60
        return 300, 60

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        limit, window = self.rule(request)
        if request.app.state.settings.env in {"dev", "test", "demo"}:
            limit *= 10
        client = request.client.host if request.client else "unknown"
        key = f"{client}:{request.method}:{request.url.path}"
        now = time.monotonic()
        async with self.lock:
            bucket = self.events[key]
            while bucket and bucket[0] <= now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, round(window - (now - bucket[0])))
                request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
                error = AppError(
                    "RATE_LIMITED",
                    "Rate limit exceeded.",
                    status_code=429,
                    retryable=True,
                    retry_after_s=retry_after,
                )
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=429,
                    content=error_payload(request, error),
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(retry_after),
                        "X-Request-Id": request_id,
                    },
                )
            bucket.append(now)
            remaining = limit - len(bucket)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(window)
        return response
