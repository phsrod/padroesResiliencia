"""
Demo runner for FastAPI async client without starting the web server.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.client import ResilientClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

HTTPBIN = 'https://httpbin.org'


def build_urls(count: int):
    urls = []
    for i in range(count):
        if i % 5 == 0:
            urls.append(f"{HTTPBIN}/status/500")
        elif i % 3 == 0:
            urls.append(f"{HTTPBIN}/delay/3")
        else:
            urls.append(f"{HTTPBIN}/get")
    return urls


async def main():
    client = ResilientClient(timeout=2.0, retry_attempts=2, backoff_factor=0.3, max_concurrency=6, rate_limit=6, rate_period=1.0, cb_fail_max=3, cb_reset_timeout=8.0)
    await client.start()
    urls = build_urls(30)
    logger.info('Starting demo batch')
    results = await client.run_batch(urls)
    ok = sum(1 for r in results if r.get('ok'))
    logger.info(f'Done. Success: {ok} / {len(results)}')
    await client.close()


if __name__ == '__main__':
    asyncio.run(main())
