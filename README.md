# Nova AI

Next-generation AI workspace platform — FastAPI backend + React/Vite frontend, packaged for Docker so any team member can run it with one command.

## Quick start (Docker — recommended)

> Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/Mac) or Docker Engine (Linux). Git is required to clone.

1. Clone the repository:

   ```bash
   git clone https://github.com/rakeshkumartripathy629/NOVA-AI-AGent.git
   cd NOVA-AI-AGent
   ```

2. Create your environment file and fill in your own keys:

   ```bash
   cp .env.example .env
   ```

   At minimum set `GEMINI_API_KEY` (get one free at https://aistudio.google.com/apikey) and change `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD`, and the SMTP values.

3. Build and start everything:

   ```bash
   docker compose up --build
   ```

   The first build takes a while (AI/ML dependencies). Subsequent starts are fast.

4. Open the app:

   - Frontend (UI): http://localhost:3000
   - Backend API docs (Swagger): http://localhost:8000/docs
   - MinIO console (file storage): http://localhost:9001 (`minioadmin` / `minioadmin`)

5. Login with the admin account from your `.env` (default `admin@nova-ai.com` / the `FIRST_SUPERUSER_PASSWORD` you set).

### Useful commands

```bash
docker compose up --build      # start (first time)
docker compose up -d           # start in background
docker compose down            # stop (keeps data)
docker compose down -v         # stop and wipe all data (fresh start)
docker compose logs -f backend # follow backend logs
```

### Services started by Docker Compose

| Service   | Port(s)    | Purpose                          |
|-----------|-----------|----------------------------------|
| frontend  | 3000       | React UI (nginx)                 |
| backend   | 8000       | FastAPI + migrations             |
| db        | 5432*      | PostgreSQL (data stored in volume) |
| redis     | 6379*      | Cache / Celery broker            |
| qdrant    | 6333*      | Vector database (RAG)            |
| minio     | 9000/9001  | File storage (S3-compatible)     |

\* Database, Redis, and Qdrant are only reachable inside the Docker network; only frontend, backend, and MinIO are published to the host.

## Local development (without Docker)

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows: .venv\Scripts\activate.bat
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

The frontend proxies `/api` and `/ws` to `http://localhost:8000`.

## Environment variables

See `.env.example` for the full list with comments. Never commit a real `.env` file — it contains secrets (the repo's `.gitignore` already excludes it).

## License

MIT
