import logging
from typing import Union
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.exceptions import BaseCustomException

logger = logging.getLogger(__name__)


async def custom_http_exception_handler(request: Request, exc: BaseCustomException) -> JSONResponse:
    """커스텀 HTTP 예외 처리"""
    error_response = {
        "success": False,
        "error": {
            "message": exc.detail,
            "code": exc.error_code,
            "status": exc.status_code
        },
        "timestamp": None,
        "path": request.url.path,
        "method": request.method
    }
    
    # 세부 정보가 있으면 추가
    if exc.details:
        error_response["error"]["details"] = exc.details
    
    # 로깅 - 민감한 정보는 제외
    logger.error(
        f"Custom Exception: {exc.__class__.__name__} - {exc.error_code} - "
        f"Status: {exc.status_code} - Path: {request.url.path} - Method: {request.method}",
        extra={
            "exception_type": exc.__class__.__name__,
            "error_code": exc.error_code,
            "status_code": exc.status_code,
            "path": request.url.path,
            "method": request.method
        }
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response,
        headers=exc.headers
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """일반 HTTP 예외 처리"""
    error_response = {
        "success": False,
        "error": {
            "message": exc.detail,
            "code": "HTTP_EXCEPTION",
            "status": exc.status_code
        },
        "timestamp": None,
        "path": request.url.path,
        "method": request.method
    }
    
    logger.error(
        f"HTTP Exception: {exc.status_code} - Path: {request.url.path} - Method: {request.method}",
        extra={
            "status_code": exc.status_code,
            "path": request.url.path,
            "method": request.method
        }
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """유효성 검사 예외 처리"""
    error_details = []
    for error in exc.errors():
        field_path = " -> ".join(str(loc) for loc in error["loc"])
        error_details.append({
            "field": field_path,
            "message": error["msg"],
            "type": error["type"],
            "input": error.get("input")
        })
    
    error_response = {
        "success": False,
        "error": {
            "message": "입력값 검증에 실패했습니다",
            "code": "VALIDATION_ERROR",
            "status": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "details": error_details
        },
        "timestamp": None,
        "path": request.url.path,
        "method": request.method
    }
    
    logger.error(
        f"Validation Exception: {len(error_details)} field(s) - Path: {request.url.path}",
        extra={
            "validation_errors": error_details,
            "path": request.url.path,
            "method": request.method
        }
    )
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_response
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """일반 예외 처리 (예상하지 못한 오류)"""
    error_response = {
        "success": False,
        "error": {
            "message": "서버 내부 오류가 발생했습니다",
            "code": "INTERNAL_SERVER_ERROR",
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR
        },
        "timestamp": None,
        "path": request.url.path,
        "method": request.method
    }
    
    logger.error(
        f"Unexpected Exception: {type(exc).__name__} - {str(exc)} - "
        f"Path: {request.url.path} - Method: {request.method}",
        exc_info=True,
        extra={
            "exception_type": type(exc).__name__,
            "path": request.url.path,
            "method": request.method
        }
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response
    )