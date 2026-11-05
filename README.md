# LogiSQL-Agent

**Enterprise supply-chain text-to-SQL analytics platform** — ask a plain-English question, and a self-correcting LangGraph agent writes guardrailed PostgreSQL, runs it read-only, repairs its own failures, and returns an executive finding with a validated Plotly chart.

Built for the **Olist Brazilian e-commerce & logistics dataset** (100k+ transactions, five relational tables).

```text
Question -> Schema context -> Groq/Llama SQL -> SQLGlot AST guard -> Execute
                                   ^                              |
                                   |--------- repair <------------|
                                                                  |
                                     Executive synthesis <--------+
```

---

## What makes this production-minded

| Capability | Implementation |
| --- | --- |
| Cyclic agent | **LangGraph** state machine with a bounded repair loop |
| Fast inference | **Groq** `llama-3.3-70b-versatile` |
| Hosted warehouse | **Supabase PostgreSQL**, introspected through `information_schema` |
| SQL safety | **SQLGlot AST** parsing, single-statement enforcement, table allowlist, function denylist, read-only transaction |
| Dynamic context | Schema introspector with PK/FK awareness and TTL cache |
| Self-correction | Validation and database errors are fed back to the model (max 3 retries) |
| Execution controls | Read-only DB transaction, statement timeout, row cap, truncated-result flag |
| Dataset snapshot | Cached `/overview` KPIs (orders, delivery performance, item value) shown in the UI |
| Backpressure | Bounded concurrent queries with a queue timeout and `429 Retry-After` |
| Analytics UX | **FastAPI + asyncio** backend, **Streamlit** frontend, Plotly charts |
| Observability | LangSmith tracing, per-node timings, attempt trail, request IDs |
| Zero-setup demo | Synthetic Olist-like SQLite database seeded on first API boot |
| Tests | Guardrail, chart, schema, graph, and API tests |

---

## Architecture

```mermaid
flowchart LR
    U[Streamlit UI] -->|POST /api/v1/query| A[FastAPI]
    A --> R[LangGraph Agent]

    subgraph R[LangGraph execution]
        S[1. Schema extractor] --> G[2. SQL generator]
        G --> V[3. AST validator]
        V -->|valid| E[4. Read-only executor]
        V -->|invalid| F[Repair node]
        E -->|DB error| F
        F --> V
        E -->|rows| N[5. Synthesis]
        V -->|retries exhausted| X[Failure summary]
        E -->|retries exhausted| X
    end

    S -.->|information_schema| DB[(Supabase / SQLite)]
    E -.->|SELECT only| DB
    G -.->|Groq| LLM[Llama 3.3 70B]
    F -.->|error + schema| LLM
    N -.->|findings + chart spec| LLM
    R -.->|traces| LS[LangSmith]
```

### Agent nodes

1. **Schema extractor** — reads columns, primary keys, and foreign keys. PostgreSQL uses `information_schema`; SQLite uses SQLAlchemy inspection. Results are cached.
2. **SQL generator** — injects the live schema into a strict prompt and asks Llama 3.3 for one PostgreSQL query.
3. **Validation & guardrail** — parses with SQLGlot, rejects mutation/DDL/multiple statements, blocks system schemas and dangerous functions, and checks the table allowlist.
4. **Execution & repair** — executes inside a read-only Postgres transaction with `statement_timeout`. Any SQL or DB error is returned to the repair node.
5. **Synthesis** — turns result rows into an executive summary and a bounded chart request; the backend builds the Plotly JSON rather than trusting arbitrary model output.

---

## Quickstart (zero cloud setup)

The default configuration runs against a synthetic Olist-like SQLite database with **1,200 orders**, so you can evaluate the whole system before connecting Supabase.

### 1. Install

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
```

**macOS / Linux**

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
```

Add a free Groq key to `.env`:

```env
GROQ_API_KEY=gsk_your_key_here
```

Get one at <https://console.groq.com/keys>.

