# Resilience Demo (FastAPI)

Versão assíncrona do projeto de demonstração de padrões de resiliência. Esta pasta (`fast/`) contém uma implementação separada usando FastAPI + httpx.AsyncClient para que o comportamento de concorrência e padrões (Bulkhead, Rate Limiter, Circuit Breaker, Timeout/Retry e Fallback) seja demonstrado de forma mais realista.

Sumário rápido
- Implementação: `fast/src/client.py` (cliente async), `fast/src/main.py` (FastAPI).
- Script de demo: `fast/scripts/run_demo.py` (rodar sem servidor).
- Logs: `fast/logs/app.log` (arquivo criado em runtime).

## Tecnologias utilizadas

Uma visão organizada das tecnologias e padrões presentes nesta implementação:

- Linguagem
	- Python 3.9+ (uso de async/await para concorrência assíncrona).

- Framework / ASGI
	- FastAPI — definição de endpoints, validação e documentação automática (OpenAPI/Swagger). (arquivo: `fast/src/main.py`)
	- Uvicorn — servidor ASGI recomendado para executar a aplicação (usado no modo "com servidor").

- Cliente HTTP assíncrono
	- httpx.AsyncClient — responsável por realizar chamadas HTTP externas de forma assíncrona. (arquivo: `fast/src/client.py`)

- Concorrência e utilitários assíncronos
	- asyncio — loop assíncrono do Python; `asyncio.Semaphore` é usado como Bulkhead para limitar concorrência. (arquivo: `fast/src/client.py`)

- Padrões de resiliência implementados
	- Rate Limiter (Token Bucket) — controla o ritmo das requisições para evitar sobrecarga do serviço externo.
	- Bulkhead (Semaphore) — limita a concorrência local para proteger recursos.
	- Circuit Breaker (CLOSED / OPEN / HALF-OPEN) — evita chamadas repetidas a serviços com falha; inclui endpoints para forçar/resetar o estado. (arquivos: `fast/src/client.py`, `fast/src/main.py`)
	- Timeout + Retry (com backoff exponencial) — cancela chamadas lentas e tenta novas tentativas quando aplicável.
	- Fallback — resposta degradada quando todas as tentativas falham ou quando o circuito está aberto.

- Observabilidade / Logs
	- módulo `logging` do Python — grava eventos e transições do circuito em `fast/logs/app.log`.
	- Endpoint `/logs` para consultar os logs via HTTP. (arquivo: `fast/src/main.py`)

- Ferramentas e execução
	- `venv` / `pip` — gerenciamento de ambiente e instalação das dependências descritas em `fast/requirements.txt`.
	- PowerShell — comandos de execução e demonstração fornecidos para Windows (README).
	- `fast/scripts/run_demo.py` — modo "sem servidor" para executar os cenários localmente sem expor endpoints HTTP.

- Serviço externo usado no demo
	- httpbin.org — endpoints públicos usados para simular respostas, latências e erros (`/get`, `/delay/3`, `/status/500`).


Requisitos
- Python 3.9+ (recomendado 3.10+).
- Conexão com a internet para acessar `https://httpbin.org` (pode usar uma API local se preferir offline).

Instalação (Windows - PowerShell)

1) Abra PowerShell e entre na pasta `fast`:

```powershell
cd c:\Users\pedro\OneDrive\Documentos\UFPI\ENGII\pDr\fast
```

2) Crie e ative um virtualenv:

```powershell
python -m venv venv; .\venv\Scripts\Activate.ps1
```

3) Instale dependências:

```powershell
python -m pip install -r requirements.txt
```

Executando a aplicação (modo apresentação)

```powershell
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

- Abra `http://localhost:8000/docs` para a documentação automática (OpenAPI) — boa para apresentar rapidamente os endpoints.
- Abra `http://localhost:8000/logs` para visualizar os logs gerados em tempo real (útil para projetor/sala).

Executando o demo em lote (sem servidor)

```powershell
python .\scripts\run_demo.py
```

