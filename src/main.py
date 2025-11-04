import asyncio
import logging
import os
import random
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from src.client import ResilientClient

# logging
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "app.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Resilience Demo (FastAPI)")

# client instance
client = ResilientClient(
    timeout=2.0,
    retry_attempts=2,
    backoff_factor=0.4,
    max_concurrency=6,
    rate_limit=6,
    rate_period=1.0,
    cb_fail_max=3,
    cb_reset_timeout=8.0,
    fallback_response={"ok": False, "reason": "fallback from fastapi"},
)

HTTPBIN = "https://httpbin.org"


def build_urls(count: int):
    urls = []
    for i in range(count):
        r = random.random()
        if r < 0.6:
            urls.append(f"{HTTPBIN}/get")
        elif r < 0.85:
            urls.append(f"{HTTPBIN}/delay/3")
        else:
            urls.append(f"{HTTPBIN}/status/500")
    return urls


@app.on_event("startup")
async def startup_event():
    logger.info("Starting Resilience Demo (FastAPI)")
    await client.start()


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Resilience Demo (FastAPI)")
    await client.close()


@app.get("/invoke")
async def invoke(count: int = 10):
    urls = build_urls(count)
    logger.info(f"Invoke: running batch of {count} calls")
    results = await client.run_batch(urls)
    ok = sum(1 for r in results if r.get("ok"))
    return JSONResponse({"requested": count, "successful": ok, "results": results})


@app.get("/invoke_delay")
async def invoke_delay(count: int = 8):
    urls = [f"{HTTPBIN}/delay/3" for _ in range(count)]
    logger.info(f"Invoke delay: {count} calls to /delay/3")
    results = await client.run_batch(urls)
    ok = sum(1 for r in results if r.get("ok"))
    return JSONResponse({"requested": count, "successful": ok, "results": results})


@app.get("/invoke_error")
async def invoke_error(count: int = 8):
    urls = [f"{HTTPBIN}/status/500" for _ in range(count)]
    logger.info(f"Invoke error: {count} calls to /status/500")
    results = await client.run_batch(urls)
    ok = sum(1 for r in results if r.get("ok"))
    return JSONResponse({"requested": count, "successful": ok, "results": results})


@app.post("/force_open")
async def force_open():
    await client.force_open_circuit()
    return JSONResponse({"status": "circuit_forced_open"})


@app.post("/reset_circuit")
async def reset_circuit():
    await client.reset_circuit()
    return JSONResponse({"status": "circuit_reset"})


@app.get("/circuit_state")
async def circuit_state():
    # circuit_state is sync, but cheap; run in threadpool for safety
    state = await run_in_threadpool(client.circuit_state)
    return JSONResponse(state)


@app.get("/logs")
async def get_logs():
    if not os.path.exists(LOG_FILE):
        return PlainTextResponse("No logs yet", status_code=404)
    # read file in threadpool to avoid blocking event loop
    text = await run_in_threadpool(lambda: open(LOG_FILE, "r", encoding="utf-8").read())
    return PlainTextResponse(text)


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})