### 2. Run the API

```bash
uvicorn logisql.api.main:app --reload --port 8000
```

On first boot, `data/logisql_demo.db` is created and seeded. Useful endpoints:

- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/api/v1/health>
- Schema: <http://localhost:8000/api/v1/schema>

### 3. Run the UI

In a second terminal:

```bash
streamlit run apps/streamlit_app.py
```

Open <http://localhost:8501> and ask one of the suggested questions.

### Optional: seed or reset the demo DB

```bash
python scripts/seed_demo.py --orders 1200 --force
```

---

## Connect the real Olist dataset on Supabase

### 1. Create the schema

Create a free Supabase project, open **SQL Editor**, and run [`database/schema.sql`](database/schema.sql). It creates five constrained tables and analytics indexes.

### 2. Download the Olist CSVs

Download the **Brazilian E-Commerce Public Dataset by Olist** from Kaggle:

<https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce>

Place these files in `data/raw/`:

```text
olist_orders_dataset.csv
olist_order_items_dataset.csv
olist_products_dataset.csv
olist_sellers_dataset.csv
olist_order_payments_dataset.csv
```

### 3. Configure the connection

Use the Supabase **direct connection** string for ingestion (port `5432`) and either direct or pooler for the API. Keep `sslmode=require`.

```env
DATABASE_URL=postgresql+psycopg://postgres.YOUR_PROJECT:YOUR_PASSWORD@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
DATABASE_SCHEMA=public
ALLOWED_TABLES=orders,order_items,products,sellers,order_payments
```

The app normalizes a plain `postgresql://` URL to the async psycopg driver automatically. The loader does the same.

### 4. Load the CSVs

```bash
python scripts/load_olist.py --csv-dir data/raw --truncate
```

The loader:

- normalizes the Olist column typos (`product_name_lenght` → `product_name_length`),
- parses timestamps,
- filters orphan rows that would violate foreign keys,
- bulk-upserts in chunks with `ON CONFLICT DO NOTHING`,
- prints final table counts.

### 5. Restart the API

```bash
uvicorn logisql.api.main:app --reload --port 8000
```

---

## Example questions

- Which product categories generated the most item revenue from delivered orders in 2018?
- Which seller states have the longest average delivery time for delivered orders?
- Which sellers have the highest on-time delivery rate among sellers with at least 20 delivered orders?
- How did monthly order volume and freight value trend between January 2017 and August 2018?
- Which product categories have the highest average freight cost as a percentage of item price?
- Which payment types have the highest average order value?
- What share of delivered orders arrived late, by product category?

---

## Configuration

All settings are environment variables (see [`.env.example`](.env.example)).

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | SQLite demo | SQLAlchemy async URL |
| `DATABASE_SCHEMA` | `public` | PostgreSQL schema to introspect |
| `ALLOWED_TABLES` | five Olist tables | Hard table allowlist for SQLGlot |
| `GROQ_API_KEY` | empty | Groq API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | LLM model |
| `MAX_RETRIES` | `3` | Repair attempts after the initial SQL |
| `DEFAULT_ROW_LIMIT` | `200` | Rows returned by default |
| `MAX_ROW_LIMIT` | `1000` | Hard API cap |
| `QUERY_TIMEOUT_MS` | `15000` | PostgreSQL statement timeout |
| `SCHEMA_CACHE_TTL_SECONDS` | `300` | Schema introspection cache |
| `MAX_CONCURRENT_QUERIES` | `4` | In-process LLM query workers |
| `QUERY_QUEUE_TIMEOUT_SECONDS` | `30` | Wait before returning `429` |
| `CORS_ORIGINS` | localhost UI | Comma-separated browser origins |
| `API_BASE_URL` | `http://localhost:8000` | URL used by Streamlit |
| `LANGCHAIN_TRACING_V2` | `false` | Enable LangSmith |
| `LANGCHAIN_API_KEY` | empty | LangSmith key |
| `LANGCHAIN_PROJECT` | `logisql-agent` | LangSmith project |

