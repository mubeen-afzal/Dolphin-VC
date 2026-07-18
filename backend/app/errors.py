from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        field_errors: list[dict[str, str]] | None = None,
        retryable: bool = False,
        retry_after_s: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.field_errors = field_errors or []
        self.retryable = retryable
        self.retry_after_s = retry_after_s


class NotFoundError(AppError):
    def __init__(self, resource: str = "Resource") -> None:
        super().__init__("NOT_FOUND", f"{resource} was not found.", status_code=404)


class ConflictError(AppError):
    def __init__(self, message: str, code: str = "CONFLICT") -> None:
        super().__init__(code, message, status_code=409)


class ForbiddenError(AppError):
    def __init__(self, message: str = "You do not have permission to perform this action.") -> None:
        super().__init__("FORBIDDEN", message, status_code=403)


class UnauthenticatedError(AppError):
    def __init__(
        self, code: str = "UNAUTHENTICATED", message: str = "Authentication required."
    ) -> None:
        super().__init__(code, message, status_code=401)


def error_payload(request: Request, error: AppError) -> dict[str, Any]:
    request_id = getattr(request.state, "request_id", "unknown")
    return {
        "error": {
            "code": error.code,
            "message": error.message,
            "field_errors": error.field_errors,
            "details": error.details,
            "retryable": error.retryable,
            "retry_after_s": error.retry_after_s,
            "request_id": request_id,
            "docs": f"https://docs.vcbrain.local/errors#{error.code}",
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, error: AppError) -> JSONResponse:
        headers: dict[str, str] = {}
        if error.retry_after_s is not None:
            headers["Retry-After"] = str(error.retry_after_s)
        return JSONResponse(
            status_code=error.status_code,
            content=error_payload(request, error),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, error: RequestValidationError) -> JSONResponse:
        field_errors = []
        for item in error.errors():
            loc = [str(part) for part in item.get("loc", ()) if part not in {"body", "query"}]
            field_errors.append(
                {
                    "field": ".".join(loc) or "request",
                    "code": str(item.get("type", "invalid")),
                    "message": str(item.get("msg", "Invalid value")),
                }
            )
        app_error = AppError(
            "VALIDATION_ERROR",
            "The request is invalid.",
            status_code=400,
            field_errors=field_errors,
        )
        return JSONResponse(status_code=400, content=error_payload(request, app_error))

    @app.exception_handler(IntegrityError)
    async def handle_integrity(request: Request, _error: IntegrityError) -> JSONResponse:
        app_error = ConflictError("The request conflicts with an existing resource.")
        return JSONResponse(status_code=409, content=error_payload(request, app_error))
