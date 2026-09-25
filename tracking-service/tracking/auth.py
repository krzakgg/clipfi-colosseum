import hmac

from fastapi import HTTPException, Request, status
from starlette._utils import get_route_path
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def token_matches(authorization: str, expected: bytes) -> bool:
    scheme, _, token = authorization.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(token.strip().encode(), expected)


async def require_service_token(request: Request) -> None:
    if not token_matches(request.headers.get("authorization", ""), request.app.state.service_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid service token",
            headers={"WWW-Authenticate": "Bearer"},
        )


class InternalGate:
    """Token check and body size cap for /internal.

    FastAPI parses the body before running dependencies, so the token has to be
    checked here, before anything is read.
    """

    def __init__(self, app: ASGIApp, *, token: bytes, max_body: int, prefix: str = "/internal") -> None:
        self.app = app
        self.token = token
        self.max_body = max_body
        self.prefix = prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # same path the router matches on (root_path stripped)
        path = get_route_path(scope)
        if not (path == self.prefix or path.startswith(self.prefix + "/")):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not token_matches(headers.get("authorization", ""), self.token):
            response = JSONResponse(
                {"detail": "invalid service token"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
            )
            await response(scope, receive, send)
            return

        declared = headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.max_body):
            await _too_large(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if len(body) > self.max_body:
                await _too_large(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
    await JSONResponse({"detail": "request body too large"}, status_code=413)(scope, receive, send)