---

## API

### `POST /api/v1/query`

```json
{
  "question": "Which product categories generated the most revenue in 2018?",
  "row_limit": 100
}
```

Response shape (abridged):

```json
{
  "request_id": "b0e6...",
  "status": "success",
  "sql": "SELECT ...",
  "headline": "Health & beauty leads 2018 revenue",
  "summary": "...",
  "key_takeaways": ["..."],
  "columns": ["product_category_name", "revenue"],
  "rows": [{"product_category_name": "health_beauty", "revenue": 123456.78}],
  "row_count": 10,
  "truncated": false,
  "chart": {"data": [], "layout": {}},
  "attempt_count": 1,
  "retry_count": 0,
  "attempts": [],
  "node_timings": [],
  "total_ms": 2810.4,
  "model": "llama-3.3-70b-versatile"
}
```

Other endpoints:

- `GET /api/v1/health`
- `GET /api/v1/overview?force=false` — cached dataset KPIs used by the UI
- `GET /api/v1/schema?force=false`
- `GET /api/v1/examples`

`/api/v1/query` is protected by an in-process semaphore (`MAX_CONCURRENT_QUERIES`).
When every worker is busy past `QUERY_QUEUE_TIMEOUT_SECONDS`, the API returns
`429 Too Many Requests` with a `Retry-After` header instead of exhausting the
Groq quota or the event loop.

---

## Safety model

This is a reference implementation, not a claim of absolute security. It uses defense in depth:

1. **Only SELECT-like roots** are accepted (`SELECT`, `WITH`, `UNION`, `INTERSECT`, `EXCEPT`).
2. **AST-level mutation blocking** rejects `INSERT`, `UPDATE`, `DELETE`, DDL, `COPY`, `SET`, `MERGE`, `CALL`, and similar nodes.
3. **Single statement only** — stacked queries are rejected.
4. **Table allowlist** — only configured Olist tables can be referenced.
5. **Schema blocking** — `information_schema`, `pg_catalog`, `auth`, `storage`, etc.
6. **Dangerous function denylist** — `pg_sleep`, file I/O, `dblink`, backend control functions, sequence mutation (`nextval`/`setval`), notification and large-object helpers.
7. **Read-only transaction** — PostgreSQL `SET TRANSACTION READ ONLY`; SQLite `PRAGMA query_only`.
8. **Statement timeout + row cap** — prevents runaway or unbounded reads.
9. **Validated chart spec** — the model cannot inject arbitrary Plotly JSON or HTML.
10. **Secrets stay server-side** — the Streamlit app never sees the database or Groq key.
11. **Non-finite values are sanitized** — `NaN`/`Infinity` cannot break JSON serialization.
12. **Bounded concurrency** — expensive LLM runs queue behind a semaphore.

For a public deployment, also add authentication, per-user rate limiting, query cost budgets, and network-level egress controls. Use a dedicated read-only Supabase role rather than the service role.

---

## Observability

