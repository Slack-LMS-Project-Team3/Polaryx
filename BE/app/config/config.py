import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

env = os.environ.get("ENVIRONMENT", "DEV")
if env == "DEV":
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ENV_PATH = os.path.join(os.path.dirname(BASE_DIR), ".env")
    load_dotenv(ENV_PATH)


class Settings(BaseSettings):
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60000 
    SECRET_KEY: str
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    CONNECTION_TIMEOUT: int
    RDB_HOST: str
    RDB_PORT: int
    NOSQL_HOST: str
    NOSQL_PORT: int
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    NOSQL_URL: str = f""
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str
    GITHUBS_CLIENT_ID: str
    GITHUBS_CLIENT_SECRET: str
    GITHUBS_REDIRECT_URI: str
    AWS_REGION: str
    AWS_BUCKET_NAME: str
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    VAPID_PUBLIC_KEY: str
    VAPID_PRIVATE_KEY: str
    VAPID_EMAIL: str
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_PASSWORD: str = f""
    REDIS_DB: int

settings = Settings()