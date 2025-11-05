# imports

import asyncio # importa o módulo asyncio para programação assíncrona
import logging # importa o módulo logging para registro de logs
import os # importa o módulo os para manipulação de caminhos de arquivos
import random # importa o módulo random para geração de números aleatórios
from fastapi import FastAPI, BackgroundTasks # importa FastAPI e BackgroundTasks do framework FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse # importa respostas JSON e PlainText do FastAPI
from starlette.concurrency import run_in_threadpool # importa função para executar código em threadpool
from src.client import ResilientClient # importa a classe ResilientClient do módulo client

# logging
BASE_DIR = os.path.dirname(os.path.dirname(__file__)) # diretório base do projeto
LOG_DIR = os.path.join(BASE_DIR, "logs") # diretório de logs
os.makedirs(LOG_DIR, exist_ok=True) # cria o diretório de logs se não existir
LOG_FILE = os.path.join(LOG_DIR, "app.log") # caminho do arquivo de log

# configura o logging
logging.basicConfig( 
    level=logging.INFO, 
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
) # configura o logging para console e arquivo
logger = logging.getLogger(__name__) # obtém o logger para este módulo

app = FastAPI(title="Resilience Demo (FastAPI)") # cria a aplicação FastAPI

# Resilient HTTP Client
client = ResilientClient(
    timeout=2.0, # tempo limite para requisições HTTP
    retry_attempts=2, # número de tentativas de retry
    backoff_factor=0.4, # fator de backoff exponencial
    max_concurrency=6, # concorrência máxima de requisições
    rate_limit=6, # limite de requisições por segundo
    rate_period=1.0, # período para o rate limit
    cb_fail_max=3, # número máximo de falhas para abrir o circuito
    cb_reset_timeout=8.0, # tempo para resetar o circuito
    fallback_response={"ok": False, "reason": "fallback from fastapi"}, # resposta de fallback em caso de falha
)

HTTPBIN = "https://httpbin.org" # base URL para testes HTTP

# construir URLs variadas para teste
def build_urls(count: int):
    urls = []
    for i in range(count):
        r = random.random() # gera um número aleatório entre 0 e 1
        if r < 0.6: # 60% de chance de sucesso rápido
            urls.append(f"{HTTPBIN}/get") # resposta rápida
        elif r < 0.85: # 25% de chance de atraso
            urls.append(f"{HTTPBIN}/delay/3") # atraso de 3 segundos
        else: # 15% de chance de erro
            urls.append(f"{HTTPBIN}/status/500") # erro 500
    return urls # retorna a lista de URLs construídas

# eventos de startup da aplicação
@app.on_event("startup")
async def startup_event():
    logger.info("Starting Resilience Demo (FastAPI)") # registra o startup
    await client.start()

# eventos de shutdown da aplicação
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Resilience Demo (FastAPI)") # registra o desligamento
    await client.close()


# endpoint para invocar múltiplas chamadas HTTP
@app.get("/invoke")
async def invoke(count: int = 10): 
    urls = build_urls(count) # constrói URLs variadas para teste
    logger.info(f"Invoke: running batch of {count} calls") # registra a invocação
    results = await client.run_batch(urls) # executa as chamadas em batch
    ok = sum(1 for r in results if r.get("ok")) # conta o número de chamadas bem-sucedidas
    return JSONResponse({"requested": count, "successful": ok, "results": results}) # retorna a resposta JSON com os resultados

# endpoint para invocar chamadas com atraso
@app.get("/invoke_delay")
async def invoke_delay(count: int = 8):
    urls = [f"{HTTPBIN}/delay/3" for _ in range(count)] # URLs com atraso de 3 segundos
    logger.info(f"Invoke delay: {count} calls to /delay/3") # registra a invocação
    results = await client.run_batch(urls) # executa as chamadas em batch
    ok = sum(1 for r in results if r.get("ok")) # conta o número de chamadas bem-sucedidas
    return JSONResponse({"requested": count, "successful": ok, "results": results}) # retorna a resposta JSON com os resultados

# endpoint para invocar chamadas que retornam erro 
@app.get("/invoke_error")
async def invoke_error(count: int = 8):
    urls = [f"{HTTPBIN}/status/500" for _ in range(count)] # URLs que retornam erro 500
    logger.info(f"Invoke error: {count} calls to /status/500") # registra a invocação
    results = await client.run_batch(urls) # executa as chamadas em batch
    ok = sum(1 for r in results if r.get("ok")) # conta o número de chamadas bem-sucedidas
    return JSONResponse({"requested": count, "successful": ok, "results": results}) # retorna a resposta JSON com os resultados

# endpoint para forçar a abertura do circuito
@app.post("/force_open")
async def force_open():
    await client.force_open_circuit()
    return JSONResponse({"status": "circuit_forced_open"})

# endpoint para resetar o circuito
@app.post("/reset_circuit")
async def reset_circuit():
    await client.reset_circuit()
    return JSONResponse({"status": "circuit_reset"})

# endpoint para obter o estado atual do circuito
@app.get("/circuit_state")
async def circuit_state():
    # circuit_state is sync, but cheap; run in threadpool for safety
    state = await run_in_threadpool(client.circuit_state)
    return JSONResponse(state)

# endpoint para obter os logs da aplicação
@app.get("/logs")
async def get_logs():
    if not os.path.exists(LOG_FILE):
        return PlainTextResponse("No logs yet", status_code=404)
    # read file in threadpool to avoid blocking event loop
    text = await run_in_threadpool(lambda: open(LOG_FILE, "r", encoding="utf-8").read())
    return PlainTextResponse(text)

# health check endpoint
@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})
