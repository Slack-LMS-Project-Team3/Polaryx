from fastapi import HTTPException, status
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class BaseCustomException(HTTPException):
    """모든 커스텀 예외의 기본 클래스"""
    
    def __init__(
        self,
        status_code: int,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ):
        self.error_code = error_code
        self.details = details or {}
        
        super().__init__(
            status_code=status_code, 
            detail=message, 
            headers=headers
        )


# === Authentication & Authorization ===
class AuthenticationError(BaseCustomException):
    def __init__(self, message: str = "인증에 실패했습니다", error_code: str = "AUTH_FAILED"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=message,
            error_code=error_code
        )


class TokenExpiredError(AuthenticationError):
    def __init__(self, message: str = "토큰이 만료되었습니다"):
        super().__init__(message=message, error_code="TOKEN_EXPIRED")


class InvalidTokenError(AuthenticationError):
    def __init__(self, message: str = "유효하지 않은 토큰입니다"):
        super().__init__(message=message, error_code="INVALID_TOKEN")


class PermissionDeniedError(BaseCustomException):
    def __init__(self, message: str = "권한이 없습니다", resource: str = None):
        details = {"resource": resource} if resource else {}
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            message=message,
            error_code="PERMISSION_DENIED",
            details=details
        )


# === Resource Errors ===
class ResourceNotFoundError(BaseCustomException):
    def __init__(self, resource: str, identifier: str = None):
        message = f"{resource}을(를) 찾을 수 없습니다"
        if identifier:
            message += f" (ID: {identifier})"
            
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            message=message,
            error_code="RESOURCE_NOT_FOUND",
            details={"resource": resource, "identifier": identifier}
        )


class ResourceConflictError(BaseCustomException):
    def __init__(self, message: str, resource: str = None):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            message=message,
            error_code="RESOURCE_CONFLICT",
            details={"resource": resource} if resource else {}
        )


# === Validation Errors ===
class ValidationError(BaseCustomException):
    def __init__(self, message: str, field: str = None, value: Any = None):
        details = {}
        if field:
            details["field"] = field
        if value is not None:
            details["provided_value"] = str(value)
            
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=message,
            error_code="VALIDATION_ERROR",
            details=details
        )


class RequiredFieldError(ValidationError):
    def __init__(self, field: str):
        super().__init__(
            message=f"필수 필드가 누락되었습니다: {field}",
            field=field
        )


class InvalidFormatError(ValidationError):
    def __init__(self, field: str, expected_format: str):
        super().__init__(
            message=f"잘못된 형식입니다: {field} (예상 형식: {expected_format})",
            field=field
        )


# === Business Logic Errors ===
class BusinessLogicError(BaseCustomException):
    def __init__(self, message: str, error_code: str = "BUSINESS_LOGIC_ERROR"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=message,
            error_code=error_code
        )


class OperationNotAllowedError(BusinessLogicError):
    def __init__(self, operation: str, reason: str = None):
        message = f"허용되지 않은 작업입니다: {operation}"
        if reason:
            message += f" ({reason})"
        super().__init__(message=message, error_code="OPERATION_NOT_ALLOWED")


# === External Service Errors ===
class ExternalServiceError(BaseCustomException):
    def __init__(self, service: str, message: str = None):
        default_message = f"외부 서비스 오류: {service}"
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message=message or default_message,
            error_code="EXTERNAL_SERVICE_ERROR",
            details={"service": service}
        )


class DatabaseError(BaseCustomException):
    def __init__(self, message: str = "데이터베이스 오류가 발생했습니다", operation: str = None):
        details = {"operation": operation} if operation else {}
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=message,
            error_code="DATABASE_ERROR",
            details=details
        )


class FileProcessingError(BaseCustomException):
    def __init__(self, message: str, file_name: str = None, file_size: int = None):
        details = {}
        if file_name:
            details["file_name"] = file_name
        if file_size:
            details["file_size"] = file_size
            
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=message,
            error_code="FILE_PROCESSING_ERROR",
            details=details
        )


class RateLimitError(BaseCustomException):
    def __init__(self, limit: int, window: str):
        message = f"요청 한도를 초과했습니다 (최대 {limit}회/{window})"
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            message=message,
            error_code="RATE_LIMIT_EXCEEDED",
            details={"limit": limit, "window": window}
        )


# === System Errors ===
class SystemMaintenanceError(BaseCustomException):
    def __init__(self, message: str = "시스템 점검 중입니다"):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=message,
            error_code="SYSTEM_MAINTENANCE"
        )


# === 편의 함수들 ===
def raise_not_found(resource: str, identifier: str = None):
    """리소스를 찾을 수 없을 때 사용하는 편의 함수"""
    raise ResourceNotFoundError(resource=resource, identifier=identifier)


def raise_permission_denied(message: str = None, resource: str = None):
    """권한 부족 시 사용하는 편의 함수"""
    raise PermissionDeniedError(message=message, resource=resource)


def raise_validation_error(message: str, field: str = None):
    """검증 실패 시 사용하는 편의 함수"""
    raise ValidationError(message=message, field=field)


def raise_business_error(message: str, error_code: str = None):
    """비즈니스 로직 오류 시 사용하는 편의 함수"""
    raise BusinessLogicError(message=message, error_code=error_code)