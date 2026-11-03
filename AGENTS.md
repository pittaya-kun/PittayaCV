# AGENTS.md - Instructions for AI Agents Working on Auto-CV

## Quick Start
```bash
cd /Users/Pittaya/Documents/Craudio/Auto-cv
source .venv/bin/activate  # or: uv venv --python 3.9.6 && source .venv/bin/activate
auto-cv --help             # Verify CLI works
```

## Project Rules (MUST FOLLOW)

### Code Standards
- **Version header** on every file: `# Version: X.Y.Z`, `# Author: Pittaya`
- **SOLID**: SRP (one module = one responsibility), OCP (factories, enums, registry)
- **Type hints** everywhere (Python 3.9: `Optional[str]`, not `str | None`)
- **Docstrings** on all public functions/classes
- **Atomic writes** for file operations (`files.atomic_write`)
- **Retry logic** for DB writes (`storage.sqlite.with_retry`)

### Git
- Commit after each module with message: `feat: module-name vX.Y.Z`
- Author: `Pittaya <pittaya@users.noreply.github.com>`
- Push to `https://github.com/pittaya-kun/Pittaya.git`

### Testing
- Write tests in `tests/` mirroring `src/` structure
- Run: `pytest tests/ -v`
- All tests must pass before commit

## Current Task: Phase 2 - Scrapers

### Next File: `src/auto_cv/scrapers/base.py`
Create abstract `BaseScraper` class with:
- `fetch_page(url)` - requests + retry + rate limit
- `parse_jobs(html)` - abstract, returns `List[Job]`
- `search(query, filters)` - abstract, orchestrates pagination
- Rate limiter: token bucket (configurable per source)
- Session management: headers, cookies, user-agent rotation
- Error handling: retry with exponential backoff

### Scraper Implementation Order
1. `base.py` - Abstract base
2. `remoteok.py` - Simplest (static HTML, global remote)
3. `wellfound.py` - Startups, clean HTML
4. `indeed.py` - Standard job board
5. `linkedin.py` - Needs cookies, anti-bot
6. `glassdoor.py` - Similar to Indeed
7. `gupy.py` - Brazil, Portuguese
8. `vagas_com.py` - Brazil, Portuguese
9. `factory.py` - Registry + factory (OCP)

### Integration Points
- Use `create_job()` factory from `storage.models`
- Save via `JobRepository.upsert()` (unique on source+external_id)
- Log search via `SearchHistoryRepository`
- CLI commands in `cli.py` already exist as placeholders

## Key Modules Reference

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `config` | Settings | `get_settings()`, `create_settings()`, `Settings` |
| `profile.schema` | Profile models | `Profile`, `PersonalInfo`, `Experience`, enums |
| `profile.manager` | Profile I/O | `ProfileManager`, `ProfileInterviewer` |
| `storage.models` | SQLAlchemy models | `Job`, `Application`, `SearchHistory`, `EmbeddingCache`, enums |
| `storage.sqlite` | DB access | `JobRepository`, `ApplicationRepository`, `session_scope` |
| `storage.files` | File I/O | `atomic_write`, `backup_file`, `save_yaml`, `Serializer` registry |

## Common Patterns

### Create Job from Scraped Data
```python
from auto_cv.storage.models import create_job, JobSource
from auto_cv.storage.sqlite import JobRepository

job = create_job(
    source=JobSource.LINKEDIN.value,
    external_id="12345",
    url="https://linkedin.com/jobs/12345",
    title="Python Developer",
    company="Acme Corp",
    location="São Paulo, BR",
    description="...",
    raw_data={"original_html": "..."}
)
with session_scope() as session:
    repo = JobRepository(session)
    repo.upsert(job)
```

### Rate Limiter Usage
```python
from auto_cv.scrapers.base import RateLimiter

limiter = RateLimiter(requests_per_second=0.5)  # 1 req/2s
await limiter.acquire()  # Before each request
```

## Environment
- Python 3.9.6 (pinned)
- `numpy<2` (1.26.4) for torch compatibility
- `fpdf2` imported as `import fpdf`
- `email-validator` required for `EmailStr`

## Files to Read First
1. `CONTEXT.md` - This project's state
2. `PROJECT.md` - Full architecture
3. `ROADMAP.md` - Phase 2 checkpoints
4. `src/auto_cv/storage/models.py` - Job model structure
5. `src/auto_cv/cli.py` - Scrape command placeholders

## Don't Do
- ❌ Use JobSpy (Python 3.10+)
- ❌ Use RenderCV (Python 3.10+)
- ❌ Use Ollama/OpenAI (use Anthropic SDK only)
- ❌ Auto-apply (manual only)
- ❌ Skip version headers
- ❌ Skip atomic writes
- ❌ Commit without tests passing