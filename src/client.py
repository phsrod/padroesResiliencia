# imports

import asyncio # fornece suporte a programação assíncrona
import time # usado para medições de tempo e timestamps
import logging # usado para registro de logs
from typing import Optional # usado para anotações de tipo opcionais
import httpx # biblioteca HTTP assíncrona para fazer requisições


# Configuração do logger
logger = logging.getLogger(__name__) #cria um logger com o nome do módulo atual, permitindo registrar mensagens de log


# Exceção personalizada para circuito aberto - indica que o CB está aberto e não permite requisições
class CircuitOpenError(Exception): 
    pass


# Implementação do Circuit Breaker
class CircuitBreaker:
    def __init__(self, fail_max: int = 5, reset_timeout: float = 10.0):
        self.fail_max = fail_max # número máximo de falhas antes de abrir o circuito
        self.reset_timeout = reset_timeout # tempo (em segundos) que o circuito permanece aberto antes de tentar se recuperar (half-open)
        self.fail_count = 0 # contador de falhas
        self.state = "CLOSED" # estado inicial do circuito
        self.opened_at: Optional[float] = None # instante que o circuito foi aberto
        self._lock = asyncio.Lock() # garante que modificações ao estado do circuito sejam thread-safe (assíncronas seguras)

    async def allow_request(self) -> bool: # verifica se uma requisição pode ser feita com base no estado do circuito
        async with self._lock: # garante acesso thread-safe ao estado do circuito
            if self.state == "OPEN": # se o circuito estiver aberto, verifica se o tempo de reset expirou
                if (time.time() - (self.opened_at or 0)) >= self.reset_timeout: # 
                    self.state = "HALF_OPEN"
                    logger.info("Circuit moving to HALF_OPEN for trial")
                    return True
                return False
            return True

    async def record_success(self): # registra uma requisição bem-sucedida
        async with self._lock:
            self.fail_count = 0 # reseta o contador de falhas
            if self.state != "CLOSED": # se o circuito não estiver fechado, fecha-o
                logger.info("Circuit closed after successful trial") 
            self.state = "CLOSED"

    async def record_failure(self): # registra uma requisição que falhou
        async with self._lock:
            self.fail_count += 1 # incrementa o contador de falhas
            logger.debug(f"Circuit failure count: {self.fail_count}") # registra o número atual de falhas
            if self.fail_count >= self.fail_max: # se o número de falhas exceder o máximo permitido, abre o circuito
                self.state = "OPEN" # abre o circuito
                self.opened_at = time.time() # registra o instante que o circuito foi aberto
                logger.warning(f"Circuit opened after {self.fail_count} failures") # registra que o circuito foi aberto

    async def force_open(self): # força a abertura do circuito
        async with self._lock:
            self.state = "OPEN" # abre o circuito
            self.opened_at = time.time() # registra o instante que o circuito foi aberto
            logger.warning("Circuit forcibly opened") # registra que o circuito foi aberto

    async def reset(self): # reseta o circuito para o estado fechado
        async with self._lock:
            self.state = "CLOSED" # fecha o circuito
            self.fail_count = 0 # reseta o contador de falhas
            self.opened_at = None # reseta o timestamp de abertura
            logger.info("Circuit forcibly reset to CLOSED") # registra que o circuito foi resetado


# Implementação do Rate Limiter
class RateLimiter:
    def __init__(self, max_rate: int = 5, per_seconds: float = 1.0): # inicializa o limitador de taxa com a taxa máxima e o período
        self.capacity = float(max_rate) # capacidade máxima de tokens
        self.tokens = float(max_rate) # tokens disponíveis inicialmente
        self.fill_rate = float(max_rate) / float(per_seconds) # taxa de preenchimento de tokens por segundo
        self.last = time.monotonic() # último timestamp de atualização
        self._lock = asyncio.Lock() # garante que modificações ao estado do limitador sejam thread-safe (assíncronas seguras)

    async def acquire(self): # adquire um token, aguardando se necessário
        async with self._lock:
            now = time.monotonic() # obtém o timestamp atual
            elapsed = now - self.last # calcula o tempo decorrido desde a última atualização
            self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate) # atualiza o número de tokens disponíveis
            self.last = now # atualiza o timestamp da última atualização
            if self.tokens >= 1.0: # se houver tokens disponíveis, consome um e retorna imediatamente
                self.tokens -= 1.0 # consome um token
                return
            needed = 1.0 - self.tokens # calcula quantos tokens são necessários
            wait_for = needed / self.fill_rate # calcula o tempo de espera necessário para obter um token
        logger.debug(f"RateLimiter sleeping {wait_for:.3f}s for token") # registra o tempo de espera
        await asyncio.sleep(wait_for) # aguarda o tempo necessário
        async with self._lock:
            self.tokens = max(0.0, self.tokens - 1.0) # consome um token após a espera

