# NL2SQL Studio

NL2SQL Studio is an end-to-end natural-language-to-SQL system for a read-only SQLite database. It combines hybrid schema retrieval (semantic + keyword), a self-correcting LangGraph agent, and a rich web UI to produce SQL, visualizations, and business-friendly summaries for non-technical users.

## Highlights  

- Hybrid schema retrieval with ChromaDB + BM25 and Reciprocal Rank Fusion.
- Join-path hints from the database foreign-key graph to improve SQL accuracy.
- Self-correcting agent loop with retry caps and safe failure states.
- Read-only SQL enforcement and prompt guardrails.
- Web UI with status stepper, query history, SQL editor, and Plotly charts.
- Backend-only CLI demo for quick testing.

## Architecture Overview

1. **Schema Extraction + Indexing**
   - Extracts table schema, PK/FK info, and sample rows from SQLite.
   - Indexes schema documents into a persistent ChromaDB collection.

2. **Hybrid Retrieval + Reranking**
   - Semantic retrieval using sentence-transformers embeddings.
   - Keyword retrieval using BM25.
   - Results fused with Reciprocal Rank Fusion (RRF) to pick top-k tables.
   - Join-path tables and join hints are added when needed.

3. **LangGraph Agent**
   - `retrieve_schema` -> `generate_sql` -> `execute_sql`.
   - If execution fails, `self_correct` retries up to 3 times.
   - If schema confidence is low, a fallback response is returned early.

4. **Result Interpretation**
   - Auto-selects chart type based on DataFrame shape and types.
   - Summarizes results in 2-3 sentences for business users.

5. **Web UI**
   - Single-page app (HTML/CSS/JS) served by Flask.
   - Shows status updates, SQL editor, charts, and data tables.

## Database Schema (Enterprise HR Demo)

The demo database lives at `data/enterprise.db` and includes these tables:

- `locations`
- `departments`
- `employees` (includes `manager_id` for hierarchy)
- `salaries`
- `projects`
- `project_assignments`
- `performance_reviews`
- `trainings`
- `employee_trainings`

The seed data includes realistic distributions for locations, departments, employees, salaries, projects, training completions, and performance reviews.

## Quickstart

### 1) Install Dependencies

```bash
pip install -r requirements.txt
```

### 2) Create the Demo Database

```bash
python setup_db.py
```

### 3) Run the Web App

```bash
python app.py
```

Open the UI at:

```
http://localhost:8000
```

The app auto-builds the ChromaDB index if it is missing.

### 4) Run the CLI Demo (Optional)

```bash
python demo_backend.py "List the top 5 employees with the highest-rated performance reviews."
```

## Configuration

Environment variables are loaded from `.env` if present:

- `NL2SQL_LLM_PROVIDER` (default: `gemini`)
- `GEMINI_API_KEY`
- `GEMINI_MODEL` (default: `gemini-3.1-flash-lite`)
- `GROQ_API_KEY`
- `GROQ_MODEL` (default: `llama-3.1-70b-versatile`)
- `PORT` (default: `8000`)

The UI also lets users override the API key per request.

## API Endpoints

### `POST /api/query`

Runs the agent and returns the final response payload.

**Request body:**

```json
{
  "question": "Show total project budget by department",
  "provider": "gemini",
  "api_key": "...optional...",
  "top_k": 3,
  "sql_override": "SELECT ..."
}
```

**Response fields (high level):**

- `status`, `status_updates`, `status_meta`
- `sql_query`
- `db_result` (columns, rows, row_count)
- `figure` (Plotly JSON)
- `figures` (all chart types)
- `summary`
- `schema_context` (truncated)
- `error_type`, `error_message`, `error_trace` (when applicable)

### `POST /api/query/stream`

Server-Sent Events (SSE) endpoint that streams node updates and emits a final `done` event with the same payload fields as `/api/query`.

## Prompt Guardrails and Safety

- **Read-only DB:** SQLite is opened with `mode=ro`.
- **Forbidden SQL:** Blocks `DROP`, `DELETE`, `UPDATE`, `INSERT`.
- **Prompt guardrails:** Detects basic prompt injection and PII (email/phone).
- **Fallback:** If schema confidence is too low, the agent returns a friendly mismatch message without generating SQL.

## Project Structure

```
.
├── agent.py              # LangGraph agent + self-correction
├── app.py                # Flask API + static UI server
├── demo_backend.py       # CLI demo runner
├── retriever.py          # Schema extraction + hybrid retrieval + RRF
├── setup_db.py           # SQLite schema + seed data
├── visualizer.py         # Plotly charts + LLM summaries
├── requirements.txt
├── web/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── chroma_store/         # ChromaDB persistent store
└── data/
    └── enterprise.db     # SQLite demo database
```

## Example Questions

- Which department has the highest average salary?
- Show total project budget by department.
- How many employees are on leave by department?
- List active projects with assigned employee count.
- Average base salary by job title.
- Top 5 cities by employee count.

## Troubleshooting

- **No results / empty tables:** Run `python setup_db.py` to rebuild the database.
- **Slow startup:** The first run builds the ChromaDB index; subsequent runs are faster.
- **LLM errors:** Ensure the selected provider API key is set via `.env` or the UI.
- **SQL blocked:** The system rejects write operations by design.