Estrutura de arquivos (resumo)
- `fast/src/client.py` — cliente resiliente (async): CircuitBreaker, RateLimiter, Bulkhead (Semaphore), Timeout, Retry, Fallback.
- `fast/src/main.py` — FastAPI com endpoints para cenários e controle do circuito.
- `fast/scripts/run_demo.py` — executa um batch assíncrono local.
- `fast/requirements.txt` — dependências para esta implementação.
- `fast/logs/app.log` — arquivo de logs (criado em runtime).

Endpoints (e o que fazem)
- `GET /invoke?count=N` — dispara N chamadas mistas (`/get`, `/delay/3`, `/status/500`) para demonstrar o comportamento combinado.
- `GET /invoke_delay?count=N` — dispara N chamadas para `/delay/3` (útil para demonstrar timeout + retry).
- `GET /invoke_error?count=N` — dispara N chamadas para `/status/500` (útil para forçar abertura do circuit breaker).
- `POST /force_open` — força o circuito para `OPEN` (demo somente).
- `POST /reset_circuit` — reseta o circuito para `CLOSED`.
- `GET /circuit_state` — retorna JSON com `{state, fail_count, opened_at}`.
- `GET /logs` — retorna conteúdo do log (`logs/app.log`) em texto simples.
- `GET /health` — simples verificação de saúde.

Diagrama da arquitetura (ASCII)

							┌──────────────────────────────────────────────────────────────┐
							│                    🧩 RESILIENCE DEMO (FastAPI)              │
							│        Demonstração de Padrões de Resiliência Assíncronos    │
							└──────────────────────────────────────────────────────────────┘

												┌──────────────────────┐
												│   Usuário / Cliente  │
												│ (Browser / curl / API│
												└──────────┬───────────┘
													       │  (Requisição HTTP)
														   ▼
												┌────────────────────────────┐
												│      FastAPI Server        │
												│     (src/main.py)          │
												└──────────┬─────────────────┘
														   │  (Chama cliente resiliente)
														   ▼
												┌────────────────────────────┐
												│   ResilientClient (async)  │
												│       (src/client.py)      │
												└──────────┬─────────────────┘
														   │
														   ▼ 
									┌────────────────────────────────────────────────────┐
									│               Cadeia de Padrões                    │
									│────────────────────────────────────────────────────│
									│                                                    │
									│  ① Rate Limiter (Token Bucket)                     │
									│     → Controla o ritmo das chamadas                │
									│     → Evita sobrecarga no serviço externo          │
									│                                                    │
									│  ② Bulkhead (asyncio.Semaphore)                    │
									│     → Limita concorrência                          │
									│     → Evita saturação local                        │
									│                                                    │
									│  ③ Circuit Breaker                                 │
									│     → Monitora falhas sucessivas                   │
									│     → Estados: CLOSED → OPEN → HALF-OPEN           │
									│     → Bloqueia novas chamadas quando OPEN          │
									│                                                    │
									│  ④ Timeout + Retry                                 │
									│     → Timeout cancela chamadas lentas              │
									│     → Retry tenta novamente com backoff exponencial│
									│                                                    │
									│  ⑤ Fallback                                        │
									│     → Retorna resposta padrão quando falhar tudo   │
									│     → Garante disponibilidade degradada            │
									└────────────────────────────────────────────────────┘
													       │
													       ▼
												┌────────────────────────────┐
												│  API Externa (httpbin.org) │
												│    /get, /delay/3, etc.    │
												└──────────┬─────────────────┘
													       │
													       ▼
												┌───────────────────────────┐
												│     Resposta / Fallback   │
												│    (JSON + Logs gerados)  │
												└──────────┬────────────────┘
														   │
														   ▼
												┌────────────────────────────┐
												│     FastAPI retorna JSON    │
												│ + registra logs em app.log  │
												└────────────────────────────┘

								───────────────────────────────────────────────────────────────
📂 Logs em: fast/logs/app.log
🧠 Demonstração:
   - CircuitBreaker → /invoke_error
   - Timeout/Retry  → /invoke_delay
   - Bulkhead/RateLimiter → /invoke
   - Fallback       → /force_open
───────────────────────────────────────────────────────────────


Fluxo resumido
1) Chamadas chegam no FastAPI.
2) `ResilientClient` aplica Rate Limiter e limita concorrência com Bulkhead.
3) Se houver falhas repetidas, o Circuit Breaker abre e evita novas chamadas externas.
4) Cada requisição tem Timeout; em erro é feita Retry com backoff.
5) Se tudo falhar (ou circuito aberto), o cliente retorna o Fallback.

