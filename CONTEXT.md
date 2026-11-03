# Auto-CV - Context for Continuing Development

## Project Overview
Open-source, local-first automated job search & CV generation system. Scrapes job boards, matches against user profile using local embeddings + optional LLM reranking, generates tailored CVs. No auto-apply. Free, token-efficient, runs via CLI. Uses Anthropic SDK with user's Claude Code subscription.

## Current State (Completed Phases 0-1)

### Done
- **Phase 0**: Planning - `PROJECT.md` (600+ lines), `ROADMAP.md` (6 phases)
- **Phase 1**: Foundation
  - `src/auto_cv/config.py` v1.0.0 - Pydantic Settings, computed fields, factory
  - `src/auto_cv/profile/schema.py` v1.0.0 - Profile models, enums, cross-validation, factories
  - `src/auto_cv/profile/manager.py` v1.0.0 - ProfileManager, ProfileInterviewer, atomic writes
  - `src/auto_cv/storage/models.py` v1.0.0 - SQLAlchemy models (Job, Application, SearchHistory, EmbeddingCache)
  - `src/auto_cv/storage/sqlite.py` v1.0.0 - WAL engine, repositories, retry decorator
  - `src/auto_cv/storage/files.py` v1.0.0 - Atomic writes, backups, serializer registry (OCP)
  - `src/auto_cv/cli.py` v1.0.0 - Typer + Rich CLI with all commands

### Tested & Working
```bash
auto-cv init --minimal          # Creates profile.yaml
auto-cv profile show            # Rich table output
auto-cv profile validate        # ValidationResult with warnings/errors
auto-cv hunt --dry-run          # Pipeline demo (no scrapers yet)
auto-cv list jobs               # Empty table (no jobs scraped)
auto-cv status                  # Kanban view
auto-cv config show             # Current settings
```

## Next: Phase 2 - Scrapers

### Files to Create (in order)
1. `src/auto_cv/scrapers/base.py` - BaseScraper abstract class (rate limit, retry, session)
2. `src/auto_cv/scrapers/linkedin.py` - LinkedIn (requests + optional cookies)
3. `src/auto_cv/scrapers/indeed.py` - Indeed
4. `src/auto_cv/scrapers/glassdoor.py` - Glassdoor
4. `src/auto_cv/scrapers/gupy.py` - Gupy (Brazil)
5. `src/auto_cv/scrapers/vagas_com.py` - Vagas.com (Brazil)
6. `src/auto_cv/scrapers/wellfound.py` - Wellfound (startups)
7. `src/auto_cv/scrapers/remoteok.py` - RemoteOK (global remote)
8. `src/auto_cv/scrapers/factory.py` - Factory + registry (OCP)

### Scraper Requirements
- **No JobSpy** (requires Python 3.10+)
- Custom: `requests` + `BeautifulSoup` + `Playwright` (for JS-heavy sites)
- Rate limiting: configurable per source (default 1 req/2s)
- Retry: exponential backoff with tenacity
- Output: `Job` model instances via factory
- Handle pagination, anti-bot (headers, cookies, delays)

## Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| Python 3.9 | JobSpy/RenderCV need 3.10+, we use fpdf2 + custom scrapers |
| SQLite + WAL | Local-first, no server, concurrent reads |
| sentence-transformers (all-MiniLM-L6-v2) | Local embeddings, no API cost, 384 dims |
| Anthropic SDK (Claude Code sub) | User's subscription, no extra cost, token-efficient |
| fpdf2 (import as `fpdf`) | PDF generation, Python 3.9 compatible |
| Typer + Rich | Modern CLI, tables, panels, progress |
| Pydantic Settings + env | Config validation, computed fields |
| Atomic writes (temp + rename) | No corruption on crash |
| Serializer registry (OCP) | Easy add TOML, pickle later |
| Version headers on all files | Traceability |

## Project Structure
```
Auto-cv/
├── PROJECT.md          # Architecture doc
├── ROADMAP.md          # 6-phase plan
├── CONTEXT.md          # This file
├── pyproject.toml      # Deps, Python 3.9
├── src/auto_cv/
│   ├── __init__.py
│   ├── config.py
│   ├── cli.py
│   ├── profile/
│   │   ├── __init__.py
│   │   ├── schema.py
│   │   └── manager.py
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── sqlite.py
│   │   └── files.py
│   └── scrapers/       # ← NEXT TO CREATE
│       ├── __init__.py
│       ├── base.py
│       ├── linkedin.py
│       ├── indeed.py
│       ├── glassdoor.py
│       ├── gupy.py
│       ├── vagas_com.py
│       ├── wellfound.py
│       ├── remoteok.py
│       └── factory.py
└── tests/              # pytest (to create)
```

## Commands to Run
```bash
# Setup
cd /Users/Pittaya/Documents/Craudio/Auto-cv
uv venv --python 3.9.6
source .venv/bin/activate
uv pip install -e ".[dev]"

# Test CLI
auto-cv --help
auto-cv init --minimal
auto-cv profile validate

# Run tests (when created)
pytest tests/ -v
```

## Dependencies (pyproject.toml)
```toml
[project]
requires-python = ">=3.9,<3.10"
dependencies = [
    "typer[all]>=0.9",
    "rich>=13.7",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "sqlalchemy>=2.0",
    "sentence-transformers>=3.0",
    "fpdf2>=2.7",
    "anthropic>=0.25",
    "playwright>=1.40",
    "beautifulsoup4>=4.12",
    "requests>=2.31",
    "tenacity>=8.2",
    "pyyaml>=6.0",
    "email-validator>=2.1",
    "numpy<2",  # 1.26.4 for torch compat
]
```

## Memory Files (Persistent)
Location: `.claude/projects/-Users-Pittaya-Documents-Craudio-Auto-cv/memory/`
- `project-autocv-architecture.md` - Architecture decisions
- `feedback-solid-principles.md` - SRP/OCP enforcement
- `feedback-version-headers.md` - Version header convention

## ROADMAP.md Phases
| Phase | Focus | Status |
|-------|-------|--------|
| 0 | Planning | ✅ Done |
| 1 | Foundation | ✅ Done |
| 2 | Scrapers | 🔄 Next |
| 3 | Matching (embeddings + LLM) | ⏳ |
| 4 | CV Generation (PDF/MD) | ⏳ |
| 5 | Polish + Skill + Docs | ⏳ |
| 6 | Brazilian scrapers (post-MVP) | ⏳ |

## Git
- Repo: https://github.com/pittaya-kun/Pittaya.git
- Last commit: `55cd668` (CLI v1.0.0)
- Author: Pittaya (all files)

## How to Continue
1. Read `PROJECT.md` for full architecture
2. Read `ROADMAP.md` for Phase 2 checkpoints
3. Start with `src/auto_cv/scrapers/base.py` - abstract base class
4. Implement scrapers one by one, test each
5. Integrate with `cli.py` scrape commands
6. Run `auto-cv hunt` end-to-end

## Risks/Notes
- LinkedIn/Indeed may block automated requests → need cookies/headers rotation
- Playwright adds browser dependency → optional, only for JS sites
- Gupy/Vagas.com need Portuguese parsing
- RemoteOK/Wellfound are simpler (API-like HTML)
- Keep rate limits conservative to avoid bans