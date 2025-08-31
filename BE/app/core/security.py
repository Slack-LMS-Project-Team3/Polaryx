# 엑세스 토큰 확인하는 로직
# (모든 라우터에 depends)
from fastapi import HTTPException, Request
from jose import JWTError, jwt, ExpiredSignatureError
from app.config.config import settings

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"

def is_token_expired(token: str) -> bool:
    try:
        jwt.decode(token, SECRET_KEY, algorithms=ALGORITHM)
        return False
    except ExpiredSignatureError:
        return True
    
def is_token_bad(token: str) -> bool:
    try:
        jwt.decode(token, SECRET_KEY, algorithms=ALGORITHM)
        return False
    except JWTError:
        return True

# 토큰 유효성 검사
def verify_token_and_get_token_data(request: Request) -> dict:

    # 먼저 요청 헤더의 authorization을 확인해보고,
    Bearer_token = request.headers.get("Authorization")

    try:
        token = Bearer_token.split()[1]
    except:
    # 토큰이 거기에 존재하지 않으면 401, NO ACCESS TOKEN PROVIDED 에러
        print("NO ACCESS TOKEN PROVIDED\n\n")
        raise HTTPException(status_code=401, detail="NO ACCESS TOKEN PROVIDED")
    
    # 문제 없으면 payload 에서 뽑아낸, 토큰에 들어있던 데이터 반환.
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

    except:
    # 실패시 만료되지 않았는지 확인
        if ExpiredSignatureError:
            print("EXPIRED TOKEN\n\n")        
            raise HTTPException(status_code=401, detail="EXPIRED TOKEN")            

    # 실패시 토큰이 정상적인지 확인
        elif JWTError:
            print("INVALID TOKEN\n\n")        

            raise HTTPException(status_code=401, detail="INVALID TOKEN")

    result = {"user_id": payload.get("user_id"), "email": payload.get("email")}
    print("in verify_token_and_get_token_data, result: ", result)
    return result