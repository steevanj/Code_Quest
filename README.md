# Backend Forge

Learn Django by building a real e-commerce backend, and see what every line changes.

Write models, serializers, views and URLs in the editor, and the platform shows the effect:

- **Schema**: a live ER diagram. Tables and relationships appear as a dashed *preview* while you type, then turn solid once a real migration applies them.
- **Request flow**: send a request through *your* code and watch it move through URL resolver → view → serializer → SQL → response. The editor highlights each line as it runs. Every SQL query is listed, and N+1 patterns are flagged.
- **Store**: a storefront built from the rows your models actually stored. In the cart mission, "Add to cart" calls your own API.
- **Database**: the migrations you generated, the SQL Django ran, and every table's rows.
- **Mentor**: click any line to see what it does, why it's needed, what breaks without it, and a short quiz question.

There are 10 missions across three playable phases (Foundation, Database & ORM, REST API), building one continuous app from `GET /api/products/` up to a cart API with nested serializers, ViewSets and stock validation. Phases 4–6 (auth, testing, deployment) appear on the roadmap.

```
backend/    Django + DRF: code analyzer, curriculum, sandbox runner
frontend/   React + TypeScript + Vite: Monaco, React Flow, Framer Motion
```

## Run it

You need Python 3.10+ and Node 18+.

**Backend** (http://127.0.0.1:8000):

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python manage.py runserver
```

**Frontend** (http://localhost:5173), in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to Django.

**Tests:**

```powershell
cd backend
.venv\Scripts\python manage.py test
```

The mission tests run every reference solution through the real sandbox. Each solution must pass all of its checks, and each mission's starting code must not.

## How it works

Every part of the platform is built on one rule: **preview vs. verified**.

| Level | When | How | UI |
|---|---|---|---|
| Preview | while typing (debounced) | `analyzer/engine.py` parses the four files with Python's `ast`. It extracts models, fields, relations, serializers, views and routes, and reports diagnostics worded like the errors Django would raise. | dashed tables, hollow check icons |
| Verified | Make migrations / Send / Run checks | `runner/worker.py` starts a fresh Python process with a minimal Django project around the learner's `store` app, then runs real `makemigrations`/`migrate`, real requests through Django's test client, or the mission checks. | solid tables, traced lifecycle, filled check icons |

- **Mentor explanations** come from a deterministic knowledge base (`analyzer/explain.py`) fed by the analyzer's facts. No LLM is involved, so explanations never invent behavior.
- **Request traces** come from probes installed in the worker: DRF `is_valid()`, `save()` and `.data`, plus Django's `connection.execute_wrapper` for SQL. Together they record the real order of events.
- **Applied schema** is read straight from the sandbox SQLite database with `PRAGMA` queries and compared column by column with the preview.
- **Mission checks** are declarative (`missions/curriculum.py`). The analyzer previews them; the worker verifies them in a throwaway copy of the learner's project, so their own database is never touched.

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/missions/` | curriculum (phases, missions, starting and reference code) |
| POST | `/api/analyze/` | static analysis `{files, mission_id}` |
| POST | `/api/missions/<id>/check/` | verify a mission `{session, files}` |
| GET | `/api/sandbox/state/?session=` | applied schema, rows, migrations |
| POST | `/api/sandbox/migrate/` | makemigrations + migrate |
| POST | `/api/sandbox/request/` | traced HTTP request `{method, path, body}` |
| POST | `/api/sandbox/seed/` | insert sample catalog data |
| POST | `/api/sandbox/reset/` | delete the session's database and migrations |

## Security note

The sandbox gives each job its own process, a throwaway directory and a timeout (`FORGE_RUNNER_TIMEOUT`, 25 s by default). **It is not a security boundary.** Learner code runs with the same permissions as the Django server. That's fine on your own machine. Before hosting this for other people, run `runner/worker.py` inside a container or microVM with no network access and no host credentials (for example gVisor, Firecracker, or a locked-down Docker container per job).

## Next steps

- Phases 4–6: JWT auth and ownership permissions, checkout with `transaction.atomic()` and `select_for_update()`, test suites, caching, Docker/CI deployment.
- An optional LLM mentor for open-ended questions, given the analyzer's structured facts as context.
- A hardened, containerized runner; PostgreSQL in the sandbox so types match production.
- Accounts and server-side progress (progress is currently stored in browser localStorage).
sd