# Cliente HTTP resiliente com timeout, retries, controle de concorrência, rate limiting e circuit breaker
class ResilientClient:
    def __init__(
        self,
        timeout: float = 3.0, # tempo máximo de espera para uma requisição
        retry_attempts: int = 2, # número máximo de tentativas de retry
        backoff_factor: float = 0.5, # fator de backoff para retries
        max_concurrency: int = 5, # número máximo de requisições concorrentes
        rate_limit: int = 5, # número máximo de requisições por período
        rate_period: float = 1.0, # período para o rate limit
        cb_fail_max: int = 5, # número máximo de falhas antes de abrir o circuito
        cb_reset_timeout: float = 10.0, # tempo que o circuito permanece aberto antes de tentar se recuperar
        fallback_response: Optional[dict] = None, # resposta de fallback padrão
    ):
        self.timeout = timeout # tempo máximo de espera para uma requisição
        self.retry_attempts = retry_attempts # número máximo de tentativas de retry
        self.backoff_factor = backoff_factor # fator de backoff para retries
        self.semaphore = asyncio.Semaphore(max_concurrency) # controla o número máximo de requisições concorrentes
        self.rate_limiter = RateLimiter(rate_limit, rate_period) # limitador de taxa
        self.circuit = CircuitBreaker(cb_fail_max, cb_reset_timeout) # circuito breaker
        self.fallback_response = fallback_response or {"ok": False, "reason": "fallback"} # resposta de fallback padrão
        self._client: Optional[httpx.AsyncClient] = None # cliente HTTP assíncrono

    # Inicializa o cliente HTTP assíncrono
    async def start(self):
        if self._client is None: # se o cliente ainda não foi inicializado
            self._client = httpx.AsyncClient() # cria uma nova instância do cliente HTTP assíncrono
            logger.info("httpx AsyncClient started") # registra que o cliente foi iniciado

    # Fecha o cliente HTTP assíncrono
    async def close(self):
        if self._client is not None: # se o cliente foi inicializado
            await self._client.aclose() # fecha o cliente HTTP assíncrono
            self._client = None # reseta a instância do cliente
            logger.info("httpx AsyncClient closed") # registra que o cliente foi fechado

    # Método interno para fazer requisições HTTP com retries, timeout, controle de concorrência, rate limiting e circuit breaker
    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response: # faz uma requisição HTTP com os mecanismos de resiliência
        async with self.semaphore: # controla o número máximo de requisições concorrentes
            await self.rate_limiter.acquire() # aplica o rate limiting

            allowed = await self.circuit.allow_request() # verifica se o circuito permite a requisição
            if not allowed: # se o circuito estiver aberto, bloqueia a requisição
                logger.warning("Request blocked by open circuit") # registra que a requisição foi bloqueada pelo circuito aberto
                raise CircuitOpenError("circuit is open") # lança a exceção de circuito aberto

            attempt = 0 # contador de tentativas
            while True: # loop de tentativas de requisição
                attempt += 1
                try:
                    logger.info(f"Request attempt {attempt} -> {url}") # registra a tentativa de requisição
                    resp = await self._client.request(method, url, timeout=self.timeout, **kwargs)  # faz a requisição HTTP com timeout
                    if resp.status_code >= 500: # considera erros 5xx como falhas
                        raise httpx.HTTPStatusError("server error", request=resp.request, response=resp) # lança exceção para erros 5xx
                    await self.circuit.record_success() # registra o sucesso no circuito breaker
                    logger.info(f"Request success {resp.status_code} -> {url}") # registra o sucesso da requisição
                    return resp
                except asyncio.TimeoutError as exc: # trata timeout
                    await self.circuit.record_failure() # registra a falha no circuito breaker
                    logger.warning(f"Timeout on {url}: {exc}") # registra o timeout
                    if attempt > self.retry_attempts: # se excedeu o número de tentativas, lança a exceção
                        logger.error("Exceeded retry attempts (timeout)") # registra o erro de tentativas excedidas
                        raise
                except (httpx.RequestError, httpx.HTTPStatusError) as exc: # trata erros de requisição HTTP
                    await self.circuit.record_failure() # registra a falha no circuito breaker
                    logger.warning(f"HTTP error on {url}: {exc}") # registra o erro HTTP
                    if attempt > self.retry_attempts: # se excedeu o número de tentativas, lança a exceção
                        logger.error("Exceeded retry attempts (http error)") # registra o erro de tentativas excedidas
                        raise

                sleep = self.backoff_factor * (2 ** (attempt - 1)) # calcula o tempo de backoff exponencial
                logger.debug(f"Sleeping {sleep:.2f}s before retry") # registra o tempo de espera antes da próxima tentativa
                await asyncio.sleep(sleep) # aguarda o tempo de backoff antes da próxima tentativa

    # Método público para fazer chamadas HTTP com fallback em caso de falha
    async def call(self, url: str, method: str = "GET", fallback: Optional[dict] = None, **kwargs) -> dict: # faz uma chamada HTTP com fallback
        try: # tenta fazer a requisição HTTP
            resp = await self._request(method, url, **kwargs) # faz a requisição HTTP com os mecanismos de resiliência
            return {"ok": True, "status_code": resp.status_code, "text": resp.text} # retorna a resposta bem-sucedida
        except CircuitOpenError: # trata o caso de circuito aberto
            logger.warning("Using fallback due to circuit open")
            return fallback or self.fallback_response
        except Exception: # trata outras exceções
            logger.exception("Final error calling url")
            return fallback or self.fallback_response

    # Método para executar múltiplas chamadas HTTP em batch
    async def run_batch(self, urls: list): # executa múltiplas chamadas HTTP em batch
        tasks = [asyncio.create_task(self.call(u)) for u in urls] # cria tarefas para cada URL
        return await asyncio.gather(*tasks)

    # control helpers
    async def force_open_circuit(self): # força a abertura do circuito
        await self.circuit.force_open()

    async def reset_circuit(self): # reseta o circuito para o estado fechado
        await self.circuit.reset()

    def circuit_state(self): # retorna o estado atual do circuito
        return {"state": self.circuit.state, "fail_count": self.circuit.fail_count, "opened_at": self.circuit.opened_at}
