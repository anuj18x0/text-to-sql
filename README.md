# 🧠 Text-to-SQL Agent

💬 Ask a question in plain English. ⚡ Watch SQL generate in real-time. 📊 Get instant results and charts. No SQL knowledge required.

> **An AI-powered analytical agent** that converts natural language to SQL using RAG, streams responses in real-time via SSE, and self-heals from its own errors.

---

## 📚 Table of Contents

1. [🤔 What Does This Project Do?](#1-what-does-this-project-do)
2. [😬 The Problem With "Typical" Text-to-SQL](#2-the-problem-with-typical-text-to-sql)
3. [🚀 Key Features](#2-key-features)
4. [🏗️ Architecture](#3-architecture)
5. [🔄 How a Query Works (Pipeline)](#4-how-a-query-works-pipeline)
6. [🛠️ Core Techniques](#5-core-techniques)
7. [✅ What It Can (and Cannot) Do](#6-what-it-can-and-cannot-do)
8. [📁 Project Structure](#7-project-structure)
9. [🗄️ Database Schema](#8-database-schema)
10. [🚀 Quick Start](#9-quick-start)
11. [⚙️ Environment Variables](#10-environment-variables)

SPECIAL THANKS : techwithpratik

---

## 1. 🤔 What Does This Project Do?

This system lets a non-technical user type a question like:

> *"Find the top 5 product categories that have an average review score above 4.0 and at least 100 orders."*

…and automatically:

1. 🗺️ Retrieves relevant database schema using **RAG** (Retrieval-Augmented Generation).
2. ✍️ Asks **Gemini** to write the correct PostgreSQL query — **streamed live** to the UI.
3. ⚡ Executes that SQL against a real **PostgreSQL** database.
4. 🩺 **Self-heals** if the SQL fails — catches the error, fixes the query, and retries automatically.
5. 📊 Returns results in a clean table in the browser.

The underlying database is a **star-schema** data warehouse built on the [Olist public dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), containing real Brazilian e-commerce orders, products, sellers, customers, and reviews.

---

## 2. 😬 The Problem With "Typical" Text-to-SQL

When someone first tries to build a text-to-SQL system, the obvious approach is usually:

> *"I'll just paste the entire database schema into the LLM prompt and ask it to write a query."*

This works fine for toy databases with 3–4 tables. In the real world, it breaks down fast 💥:

| Problem | Why it happens |
|---|---|
| 🌊 **Context window overflow** | A real warehouse can have 50–200 tables. The full schema — table names, column names, types, foreign keys — can easily exceed the LLM's context limit (even GPT-4o's 128k tokens). |
| 📢 **Noise drowns out signal** | Even if it fits, flooding the prompt with irrelevant tables confuses the model. It might join to the wrong table or use the wrong column because it's overwhelmed. |
| 🔍 **Business meaning is lost** | Column names like `order_total_usd` or `is_active_member` don't tell the LLM *how* to use them correctly. Should `order_total_usd` be summed or averaged? Should you filter on `order_status = 'delivered'` first? The schema alone doesn't say. |
| 👻 **Hallucinated SQL** | Without enough context, the LLM invents column names or table relationships that don't exist, producing queries that fail at runtime. |
| 🚨 **No safety guardrails** | A naive implementation has no check to stop the LLM from generating `DELETE` or `DROP TABLE` statements if the user's question is phrased ambiguously. |

**This project solves all of these problems. 🎯**

Instead of dumping the whole schema into the prompt, we use three key techniques:

### 📖 Technique 1: Semantic Layer (the "data dictionary")

Every table and column is annotated with business-friendly descriptions in [`agent/semantic_layer.py`](agent/semantic_layer.py). For example:

```
order_total_usd: "Final post-tax revenue in USD for this line item.
                  Always use this for GMV calculations.
                  Never use freight_value_usd as a revenue proxy."
```

This tells the LLM *how* to use each column, not just *what type* it is. Think of it as a data dictionary that the LLM reads before writing SQL. 📚

### 🔎 Technique 2: RAG — Retrieval-Augmented Generation

Instead of sending all table descriptions at once, we:

1. **At startup:** Embed every table description into a vector database (ChromaDB) using OpenAI embeddings. Each table becomes a point in high-dimensional space. 📌
2. **At query time:** Embed the user's question using the same embedding model. Find the 3 most *semantically similar* table descriptions using cosine similarity. Inject *only those 3 tables* into the LLM prompt. 🎯

The user asks about "revenue by category" → we retrieve `fact_orders` and `dim_products` → the LLM only sees those two tables → cleaner, more accurate SQL. ✨

### 💡 Technique 3: Few-Shot Examples

The prompt includes curated question→SQL example pairs (stored in [`agent/few_shot_examples.yaml`](agent/few_shot_examples.yaml)). These teach the LLM the exact SQL dialect, join patterns, and aggregation idioms expected for *this specific database*, acting as in-context learning.

### 🛡️ Technique 4: HITL Safety Guard

Before any SQL is executed, a Human-In-The-Loop (HITL) guard scans for dangerous keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`, etc.). If found, execution is blocked and the user must explicitly type `CONFIRM` in a modal before anything runs. Pure `SELECT` queries pass through automatically. 🔒

---

## 3. 🚀 Key Features

### ⚡ Real-Time SQL Streaming (SSE)
The SQL query appears character-by-character in the chat — no more staring at a blank screen. Powered by **Server-Sent Events** with a typewriter effect.

### 🩺 Self-Healing Agent
If Gemini generates broken SQL (wrong column, bad syntax), the agent **catches the error**, sends it back to Gemini with the error message and schema context, and retries — up to 2 times. Most errors are fixed automatically without user intervention.

### 🧠 Multi-Turn Conversational Context
The agent remembers your last 3 questions. Ask *"Show me the top 5 sellers by revenue"* followed by *"What about just in São Paulo?"* — it understands the context.

### 🔎 RAG-Powered Schema Retrieval
Only the 3 most relevant tables are injected into the prompt — not the entire schema. This keeps the LLM focused and reduces hallucinations.

### 💡 Few-Shot Learning (PostgreSQL-Native)
Curated Q→SQL examples teach the model the exact dialect, join patterns, and aggregation idioms for this database. All examples use proper PostgreSQL syntax.

### 🛡️ HITL Safety Guard
Write operations (`INSERT`, `UPDATE`, `DELETE`, `DROP`) are blocked and require explicit human confirmation via a modal dialog.

### 📊 Auto-Visualization (Extensible)
A built-in `ChartDisplay` component using **Recharts** supports Bar, Line, and Pie charts. The visualization engine can be enabled via a single flag to auto-suggest the best chart type.

### ⏱️ Semantic Caching
Repeated questions are served from a 1-hour in-memory cache — **0ms latency** on cache hits.

### 🦴 Skeleton Loader
An animated shimmer skeleton appears instantly when you press Enter, filling the gap while the AI retrieves your schema.

---

## 4. 🏗️ Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                     Browser (React + Vite)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐    │
│  │  ChatWindow  │  │  SqlDisplay  │  │   ResultsTable    │    │
│  │ (SSE stream) │  │ (live SQL)   │  │  (data grid)      │    │
│  └──────┬───────┘  └──────────────┘  └───────────────────┘    │
│         │ POST /api/query/stream (SSE)                          │
└─────────┼─────────────────────────────────────────────────────┘
          │
┌─────────▼─────────────────────────────────────────────────────┐
│                   FastAPI Backend (Python)                       │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              stream_query() — SSE Pipeline              │    │
│  │                                                         │    │
│  │  Question                                               │    │
│  │     │                                                   │    │
│  │     ▼                                                   │    │
│  │  [1] Cache Check (1h semantic cache)                    │    │
│  │     │                                                   │    │
│  │     ▼                                                   │    │
│  │  [2] retriever.py ──► ChromaDB (local vector store)     │    │
│  │     │   (embed question, find top-3 relevant tables)    │    │
│  │     ▼                                                   │    │
│  │  [3] Build prompt (schema + few-shots + history)        │    │
│  │     │                                                   │    │
│  │     ▼                                                   │    │
│  │  [4] Gemini (streaming) ──► SSE chunks                  │    │
│  │     │   (SQL streams live to frontend)                  │    │
│  │     ▼                                                   │    │
│  │  [5] HITL guard (block writes)                          │    │
│  │     │                                                   │    │
│  │     ▼                                                   │    │
│  │  [6] Execute SQL ──► PostgreSQL                         │    │
│  │     │   ❌ Error? → Self-Heal (up to 2 retries)        │    │
│  │     │   ✅ Success? → Stream final_result               │    │
│  │     ▼                                                   │    │
│  │  [7] Log to query_log + Cache response                  │    │
│  └────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────┘
          │
┌─────────▼──────────────────────────┐
│      ChromaDB (local vector store)  │
│  Table descriptions stored as       │
│  vectors in ./db/chroma_store/      │
└─────────────────────────────────────┘
          │
┌─────────▼──────────────────────────┐
│     PostgreSQL (local or cloud)     │
│  fact_orders, dim_users,            │
│  dim_products, dim_sellers,         │
│  dim_geography, dim_reviews,        │
│  query_log                          │
└─────────────────────────────────────┘
```

---

## 5. 🔄 How a Query Works (Pipeline)

Here is exactly what happens when a user types *"Which states have the most canceled orders?"* and hits Enter:

**Step 1 → Skeleton Loader 🦴**
The UI instantly shows an animated shimmer skeleton while the backend works.

**Step 2 → Cache Check ⚡**
The normalized question is checked against the 1-hour in-memory cache. If found, the cached result is streamed immediately (0ms).

**Step 3 → Embed & Retrieve (RAG) 🗂️**
The question is embedded using Gemini's embedding model and compared against ChromaDB vectors. The 3 most relevant table schemas are returned — in this case `fact_orders` and `dim_users`.

**Step 4 → Build the Prompt 📝**
A `ChatPromptTemplate` is assembled with the retrieved schemas, PostgreSQL-native few-shot examples, and the last 3 conversational turns.

**Step 5 → Stream SQL via Gemini 🤖**
The prompt is sent to Gemini with `temperature=0`. SQL tokens are streamed back in real-time via SSE — the user sees each character appear live.

**Step 6 → HITL Safety Check 🛡️**
The finalized SQL is scanned for dangerous keywords. `SELECT` queries pass through automatically.

**Step 7 → Execute with Self-Healing 🩺**
The SQL runs against PostgreSQL. If it fails (e.g., bad column name), the agent catches the error, sends it back to Gemini with the schema context, and gets a corrected query. Up to 2 retries.

**Step 8 → Log, Cache & Stream 📦**
The question, SQL, latency, and tables used are logged. The response is cached for 1 hour. The final result (SQL + data) is streamed to the frontend.

---

## 6. 🛠️ Core Techniques

### 📖 Semantic Layer (Data Dictionary)
Every table and column is annotated with business-friendly descriptions in [`agent/semantic_layer.py`](agent/semantic_layer.py).

### 🔎 RAG — Retrieval-Augmented Generation
Only the most relevant tables are injected into the prompt, keeping the LLM focused and reducing hallucinations.

### 💡 Few-Shot Examples (PostgreSQL-Native)
Curated examples in [`agent/few_shot_examples.yaml`](agent/few_shot_examples.yaml) use proper PostgreSQL syntax (`TO_CHAR`, `EXTRACT`, repeated aggregates in `HAVING`).

### 🛡️ HITL Safety Guard
Dangerous SQL is blocked and requires explicit human confirmation via a modal.

### 🩺 Self-Healing Retry Loop
Failed SQL is automatically sent back to Gemini with the error message for correction.

---

## 7. ✅ What It Can (and Cannot) Do

### ✅ Can Do

- 💬 Answer any analytical question about the Olist e-commerce dataset in plain English.
- 💰 Revenue analysis: total, by category, by seller, by month, by state.
- 👥 Customer analysis: active members, geographic distribution, top spenders, cohorts.
- 🏪 Seller analysis: rankings, geographic distribution, freight costs.
- 📦 Order analysis: status breakdown, cancellation rates, monthly trends.
- ⭐ Review/NPS analysis: average scores by category, complaint rates.
- 🔀 Complex queries: multi-table joins, CTEs (`WITH` clauses), window functions.
- 🗣️ Explain what SQL it generated and why.
- ⚡ Stream SQL generation in real-time — no blank-screen waiting.
- 🩺 Automatically recover from SQL errors (self-healing with up to 2 retries).
- 🗣️ Understand follow-up questions using multi-turn conversational context.
- 💰 Revenue, customer, seller, order, and review analysis with complex joins and CTEs.
- 🚧 Block dangerous write operations and ask for human confirmation.
- 📊 Render data as Bar, Line, or Pie charts (extensible).

### ❌ Cannot Do

- 🚫 Modify data without explicit human approval.
- 🔒 Query tables outside the defined semantic schema.
- 🌐 Answer questions about data not in the Olist dataset.
- 🎲 Guarantee 100% correct SQL — LLM output is probabilistic. Always review generated SQL.

---

## 8. 📁 Project Structure

```
text-to-sql/
│
├── agent/                      # Core AI pipeline
│   ├── sql_chain.py            # SSE streaming pipeline: question → SQL → results
│   ├── retriever.py            # RAG: embed question, query ChromaDB
│   ├── semantic_layer.py       # Business descriptions for every table/column
│   ├── build_index.py          # One-time script: embed schema into ChromaDB
│   ├── hitl_guard.py           # Safety: block write SQL, require human approval
│   └── few_shot_examples.yaml  # PostgreSQL-native Q→SQL examples
│
├── api/                        # FastAPI web server
│   ├── main.py                 # App factory, CORS, error handling
│   └── routes/
│       ├── query.py            # POST /api/query/stream — SSE streaming pipeline
│       ├── schema.py           # GET /api/schema — returns table descriptions
│       └── health.py           # GET /api/health — liveness check
│
├── db/                         # Database & vector store clients
│   ├── postgres_client.py      # PostgreSQL engine (Cloud/Local)
│   ├── chroma_client.py        # ChromaDB client (Cloud/Local)
│   └── chroma_store/           # Local ChromaDB persistence
│
├── model/                      # SQLAlchemy ORM models
│   ├── database.py             # Engine + session factory
│   └── schema.py               # Table definitions (star schema + query_log)
│
├── frontend/                   # React + TypeScript + Vite UI
│   └── src/
│       ├── App.tsx             # Root component
│       ├── api.ts              # Streaming HTTP client
│       └── components/
│           ├── ChatWindow.tsx       # SSE stream reader + typewriter effect
│           ├── SqlDisplay.tsx       # Syntax-highlighted SQL with latency badge
│           ├── ResultsTable.tsx     # Pageable results grid
│           ├── ChartDisplay.tsx     # Recharts-based auto-visualization
│           ├── SkeletonLoader.tsx   # Animated shimmer loading state
│           ├── SchemaExplorer.tsx   # Browse available tables/columns
│           └── ApprovalModal.tsx    # HITL confirmation dialog
│
├── data/
│   ├── raw/                    # Raw Olist CSV files
│   └── seed.py                 # Load CSVs → PostgreSQL (run once)
│
├── infra/                      # Deployment scripts
├── requirements.txt            # Python dependencies
└── .env.example                # Copy to .env and fill in your keys
```

---

## 9. 🗄️ Database Schema

The database uses a **star schema** — a design pattern common in data warehouses where one central "fact" table holds measurable events, and multiple "dimension" tables hold descriptive attributes. ⭐

```
                    ┌─────────────┐
                    │  dim_users  │
                    │  user_id PK │
                    │  city       │
                    │  state      │
                    └──────┬──────┘
                           │ FK
┌──────────────┐    ┌──────▼────────────┐    ┌───────────────┐
│ dim_products │    │   fact_orders     │    │  dim_sellers  │
│ product_id PK│◄───│   order_id PK     │───►│  seller_id PK │
│ category_name│    │   user_id FK      │    │  seller_city  │
│ photos_qty   │    │   product_id FK   │    │  seller_state │
└──────────────┘    │   seller_id FK    │    └───────────────┘
                    │   order_total_usd │
                    │   order_status    │    ┌───────────────┐
                    │   created_at      │───►│  dim_reviews  │
                    └───────────────────┘    │  review_id PK │
                                             │  order_id FK  │
                    ┌───────────────────┐    │  review_score │
                    │  dim_geography    │    └───────────────┘
                    │  geo_id PK        │
                    │  zip_code_prefix  │
                    │  city, state      │
                    │  lat, lng         │
                    └───────────────────┘
```

---

## 10. 🚀 Quick Start

### Prerequisites

- 🐍 Python 3.11+
- 🟢 Node.js 18+
- 🐘 PostgreSQL 14+ (local or cloud)
- 🔑 A Google Gemini API key

### 1. Clone and install Python dependencies

```bash
git clone https://github.com/anuj18x0/text-to-sql.git
cd text-to-sql
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# ✏️ Edit .env and set your GEMINI_API_KEY
```

### 3. Set up PostgreSQL 🐘

Create the `olist` database and seed it with the Olist dataset:

```bash
# Create the database
createdb olist

# Seed the data
python -m data.seed
```

### 4. Build the vector index 🔢

This embeds all table descriptions into ChromaDB. Run once, or re-run whenever you update `semantic_layer.py`:

```bash
python -m agent.build_index
```

### 5. Start the API server 🖥️

```bash
uvicorn api.main:app --reload --port 8000
```

### 6. Start the frontend 🎨

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser and start asking questions! 🎉

---

## 11. ⚙️ Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | *(required)* | Your Google Gemini API key. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | The LLM model used for SQL generation. |
| `DB_MODE` | `local` | Database mode: `local` (PostgreSQL) or `cloud` (Supabase). |
| `DATABASE_LOCAL_URL` | `postgresql://postgres:[password]@localhost:5432/db-name` | Local PostgreSQL connection string. |
| `CHROMA_MODE` | `local` | ChromaDB mode: `local` (PersistentClient) or `cloud` (CloudClient). |
| `CHROMA_PERSIST_DIR` | `./db/chroma_store` | Directory where ChromaDB persists vector embeddings. |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model used for RAG retrieval. |
| `LOG_LEVEL` | `INFO` | Python logging level. |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins. Set to your domain in production. |