LangGraph/LangChain automatically export traces when these are set:

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_...
LANGCHAIN_PROJECT=logisql-agent
```

Each request gets:

- a request ID in the response and `X-Request-ID` header,
- an `X-Process-Time-Ms` latency header,
- a `run_name` and metadata for LangSmith,
- per-node latency in `node_timings`,
- an `attempts` trail containing generated SQL, validation failures, execution failures, and repairs.

---

## Tests

```bash
pytest -q
ruff check .
```

The suite covers:

- safe/unsafe SQL parsing, allowlists, and the dangerous-function denylist,
- schema introspection against SQLite,
- chart inference and Plotly generation (bar, line, pie, multi-series),
- the full LangGraph repair loop with a fake LLM,
- FastAPI health/schema/overview/query endpoints and latency headers,
- execution sanitization, demo seeding idempotence, loader normalization,
- configuration parsing and the query queue limiter.

---

## Docker

```bash
docker compose up --build
```

- UI: <http://localhost:8501>
- API: <http://localhost:8000>
- Demo SQLite data is stored in the `logisql-data` volume.

For Supabase, set `DATABASE_URL` in your shell or `.env` before `docker compose up`; Compose passes it through to the API.

---

## Deployment

### API (Render / Railway / Fly.io)

- Build command: `pip install .`
- Start command: `uvicorn logisql.api.main:app --host 0.0.0.0 --port $PORT`
- Set `DATABASE_URL`, `GROQ_API_KEY`, `CORS_ORIGINS`, and optionally LangSmith variables.
- Use a read-only database role and a direct/pooled Supabase URL with `sslmode=require`.

### Streamlit Community Cloud

- Repository: this project.
- Main file path: `apps/streamlit_app.py`.
- Python dependencies: `requirements.txt` (included).
- Add `API_BASE_URL=https://your-api.example.com` in Streamlit secrets/env.
- Deploy the API first; the UI only needs the API URL.

---

## Project layout

```text
.
├── apps/streamlit_app.py          # Streamlit UI
├── database/schema.sql            # Supabase/PostgreSQL DDL
├── scripts/load_olist.py          # Olist CSV loader wrapper
├── scripts/seed_demo.py           # Synthetic SQLite seed
├── src/logisql/
│   ├── agent/
│   │   ├── charts.py              # Validated Plotly builder
│   │   ├── graph.py               # LangGraph nodes + routing
│   │   ├── guardrails.py          # SQLGlot AST policy
│   │   ├── llm.py                 # Groq client + parsing
│   │   ├── prompts.py             # Generation/repair/synthesis prompts
│   │   ├── state.py               # Typed agent state
│   │   └── synthesis.py           # Deterministic fallback narrative
│   ├── api/                       # FastAPI app, routes, schemas
│   ├── db/                        # engine, introspector, executor, overview, seed
│   ├── ingest/loader.py           # Supabase CSV ingestion
│   └── config.py                  # Pydantic settings
├── tests/
├── Dockerfile.api
├── Dockerfile.ui
├── docker-compose.yml
└── .dockerignore
```

---

## Limitations & next steps

- Olist has no customer dimension table, so customer geography is not available. The agent uses **seller state** in geographic examples.
- The local demo dataset is synthetic; use Supabase + the Kaggle CSVs for real findings.
- The reference app has no authentication; it has an in-process concurrency limit but no per-user rate limiting. Add both (plus a distributed limiter) before exposing it publicly.
- The chart builder intentionally supports a small, safe set: bar, line, area, scatter, pie.
- Good production extensions: query result caching, per-user history, schema comments/descriptions, semantic column aliases, evaluation harness with golden SQL, and a read-only Supabase role.

---

## Resume bullets

- Built a LangGraph text-to-SQL agent over a five-table Olist warehouse, with schema-aware generation, SQLGlot AST guardrails, read-only execution, and a bounded self-correction loop (max 3 repairs).
- Implemented defense-in-depth SQL safety: single-statement enforcement, table/system-schema allowlists, dangerous-function denylist, read-only transactions, statement timeouts, and row caps.
- Delivered an asyncio FastAPI backend and Streamlit analytics UI with request tracing, per-node latency, retry audit trails, and validated Plotly visualizations.
- Designed dynamic `information_schema` introspection with PK/FK discovery and TTL caching, keeping prompts aligned with the live Supabase schema.
- Added an Olist ingestion pipeline with FK validation, bulk upserts, timestamp normalization, and a zero-setup synthetic demo mode.
- Hardened the API with cached dataset KPI overviews, bounded query concurrency, non-finite result sanitization, and a broader dangerous-function denylist.
- Instrumented every request with LangSmith traces and structured execution metadata for debugging and evaluation.

---

License terms are documented in [`LICENSE`](LICENSE).
