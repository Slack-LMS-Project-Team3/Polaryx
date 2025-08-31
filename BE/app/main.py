from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from urllib.parse import urlencode
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.exceptions import CustomHTTPException
from app.core.exception_handlers import (
    custom_http_exception_handler,
    http_exception_handler,
    validation_exception_handler,
    general_exception_handler
)

from app.router import message
from app.router.auth import auth_controller as auth
from app.router import workspace_members
from app.router import workspace
from app.router import s3
from app.router import tab
from app.router import ws_message
from app.router import direct_message
from app.router import push
from app.router import notification
from app.router import db
from app.router import role
from app.router import group
from app.router import links
from app.router import sse  # SSE
from app.router import canvas
from app.router import save_message


load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://3.36.61.200:3000", "http://jungle-lms.site:3000", "http://polaryx.net:3000"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
    max_age=0
)
app.include_router(router=ws_message.router, prefix="/api/ws")
app.include_router(router=message.router, prefix="/api")
app.include_router(router=auth.router, prefix="/api")
app.include_router(router=s3.router, prefix="/api")
app.include_router(router=push.router, prefix="/api")
app.include_router(router=notification.router, prefix="/api")
app.include_router(router=group.router, prefix="/api")
app.include_router(router=links.router, prefix="/api")

app.include_router(router=workspace_members.router, prefix="/api")
app.include_router(router=tab.router, prefix="/api")
app.include_router(router=workspace.router, prefix="/api")
app.include_router(router=direct_message.router, prefix="/api")
app.include_router(router=db.router, prefix="/api")
app.include_router(router=role.router, prefix="/api")
app.include_router(router=sse.router, prefix="/api")
app.include_router(router=canvas.router, prefix="/api")
app.include_router(router=save_message.router, prefix="/api")


# 예외 핸들러 등록
app.add_exception_handler(CustomHTTPException, custom_http_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "message": "Service is running"}





