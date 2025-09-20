# 엑세스 토큰 확인하는 로직
# (모든 라우터에 depends)
from fastapi import Request
from jose import JWTError, jwt, ExpiredSignatureError
from app.config.config import settings
from app.core.exceptions import (
    AuthenticationError,
    TokenExpiredError,
    InvalidTokenError
)
import logging

logger = logging.getLogger(__name__)

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"

def is_token_expired(token: str) -> bool:
    """토큰 만료 여부 확인"""
    try:
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return False
    except ExpiredSignatureError:
        return True
    
def is_token_bad(token: str) -> bool:
    """토큰 유효성 확인"""
    try:
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return False
    except JWTError:
        return True

def verify_token_and_get_token_data(request: Request) -> dict:
    """토큰 유효성 검사 및 사용자 데이터 추출"""
    
    # Authorization 헤더 확인
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        logger.warning("Missing Authorization header")
        raise AuthenticationError("인증 토큰이 제공되지 않았습니다")
    
    # Bearer 토큰 형식 확인
    try:
        scheme, token = auth_header.split()
        if scheme.lower() != "bearer":
            raise AuthenticationError("Bearer 토큰 형식이 아닙니다")
    except ValueError:
        logger.warning("Invalid Authorization header format")
        raise AuthenticationError("Authorization 헤더 형식이 올바르지 않습니다")
    
    # 문제 없으면 payload 에서 뽑아낸, 토큰에 들어있던 데이터 반환
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # 필수 필드 확인
        user_id = payload.get("user_id")
        email = payload.get("email")
        
        if not user_id or not email:
            logger.warning("Token payload missing required fields")
            raise InvalidTokenError("토큰에 필수 정보가 누락되었습니다")
        
        logger.debug(f"Token verified for user: {user_id}")
        return {"user_id": user_id, "email": email}
        
    except ExpiredSignatureError:
        logger.warning("Token expired")
        raise TokenExpiredError()
        
    except JWTError as e:
        logger.warning(f"JWT validation failed: {str(e)}")
        raise InvalidTokenError()
    
    except Exception as e:
        logger.error(f"Unexpected error during token verification: {str(e)}")
        raise AuthenticationError("토큰 검증 중 오류가 발생했습니다")