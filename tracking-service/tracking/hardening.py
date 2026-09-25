from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestGuard:
    """Rejects CL+TE requests (h11 lets them through) and oversized headers."""

    def __init__(self, app: ASGIApp, *, max_header_bytes: int) -> None:
        self.app = app
        self.max_header_bytes = max_header_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        total = 0
        has_length = has_encoding = False
        for name, value in scope["headers"]:
            total += len(name) + len(value)
            if name == b"content-length":
                has_length = True
            elif name == b"transfer-encoding":
                has_encoding = True
        if has_length and has_encoding:
            await _refuse(400, "ambiguous message framing", scope, receive, send)
        elif total > self.max_header_bytes:
            await _refuse(431, "request headers too large", scope, receive, send)
        else:
            await self.app(scope, receive, send)


async def _refuse(status: int, detail: str, scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse({"detail": detail}, status_code=status, headers={"connection": "close"})
    await response(scope, receive, send)
