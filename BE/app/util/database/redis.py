import os
import redis.asyncio as redis
from typing import Optional
from app.config.config import settings

class RedisConfig:
    def __init__(self):
        self.host = settings.REDIS_HOST
        self.port = settings.REDIS_PORT
        self.password = settings.REDIS_PASSWORD
        self.db = settings.REDIS_DB
        self.decode_responses = True

class RedisManager:
    _instance: Optional[redis.Redis] = None
    _pubsub_instance: Optional[redis.Redis] = None
    
    @classmethod
    async def get_redis(cls) -> redis.Redis:
        """Redis 클라이언트 싱글톤 인스턴스 반환"""
        if cls._instance is None:
            config = RedisConfig()
            cls._instance = redis.Redis(
                host=config.host,
                port=config.port,
                password=config.password,
                db=config.db,
                decode_responses=config.decode_responses
            )
        return cls._instance
    
    @classmethod
    async def get_pubsub_redis(cls) -> redis.Redis:
        """Pub/Sub 전용 Redis 클라이언트 반환"""
        if cls._pubsub_instance is None:
            config = RedisConfig()
            cls._pubsub_instance = redis.Redis(
                host=config.host,
                port=config.port,
                password=config.password,
                db=config.db,
                decode_responses=config.decode_responses
            )
        return cls._pubsub_instance
    
    @classmethod
    async def close_connections(cls):
        """Redis 연결 정리"""
        if cls._instance:
            await cls._instance.close()
            cls._instance = None
        if cls._pubsub_instance:
            await cls._pubsub_instance.close()
            cls._pubsub_instance = None