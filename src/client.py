import asyncio
import time
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    def __init__(self, fail_max: int = 5, reset_timeout: float = 10.0):
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.fail_count = 0
        self.state = "CLOSED"
        self.opened_at: Optional[float] = None
        self._lock = asyncio.Lock()

    async def allow_request(self) -> bool:
        async with self._lock:
            if self.state == "OPEN":
                if (time.time() - (self.opened_at or 0)) >= self.reset_timeout:
                    self.state = "HALF_OPEN"
                    logger.info("Circuit moving to HALF_OPEN for trial")
                    return True
                return False
            return True

    async def record_success(self):
        async with self._lock:
            self.fail_count = 0
            if self.state != "CLOSED":
                logger.info("Circuit closed after successful trial")
            self.state = "CLOSED"

    async def record_failure(self):
        async with self._lock:
            self.fail_count += 1
            logger.debug(f"Circuit failure count: {self.fail_count}")
            if self.fail_count >= self.fail_max:
                self.state = "OPEN"
                self.opened_at = time.time()
                logger.warning(f"Circuit opened after {self.fail_count} failures")

    async def force_open(self):
        async with self._lock:
            self.state = "OPEN"
            self.opened_at = time.time()
            logger.warning("Circuit forcibly opened")

    async def reset(self):
        async with self._lock:
            self.state = "CLOSED"
            self.fail_count = 0
            self.opened_at = None
            logger.info("Circuit forcibly reset to CLOSED")


class RateLimiter:
    def __init__(self, max_rate: int = 5, per_seconds: float = 1.0):
        self.capacity = float(max_rate)
        self.tokens = float(max_rate)
        self.fill_rate = float(max_rate) / float(per_seconds)
        self.last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last
            self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)
            self.last = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            needed = 1.0 - self.tokens
            wait_for = needed / self.fill_rate
        logger.debug(f"RateLimiter sleeping {wait_for:.3f}s for token")
        await asyncio.sleep(wait_for)
        async with self._lock:
            self.tokens = max(0.0, self.tokens - 1.0)


class ResilientClient:
    def __init__(
        self,
        timeout: float = 3.0,
        retry_attempts: int = 2,
        backoff_factor: float = 0.5,
        max_concurrency: int = 5,
        rate_limit: int = 5,
        rate_period: float = 1.0,
        cb_fail_max: int = 5,
        cb_reset_timeout: float = 10.0,
        fallback_response: Optional[dict] = None,
    ):
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.backoff_factor = backoff_factor
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.rate_limiter = RateLimiter(rate_limit, rate_period)
        self.circuit = CircuitBreaker(cb_fail_max, cb_reset_timeout)
        self.fallback_response = fallback_response or {"ok": False, "reason": "fallback"}
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self):
        if self._client is None:
            self._client = httpx.AsyncClient()
            logger.info("httpx AsyncClient started")

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("httpx AsyncClient closed")

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        async with self.semaphore:
            await self.rate_limiter.acquire()

            allowed = await self.circuit.allow_request()
            if not allowed:
                logger.warning("Request blocked by open circuit")
                raise CircuitOpenError("circuit is open")

            attempt = 0
            while True:
                attempt += 1
                try:
                    logger.info(f"Request attempt {attempt} -> {url}")
                    resp = await self._client.request(method, url, timeout=self.timeout, **kwargs)  # type: ignore
                    if resp.status_code >= 500:
                        raise httpx.HTTPStatusError("server error", request=resp.request, response=resp)
                    await self.circuit.record_success()
                    logger.info(f"Request success {resp.status_code} -> {url}")
                    return resp
                except asyncio.TimeoutError as exc:
                    await self.circuit.record_failure()
                    logger.warning(f"Timeout on {url}: {exc}")
                    if attempt > self.retry_attempts:
                        logger.error("Exceeded retry attempts (timeout)")
                        raise
                except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                    await self.circuit.record_failure()
                    logger.warning(f"HTTP error on {url}: {exc}")
                    if attempt > self.retry_attempts:
                        logger.error("Exceeded retry attempts (http error)")
                        raise

                sleep = self.backoff_factor * (2 ** (attempt - 1))
                logger.debug(f"Sleeping {sleep:.2f}s before retry")
                await asyncio.sleep(sleep)

    async def call(self, url: str, method: str = "GET", fallback: Optional[dict] = None, **kwargs) -> dict:
        try:
            resp = await self._request(method, url, **kwargs)
            return {"ok": True, "status_code": resp.status_code, "text": resp.text}
        except CircuitOpenError:
            logger.warning("Using fallback due to circuit open")
            return fallback or self.fallback_response
        except Exception:
            logger.exception("Final error calling url")
            return fallback or self.fallback_response

    async def run_batch(self, urls: list):
        tasks = [asyncio.create_task(self.call(u)) for u in urls]
        return await asyncio.gather(*tasks)

    # control helpers
    async def force_open_circuit(self):
        await self.circuit.force_open()

    async def reset_circuit(self):
        await self.circuit.reset()

    def circuit_state(self):
        return {"state": self.circuit.state, "fail_count": self.circuit.fail_count, "opened_at": self.circuit.opened_at}
