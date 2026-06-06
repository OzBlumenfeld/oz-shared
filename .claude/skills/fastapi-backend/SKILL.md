# FastAPI Backend Skill

When this skill is invoked, write or review FastAPI backend code following the guidelines below.
Apply all rules by default. If the user provides an argument (e.g. `/fastapi-backend review`), focus on that mode.

---

## Language & Runtime

- Python 3.14+. Use `from __future__ import annotations` at the top of every file.
- Enable strict type checking (`mypy --strict` or `pyright` in strict mode).
- Use `uv` for dependency management; never `pip install` directly.

---

## Project Layout

```
src/
  <service>/
    main.py          # app factory only — no routes
    routes/          # one file per domain (users.py, orders.py, …)
    models/          # SQLAlchemy ORM models
    schemas/         # Pydantic request/response schemas
    services/        # business logic, no HTTP concerns
    repositories/    # DB queries, no business logic
    dependencies.py  # FastAPI Depends() providers
    config.py        # settings via pydantic-settings
tests/
  unit/
  integration/
```

**Rule:** Routes call services. Services call repositories. Repositories own all DB access. No raw SQL or ORM queries inside routes or services.

---

## App Factory

```python
# main.py
from __future__ import annotations
from fastapi import FastAPI
from .routes import users, orders

def create_app() -> FastAPI:
    app = FastAPI(title="<service>")
    app.include_router(users.router, prefix="/users", tags=["users"])
    app.include_router(orders.router, prefix="/orders", tags=["orders"])
    return app
```

Never instantiate `FastAPI()` at module level outside the factory — it breaks testing.

---

## Schemas (Pydantic v2)

- Separate request schema (`UserCreate`) from response schema (`UserResponse`). Never expose ORM models directly.
- All fields must be typed. No bare `dict` or `Any` unless the shape is genuinely open.
- Use `model_config = ConfigDict(from_attributes=True)` on response schemas that map from ORM.
- Validate at the boundary; don't re-validate inside services.

```python
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, EmailStr

class UserCreate(BaseModel):
    email: EmailStr
    name: str

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    name: str
```

---

## Routes

- Thin — call a service, return a schema. No business logic, no DB access.
- Always annotate the response model: `@router.get("/", response_model=list[UserResponse])`.
- Use `status.HTTP_201_CREATED` etc. from `fastapi` — never hardcode integers.
- Raise `HTTPException` only in the route layer; services raise domain exceptions.

```python
from __future__ import annotations
from fastapi import APIRouter, Depends, status
from .schemas import UserCreate, UserResponse
from .services import UserService
from .dependencies import get_user_service

router = APIRouter()

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    svc: UserService = Depends(get_user_service),
) -> UserResponse:
    return await svc.create(body)
```

---

## Services

- Pure business logic: validation beyond schema, orchestration, side effects.
- No HTTP types (`Request`, `Response`, `HTTPException`) — raise domain exceptions instead.
- Async by default; use `await` consistently.

---

## Repositories

- One class per aggregate root. Injected via `Depends()`.
- Accept and return domain/schema types, not raw rows.
- All queries go here; no ORM access outside this layer.

---

## Dependencies (`dependencies.py`)

- Use `Depends()` for DB sessions, auth, services, and repositories.
- Session lifetime: one per request via an async generator.

```python
from __future__ import annotations
from collections.abc import AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from .db import async_session_factory
from .repositories import UserRepository
from .services import UserService

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session

def get_user_repo(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(db)

def get_user_service(repo: UserRepository = Depends(get_user_repo)) -> UserService:
    return UserService(repo)
```

---

## Configuration (`config.py`)

- Use `pydantic-settings`. Load secrets from environment or 1Password via `oz_shared.onepassword`.
- One `Settings` singleton; expose via `get_settings()` used in `Depends()`.
- Never use `os.environ` directly in application code.

```python
from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    database_url: str
    secret_key: str

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

---

## Async & Database

- Use `sqlalchemy[asyncio]` + `asyncpg`. Never use the sync `Session` in async routes.
- Wrap mutations in explicit transactions; don't rely on autocommit.
- Use `oz_shared.postgres` for shared connection helpers when available.

---

## Error Handling

- Define domain exceptions in a `exceptions.py` module (`class UserNotFound(Exception): ...`).
- Map domain exceptions to HTTP responses in a single exception handler registered on the app, not scattered across routes.
- Never return `{"error": "..."}` dicts — use `HTTPException` or a structured error schema.

---

## Security

- Never log or return secrets, tokens, or PII.
- Use `python-jose` or `authlib` for JWT; never roll your own crypto.
- Rate-limit auth endpoints; don't rate-limit by IP alone.
- Validate `Content-Type` on mutation endpoints (FastAPI does this automatically with a typed body).
- CORS: list allowed origins explicitly — no wildcard `*` in production.

---

## Testing

- `pytest` + `httpx.AsyncClient` with `ASGITransport` for integration tests; never spin up a real server.
- Use a real test DB (Docker or SQLite in-memory via async engine), not mocked sessions.
- Fixture scope: DB engine at `session`, DB connection at `function`, rollback after each test.
- Unit-test services in isolation by injecting a fake/stub repository.

```python
import pytest
from httpx import AsyncClient, ASGITransport
from src.main import create_app

@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        yield c
```

---

## What to Avoid

- No `app = FastAPI()` at module top level (breaks test isolation).
- No sync route handlers in an async app (`def` instead of `async def`).
- No business logic inside route handlers.
- No ORM models returned directly as responses.
- No `print()` for logging — use `logging.getLogger(__name__)`.
- No `except Exception: pass` — always log and re-raise or convert to a domain exception.