Roteiro passo-a-passo para demonstrar padrões (sugestão para apresentação)

- Preparação
	1) Abra `http://localhost:8000/logs` em uma aba do navegador (projete essa aba).
	2) Abra `http://localhost:8000/docs` em outra aba para mostrar os endpoints.

- Demonstrar Circuit Breaker (5 minutos)
	1) Execute (no PowerShell ou no browser):

```powershell
curl "http://localhost:8000/invoke_error?count=20"
```

	2) Observe em `/logs` as falhas (`HTTP error`) e o aumento de `fail_count` até o log mostrar `Circuit opened`.
	3) Execute `curl http://localhost:8000/invoke?count=5` para provar que, enquanto o circuito estiver `OPEN`, as respostas são rápidas e vêm do fallback (sem chamadas externas).
	4) Mostre `curl http://localhost:8000/circuit_state` para ver `OPEN` e o `opened_at`.

- Demonstrar Timeout + Retry (3 minutos)
	1) Execute:

```powershell
curl "http://localhost:8000/invoke_delay?count=8"
```

	2) Cada chamada para `/delay/3` normalmente demora ~3s; como o `timeout` do cliente é menor (ex.: 2s), verá `Timeout on...` nos logs e tentativas de retry com backoff.
	3) Aponte quantas foram recuperadas via retry e quantas caíram no fallback (ver JSON de retorno do endpoint).

- Demonstrar Bulkhead + Rate Limiter (3 minutos)
	1) Execute um batch grande:

```powershell
curl "http://localhost:8000/invoke?count=60"
```

	2) Observe nos logs como a concorrência é limitada (o cliente usa `asyncio.Semaphore`) e como o Rate Limiter espaça chamadas.
	3) Explique que isso protege recursos locais e evita sobrecarregar serviços externos.

- Mostrar Fallback (1 minuto)
	1) Force o circuito aberto manualmente:

```powershell
curl -X POST http://localhost:8000/force_open
curl "http://localhost:8000/invoke?count=5"
```

	2) Mostre nos logs que as respostas vieram do fallback e explique o trade-off: disponibilidade degradada mas previsível.

Comandos úteis para apresentação (PowerShell)

```powershell
# Ver logs em tempo real (servidor):
Get-Content .\fast\logs\app.log -Tail 200 -Wait

# Estado do circuito:
curl http://localhost:8000/circuit_state

# Forçar abertura do circuito:
curl -X POST http://localhost:8000/force_open

# Resetar circuito:
curl -X POST http://localhost:8000/reset_circuit

# Invocar cenário misto:
curl "http://localhost:8000/invoke?count=20"
```

Troubleshooting
- Erro de importação (`fastapi`, `httpx`): confirme que você ativou o `venv` e executou `pip install -r requirements.txt` dentro da pasta `fast`.
- `httpbin.org` inacessível: use uma API local simples para `/delay` e `/status/500` (posso ajudar a gerar esse mock).
- Logs vazios: execute um endpoint (`/invoke`) para gerar tráfego; os logs são gravados quando o servidor lida com requisições.

Próximos passos sugeridos
- Adicionar métricas (Prometheus) para mostrar contadores e latências em dashboards durante a apresentação.
- Gerar capturas de tela automáticas dos logs para inserir nos slides.
- Implementar um endpoint `/stress` que dispara carga controlada por X segundos para demonstrar Bulkhead & Rate Limiter automaticamente.

Licença / uso
- Projeto educacional. Use à vontade para apresentações e estudos.

