import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List
import uuid
from pywebpush import webpush, WebPushException
import asyncio
from concurrent.futures import ThreadPoolExecutor

from app.config.config import settings

executor = ThreadPoolExecutor()
logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_nonnegative_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class PushSendSummary:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped_no_subscription: int = 0
    elapsed_seconds: float = 0.0

    @property
    def has_failures(self) -> bool:
        return self.failed > 0

class PushService:
    def __init__(self, repo: object | None = None):
        self.repo = repo

    def _repo(self):
        if self.repo is None:
            from app.repository.push_subscription import QueryRepo as PushRepo

            self.repo = PushRepo()
        return self.repo

    @property
    def provider_timeout_seconds(self) -> float:
        return _env_float("PUSH_PROVIDER_TIMEOUT_SECONDS", 5.0)

    @property
    def provider_mode(self) -> str:
        return os.getenv("PUSH_PROVIDER_MODE", "real").strip().lower()

    @property
    def fake_provider_delay_seconds(self) -> float:
        if "PUSH_FAKE_PROVIDER_DELAY_SECONDS" in os.environ:
            return _env_nonnegative_float("PUSH_FAKE_PROVIDER_DELAY_SECONDS", 0.0)
        return _env_nonnegative_float("PUSH_FAKE_PROVIDER_DELAY_MS", 0.0) / 1000

    @property
    def noop_provider_mode(self) -> bool:
        return self.provider_mode in {"noop", "no-op", "disabled", "test"}

    def add_subscription(self, user_id: str, subscription: Dict):
        data = {
            "user_id": uuid.UUID(user_id).bytes,
            "endpoint": subscription.get("endpoint"),
            "p256dh": subscription.get("keys", {}).get("p256dh"),
            "auth": subscription.get("keys", {}).get("auth"),
        }
        logger.info("push_subscription_upsert", extra={"user_id": user_id})
        self._repo().insert(data)

    async def _send_webpush_async(self, info: dict, data: dict):
        if self.provider_mode in {"fake", "noop", "no-op", "disabled", "test"}:
            delay_seconds = self.fake_provider_delay_seconds
            if delay_seconds:
                await asyncio.sleep(delay_seconds)
            return

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            executor,
            lambda: webpush(
                subscription_info=info,
                data=json.dumps(data),
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_EMAIL},
                timeout=self.provider_timeout_seconds,
            )
        )

    async def _find_subscriptions_for_user(self, user_id: str) -> List[Dict]:
        user_id_bytes = uuid.UUID(user_id).bytes
        return await asyncio.to_thread(self._repo().find_user, user_id_bytes)

    async def _send_to_user(self, user_id: str, data: Dict) -> str:
        if self.noop_provider_mode:
            return "succeeded"

        subs: List[Dict] = await self._find_subscriptions_for_user(user_id)
        if subs == []:
            return "skipped"

        if isinstance(subs[0], tuple):
            endpoint, p256dh, auth = subs[0]
        else:
            endpoint = subs[0].get("endpoint")
            p256dh = subs[0].get("p256dh")
            auth = subs[0].get("auth")

        info = {
            "endpoint": endpoint,
            "keys": {
                "p256dh": p256dh,
                "auth": auth,
            },
        }
        try:
            await self._send_webpush_async(info, data)
            return "succeeded"
        except WebPushException as exc:
            logger.warning(
                "web_push_provider_failed",
                extra={"user_id": user_id, "exception_type": type(exc).__name__},
            )
            return "failed"
        except Exception as exc:
            logger.warning(
                "web_push_provider_unexpected_failed",
                extra={"user_id": user_id, "exception_type": type(exc).__name__},
            )
            return "failed"

    async def send_push_to(self, user_ids: List[str], data: Dict) -> PushSendSummary:
        started = time.perf_counter()
        tasks = []
        for user_id in user_ids:
            tasks.append(self._send_to_user(user_id, data))
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return PushSendSummary(
            attempted=sum(1 for result in results if result != "skipped"),
            succeeded=sum(1 for result in results if result == "succeeded"),
            failed=sum(1 for result in results if result == "failed"),
            skipped_no_subscription=sum(1 for result in results if result == "skipped"),
            elapsed_seconds=time.perf_counter() - started,
        )
