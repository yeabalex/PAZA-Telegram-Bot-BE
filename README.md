# Paza Event Bot Backend

FastAPI asynchronous backend server and automated ingestion engine for Paza Event Bot.

> **Note**: For complete documentation, architecture diagrams, and full-stack setup instructions, please refer to the [Root README](../README.md).

## Quick Start

### 1. Environment Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Database Initialization

```bash
createdb addis_event_db
psql -d addis_event_db -f schema.sql
python seed_interests.py
```

### 3. Running Development Server

```bash
uvicorn app.main:app --reload --port 8000
```

- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

### 4. Running Ingestion Pipeline Manually

```bash
python run_pipeline_gateway.py
```
