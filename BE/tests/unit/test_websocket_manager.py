from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch


def _set_required_env() -> None:
    defaults = {
        "SECRET_KEY": "test-regression-secret",
        "GOOGLE_CLIENT_ID": "test-google-client",
        "GOOGLE_CLIENT_SECRET": "test-google-secret",
        "GOOGLE_REDIRECT_URI": "http://localhost/auth/callback",
        "CONNECTION_TIMEOUT": "1",
        "RDB_HOST": "127.0.0.1",
        "RDB_PORT": "3306",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
        "DB_NAME": "polaryx_test",
        "NOSQL_HOST": "127.0.0.1",
        "NOSQL_PORT": "27017",
        "NOSQL_URL": "mongodb://127.0.0.1:27017",
        "GITHUBS_CLIENT_ID": "test-github-client",
        "GITHUBS_CLIENT_SECRET": "test-github-secret",
        "GITHUBS_REDIRECT_URI": "http://localhost/auth/github/callback",
        "AWS_REGION": "ap-northeast-2",
        "AWS_BUCKET_NAME": "test-bucket",
        "AWS_ACCESS_KEY_ID": "test-access-key",
        "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        "VAPID_PUBLIC_KEY": "test-public",
        "VAPID_PRIVATE_KEY": "test-private",
        "VAPID_EMAIL": "mailto:test@example.com",
        "REDIS_HOST": "127.0.0.1",
        "REDIS_PORT": "6379",
        "REDIS_PASSWORD": "",
        "REDIS_DB": "0",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


_set_required_env()

from app.service.websocket_manager import ConnectionManager


class BlockingPipeline:
    def __init__(self, redis: "BlockingRedis") -> None:
        self.redis = redis
        self.commands: list[tuple[str, dict[str, object]]] = []

    def publish(self, channel: str, payload: str) -> None:
        self.commands.append((channel, json.loads(payload)))

    async def execute(self) -> None:
        self.redis.execute_started.set()
        await self.redis.release_execute.wait()
        self.redis.published.extend(self.commands)


class BlockingRedis:
    def __init__(self) -> None:
        self.execute_started = asyncio.Event()
        self.release_execute = asyncio.Event()
        self.published: list[tuple[str, dict[str, object]]] = []

    def pipeline(self) -> BlockingPipeline:
        return BlockingPipeline(self)


class ConnectionManagerRedisBatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_batch_task_publishes_messages_queued_while_pipeline_execute_is_in_flight(self) -> None:
        manager = ConnectionManager()
        manager.socket_type = "message"
        manager.server_id = "server-a"
        redis = BlockingRedis()

        with patch.object(manager, "_get_redis_client", AsyncMock(return_value=redis)):
            await manager._queue_redis_broadcast(1, 2, "first")
            await asyncio.wait_for(redis.execute_started.wait(), timeout=1)

            await manager._queue_redis_broadcast(1, 2, "second")
            redis.release_execute.set()
            await asyncio.wait_for(manager._batch_task, timeout=1)

        self.assertEqual(
            [payload["message"] for _, payload in redis.published],
            ["first", "second"],
        )
        self.assertEqual(manager._pending_broadcasts, {})
        self.assertIsNone(manager._batch_task)


if __name__ == "__main__":
    unittest.main()
