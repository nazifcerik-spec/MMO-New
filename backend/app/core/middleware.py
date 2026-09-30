"""Pure-ASGI middlewares: correlation id + access log, security headers."""

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import correlation_id_var

log = logging.getLogger("app.request")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
HEADER = "X-Correlation-ID"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = ""
        for name, value in scope.get("headers", []):
            if name == b"x-correlation-id":
                incoming = value.decode("latin-1")
                break
        cid = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        # Deliberately not reset: the outer error handler must still see the id.
        correlation_id_var.set(cid)
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers[HEADER] = cid
                for key, val in SECURITY_HEADERS.items():
                    if key not in headers:
                        headers[key] = val
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            log.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status,
                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
