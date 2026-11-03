# Auto-CV - Documentação do Projeto

> **Automatizador de busca de vagas + geração de CV personalizado**
> *Open source, local-first, zero custos, compartilhável*

---

## 1. Visão Geral

### Objetivo
Criar uma ferramenta CLI/skill que:
1. **Busca vagas** automaticamente em múltiplos job boards
2. **Filtra e rankeia** vagas compatíveis com o perfil do usuário
3. **Gera CVs personalizados** para cada vaga selecionada
4. **Armazena tudo localmente** (perfil, histórico de vagas, CVs gerados)
5. **Roda sob demanda** via comando único - sem daemons, sem cloud

### Princípios
- **Open source** (MIT/Apache-2.0)
- **Zero custo** - roda local, usa LLMs via API própria do usuário ou Ollama
- **Local-first** - dados ficam no seu disco, nada sai sem permissão
- **Token-efficient** - scripts Python pesados, LLM só pro essencial
- **Compartilhável** - `pip install auto-cv` ou `uvx auto-cv`

---

## 2. Pesquisa de Ferramentas Existentes

### 2.1 Job Scraping (Busca de Vagas)

| Ferramenta | Plataformas | Status | Notas |
|------------|-------------|--------|-------|
| **JobSpy** ⭐ | LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google Jobs | Ativo, 5k+ stars | Python lib, `pip install python-jobspy` |
| python-job-scraper | Indeed, LinkedIn | Baixa manutenção | Wrapper simples |
| Scrapers custom | Gupy, Vagas.com, Catho | Precisa Selenium | Anti-bot forte no Brasil |

### 2.2 Matching + CV Generation (O "Core" Inteligente)

| Ferramenta | Job Scraping | Matching/ATS | CV Tailoring | Cover Letter | Tracker |
|------------|--------------|--------------|--------------|--------------|---------|
| **Resume-Matcher** ⭐ | ❌ Manual | ✅ Excelente | ✅ Reword + diff | ✅ | ✅ Kanban |
| Resume-Tailor-Bot | 🔗 URLs | ✅ | ✅ | ✅ | ❌ |
| Resume-Tailor-AI | 🔗 Greenhouse/Lever | ✅ Fact bank | ✅ | ❌ | ❌ |
| AI-Resume-Optimizer | ❌ | ✅ Charts | ✅ Templates | ❌ | ❌ |
| lib-resume-builder-AIHawk | ❌ | ❌ | ✅ | ❌ | ❌ |

### 2.3 Browser Automation (Auto-apply - NÃO QUEREMOS)
- browser-use, EasyApplyJobsBot, Job-apply-AI-agent - apenas para aplicação automática

---

## 3. O "Buraco" no Ecossistema

**NENHUM projeto open source faz o pipeline completo:**
```
Job Boards → Scraping Automático → Filtro/Match Perfil → CV Personalizado → Histórico Local
```

Todos exigem **input manual** da vaga (colar URL ou texto). JobSpy faz scraping mas para por aí. Resume-Matcher é excelente no resto mas não busca vagas.

---

## 4. Opções de Arquitetura Analisadas

### Opção A: Fork + Extend (Resume-Matcher + JobSpy)
- **Prós:** Código maduro para matching/CV, Apache-2.0, local-first, Docker/Ollama
- **Contras:** Integrar duas codebases Python diferentes, manter fork

### Opção B: Wrapper Orchestrador
- **Prós:** Não toca código alheio, atualizações independentes
- **Contras:** Duas dependências pesadas, duplicação de lógica

### Opção C: Build Minimal do Zero
- **Prós:** Zero bloat, 100% seu, single binary/script
- **Contras:** Reinventar matching/ATS (~2000-3000 linhas)

### Opção D: Híbrido Pragmático ⭐ **ESCOLHIDA**
```
Core próprio leve (orchestrator + storage + CLI)
    + JobSpy como lib (pip install python-jobspy)
    + RenderCV como lib (pip install rendercv) - só geração PDF
    + sentence-transformers (embeddings locais, grátis)
    + LLM tailoring via prompts (Claude API / Ollama / OpenAI)
```

**Por que D:**
1. JobSpy já resolve scraping bem (mantido, atualizado)
2. RenderCV já resolve PDF bonito via YAML (17k stars, ativo)
3. sentence-transformers roda local, grátis, rápido para matching
4. Seu código = apenas orquestração + storage + CLI + prompts LLM
5. Fácil de compartilhar: `pip install auto-cv` ou `uvx auto-cv`

---

## 5. MVP - Opção D (Híbrido Pragmático)

### 5.1 Fluxo de Uso

```mermaid
graph TD
    A[auto-cv hunt] --> B[JobSpy busca: LinkedIn, Indeed, Glassdoor,<br/>Gupy, Vagas.com, Wellfound, RemoteOK...]
    B --> C[Dedup + Filtro básico: local, remote, keywords]
    C --> D[Embedding Match: perfil vs vagas<br/>(rápido, local, sem LLM)]
    D --> E[Top-N → LLM Ranker: score detalhado + razão]
    E --> F[Lista rankeada no terminal (rich table)]
    F --> G[Seleciona vagas: 1,3,5-7]
    G --> H[Para cada: LLM Tailor → CV personalizado<br/>(RenderCV → PDF + Markdown)]
    H --> I[Salva: jobs.db, cvs/job-id/, profile.yaml]
    I --> J[Próxima exec: histórico p/ não duplicar,<br/>melhorar match, mostrar "novas desde última vez"]
```

### 5.2 Estrutura do Projeto

```
auto-cv/
├── .claude/
│   └── skills/
│       └── auto-cv/              # Skill do Claude Code
│           ├── __init__.py
│           ├── commands.py       # Comandos slash
│           └── hooks.py          # Hooks se necessário
├── src/
│   └── auto_cv/
│       ├── __init__.py
│       ├── cli.py                # Entry point (Typer)
│       ├── config.py             # Settings (Pydantic Settings)
│       ├── profile/
│       │   ├── __init__.py
│       │   ├── schema.py         # Pydantic models (JSON Schema)
│       │   ├── manager.py        # CRUD + validação
│       │   └── interviewer.py    # Perguntas interativas
│       ├── scraper/
│       │   ├── __init__.py
│       │   ├── base.py           # Protocol/Interface
│       │   ├── jobspy_wrapper.py # JobSpy integration
│       │   ├── brazil.py         # Gupy, Vagas.com, Catho (futuro)
│       │   ├── remote.py         # Wellfound, RemoteOK, WWR
│       │   └── aggregator.py     # Unifica + dedup
│       ├── matcher/
│       │   ├── __init__.py
│       │   ├── embeddings.py     # sentence-transformers
│       │   ├── llm_ranker.py     # LLM para score + razão
│       │   └── scorer.py         # Score final combinado
│       ├── cv/
│       │   ├── __init__.py
│       │   ├── builder.py        # RenderCV integration
│       │   ├── tailor.py         # LLM tailoring por vaga
│       │   └── templates/        # Templates YAML base
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── sqlite.py         # SQLAlchemy + models
│       │   └── files.py          # YAML/JSON para perfil/CVs
│       └── pipeline/
│           ├── __init__.py
│           └── run.py            # Orquestração principal
├── data/                         # .gitignore
│   ├── profile.yaml              # Perfil mestre
│   ├── jobs.db                   # SQLite (vagas, histórico, aplicações)
│   ├── cvs/                      # CVs gerados por vaga
│   │   └── {job_id}/
│   │       ├── cv.pdf
│   │       ├── cv.md
│   │       └── tailor_prompt.txt
│   └── cache/
│       └── embeddings/           # Cache de embeddings
├── tests/
├── pyproject.toml
├── README.md
├── LICENSE
└── .gitignore
```

### 5.3 Schema do Perfil (profile.yaml)

```yaml
# profile.yaml - Perfil mestre do usuário
personal:
  name: "Seu Nome"
  email: "seu@email.com"
  phone: "+55 11 99999-9999"
  location: "São Paulo, SP, Brasil"
  linkedin: "linkedin.com/in/seuusuario"
  github: "github.com/seuusuario"
  portfolio: "https://seuportfolio.com"
  summary: "Resumo profissional 2-3 linhas..."

experience:
  - company: "Empresa Atual"
    role: "Senior Software Engineer"
    start_date: "2022-01"
    end_date: "present"
    location: "São Paulo, SP (Remote)"
    description: "Liderança técnica de..."
    achievements:
      - "Reduziu latência em 40%..."
      - "Mentorou 5 engenheiros..."
    technologies: ["Python", "PostgreSQL", "AWS", "Kubernetes", "React"]

education:
  - institution: "Universidade X"
    degree: "Bacharelado em Ciência da Computação"
    start_date: "2016"
    end_date: "2020"
    highlights: ["Iniciação Científica", "Monitoria"]

skills:
  languages: ["Python", "TypeScript", "Go", "SQL", "Rust"]
  frameworks: ["FastAPI", "React", "Next.js", "Django"]
  infrastructure: ["AWS", "Docker", "Kubernetes", "Terraform", "GitHub Actions"]
  databases: ["PostgreSQL", "Redis", "MongoDB", "Elasticsearch"]
  other: ["CI/CD", "Microservices", "System Design", "Mentoring"]

languages:
  - language: "Português"
    level: "Nativo"
  - language: "Inglês"
    level: "Avançado (C1)"

preferences:
  job_types: ["full-time", "contract"]
  work_modes: ["remote", "hybrid"]
  locations: ["Brasil", "Remote Global", "Portugal", "Alemanha"]
  salary_min_brl: 15000
  salary_min_usd: 3000
  keywords_include: ["backend", "api", "cloud", "architect", "lead", "senior"]
  keywords_exclude: ["frontend-only", "php", "wordpress", "sales", "support"]
  companies_exclude: ["Empresa X", "Empresa Y"]
  visa_sponsorship: false

# Metadados internos
_meta:
  created_at: "2026-01-15T10:30:00"
  updated_at: "2026-01-15T10:30:00"
  version: 1
```

### 5.4 Schema de Vaga (SQLite - jobs.db)

```sql
-- jobs table
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,           -- hash único (source + external_id)
    source TEXT NOT NULL,          -- linkedin, indeed, glassdoor, gupy, wellfound...
    external_id TEXT NOT NULL,     -- ID original do site
    url TEXT NOT NULL UNIQUE,      -- URL da vaga
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    work_mode TEXT,                -- remote, hybrid, onsite
    job_type TEXT,                 -- full-time, contract, internship
    description TEXT,              -- Descrição completa (HTML/texto)
    description_text TEXT,         -- Versão limpa para embedding
    salary_min INTEGER,
    salary_max INTEGER,
    salary_currency TEXT,
    posted_date TIMESTAMP,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_new BOOLEAN DEFAULT 1,      -- Não visto pelo usuário
    is_applied BOOLEAN DEFAULT 0,
    applied_at TIMESTAMP,
    match_score REAL,              -- 0-1 (embedding + LLM)
    match_reason TEXT,             -- Explicação do match
    embedding BLOB                 -- Vector embedding (opcional, cache)
);

-- applications table
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT REFERENCES jobs(id),
    cv_path TEXT,                  -- Caminho do CV gerado
    cover_letter_path TEXT,
    status TEXT DEFAULT 'generated', -- generated, sent, interview, offer, rejected
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- search_history table
CREATE TABLE search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_params TEXT,             -- JSON dos parâmetros de busca
    jobs_found INTEGER,
    jobs_new INTEGER,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5.5 Comandos CLI (Typer)

```bash
# Setup inicial
auto-cv init                      # Cria profile.yaml interativo
auto-cv profile show              # Mostra perfil atual
auto-cv profile edit              # Abre $EDITOR no profile.yaml
auto-cv profile interview         # Entrevista guiada para completar

# Busca de vagas
auto-cv hunt                      # Busca completa (padrão: todos sources)
auto-cv hunt --source linkedin    # Só LinkedIn
auto-cv hunt --remote-only        # Só vagas remotas
auto-cv hunt --keywords "python,aws" --exclude "php,frontend"
auto-cv hunt --since "7 days"     # Só vagas dos últimos 7 dias
auto-cv hunt --limit 50           # Max vagas por source

# Listagem e seleção
auto-cv list                      # Lista vagas rankeadas (rich table)
auto-cv list --new                # Só novas desde última vez
auto-cv list --applied            # Só onde já aplicou
auto-cv show <job_id>             # Detalhes da vaga + match reason

# Geração de CV
auto-cv tailor <job_id>           # Gera CV para uma vaga
auto-cv tailor 1,3,5-7            # Múltiplas (sintaxe range)
auto-cv tailor --all-new          # Todas as novas não aplicadas
auto-cv tailor --output pdf,md    # Formatos de saída

# Histórico e tracking
auto-cv applied <job_id>          # Marca como aplicado
auto-cv status <job_id> <status>  # Atualiza status (interview/offer/rejected)
auto-cv stats                     # Estatísticas: buscadas, aplicadas, taxa resposta

# Utilitários
auto-cv clean                     # Remove vagas antigas (>90 dias) e CVs órfãos
auto-cv export --format json      # Exporta dados para backup
auto-cv import <file>             # Importa backup
```

### 5.6 Pipeline de Execução (pipeline/run.py)

```python
async def run_hunt_pipeline(
    sources: list[str] = None,
    keywords: list[str] = None,
    exclude_keywords: list[str] = None,
    remote_only: bool = False,
    limit_per_source: int = 50,
    since_days: int = 30,
) -> HuntResult:
    """
    1. LOAD PROFILE: Carrega profile.yaml + embedding do perfil
    2. SCRAPE: JobSpy + custom scrapers → lista bruta de vagas
    3. DEDUP: Remove duplicatas (mesmo title+company+location)
    4. BASIC FILTER: location, remote, keywords, salary, exclude
    5. EMBEDDING MATCH: Cosine similarity perfil vs vaga (top 50)
    6. LLM RANKER: Top 20 → LLM para score detalhado + razão
    7. STORE: Salva no SQLite, marca is_new
    8. DISPLAY: Rich table rankeada no terminal
    9. RETURN: HuntResult com jobs rankeados
    """
```

### 5.7 Tailoring do CV (cv/tailor.py)

```python
async def tailor_cv_for_job(
    profile: Profile,
    job: Job,
    cv_template: str = "default",
    llm_provider: str = "claude",  # claude, ollama, openai
) -> TailoredCV:
    """
    1. LOAD: Profile + Job description + Base CV template (YAML)
    2. PROMPT: LLM com instruções:
       - "Reescreva bullets para destacar skills da vaga"
       - "Mantenha fatos, não invente"
       - "Priorize keywords: X, Y, Z"
       - "Formato: RenderCV YAML"
    3. PARSE: Valida YAML gerado contra schema RenderCV
    4. RENDER: RenderCV → PDF + Markdown
    5. SAVE: cvs/{job_id}/cv.pdf, cv.md, prompt_usado.txt
    6. RETURN: Paths dos arquivos gerados
    """
```

---

## 6. Dificuldade e Esforço (MVP)

| Componente | Esforço | Complexidade | Linhas Estimadas |
|------------|---------|--------------|------------------|
| Project setup (pyproject, config, CLI) | Baixo | ⭐ | ~200 |
| Profile manager (schema, CRUD, interviewer) | Médio | ⭐⭐ | ~300 |
| JobSpy wrapper + aggregator | Baixo | ⭐ | ~150 |
| Brazilian scrapers (Gupy, Vagas.com) | Médio | ⭐⭐ | ~300 |
| Remote scrapers (Wellfound, etc) | Baixo | ⭐ | ~100 |
| Storage (SQLAlchemy + models) | Baixo | ⭐ | ~200 |
| Embedding matcher (sentence-transformers) | Baixo | ⭐ | ~100 |
| LLM Ranker (prompt + parsing) | Médio | ⭐⭐ | ~200 |
| LLM Tailor (prompt + RenderCV) | Médio | ⭐⭐ | ~200 |
| CLI commands + Rich tables | Médio | ⭐⭐ | ~300 |
| **Total MVP Completo** | **~2-3 semanas** | **⭐⭐** | **~2000-2500** |

### Cortando Esquinas (MVP Mínimo - Só Para Você)

| Corte | Economia | Impacto |
|-------|----------|---------|
| Pular Brazilian scrapers v1 | -300 linhas | Só LinkedIn/Indeed/Remote (JobSpy cobre) |
| Pular LLM Ranker | -200 linhas | Só embedding match (resolve 80%) |
| Pular Profile Interviewer | -150 linhas | YAML manual + exemplo |
| Pular Rich TUI → CLI simples | -150 linhas | Tabelas básicas |
| **MVP Mínimo** | **~500 linhas** | **2-3 dias** |

---

## 7. Dependências Principais

```toml
# pyproject.toml - dependencies
[project]
name = "auto-cv"
version = "0.1.0"
description = "Automated job search + tailored CV generator"
requires-python = ">=3.11"
dependencies = [
    # Core
    "typer[all]>=0.12",           # CLI
    "pydantic>=2.7",              # Validation
    "pydantic-settings>=2.3",     # Config
    "rich>=13.7",                 # Terminal UI
    "sqlalchemy>=2.0",            # ORM
    "alembic>=1.13",              # Migrations
    "pyyaml>=6.0",                # YAML
    
    # Job Scraping
    "python-jobspy>=1.2",         # JobSpy wrapper
    
    # Matching
    "sentence-transformers>=3.0", # Embeddings locais
    "numpy>=1.26",                # Math
    
    # CV Generation
    "rendercv>=1.0",              # PDF generation
    
    # LLM (escolha um ou suporte a múltiplos)
    "anthropic>=0.25",            # Claude API
    # "ollama>=0.3",              # Local Ollama (opcional)
    # "openai>=1.30",             # OpenAI (opcional)
    
    # Utils
    "httpx>=0.27",                # HTTP client
    "tenacity>=8.3",              # Retry logic
    "python-dateutil>=2.9",       # Dates
    "hashids>=1.3",               # Short IDs
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "ruff>=0.4",
    "mypy>=1.10",
    "pre-commit>=3.6",
]
brazil = [
    "playwright>=1.40",           # Para scrapers brasileiros
    "beautifulsoup4>=4.12",
]
full = ["dev", "brazil"]
```

---

## 8. Próximos Passos (Plano de Ação)

### Fase 1: Fundação (Semana 1)
- [ ] Criar estrutura de pastas + pyproject.toml
- [ ] Configuração base (config.py, Pydantic Settings)
- [ ] Profile schema + manager + YAML load/save
- [ ] SQLite models + SQLAlchemy setup
- [ ] CLI básico com Typer (comandos init, profile show)

### Fase 2: Scraping + Storage (Semana 1-2)
- [ ] JobSpy wrapper básico
- [ ] Aggregator + dedup
- [ ] Pipeline de hunt básico (scrape → filter → store)
- [ ] Comando `hunt` + `list`

### Fase 3: Matching (Semana 2)
- [ ] Embedding do perfil (uma vez)
- [ ] Embedding das vagas + cosine similarity
- [ ] Top-N selection
- [ ] (Opcional) LLM Ranker

### Fase 4: CV Generation (Semana 2-3)
- [ ] Template base RenderCV (YAML)
- [ ] LLM Tailor prompt engineering
- [ ] RenderCV integration → PDF + MD
- [ ] Comando `tailor`

### Fase 5: Polish + Skill (Semana 3)
- [ ] Rich tables bonitas
- [ ] Comando `stats`, `clean`, `export`
- [ ] Skill do Claude Code (.claude/skills/auto-cv/)
- [ ] README + documentação
- [ ] Testes básicos

### Fase 6: Brazilian Scrapers (Pós-MVP)
- [ ] Gupy scraper (Playwright)
- [ ] Vagas.com scraper
- [ ] Catho scraper
- [ ] Integração no aggregator

---

## 9. Decisões Técnicas Importantes

| Decisão | Escolha | Racional |
|---------|---------|----------|
| **Language** | Python 3.11+ | Ecossistema ML/scraping/CLI |
| **CLI Framework** | Typer | Type hints, auto-completion, Rich integration |
| **Config** | Pydantic Settings | Validation, env vars, .env support |
| **Database** | SQLite + SQLAlchemy | Zero config, portable, ACID |
| **Embeddings** | sentence-transformers (all-MiniLM-L6-v2) | Local, grátis, 384-dim, rápido |
| **LLM Provider** | Pluggable (Claude default, Ollama/OpenAI opcional) | Flexibilidade, custo zero com Ollama |
| **CV Format** | RenderCV (YAML → PDF/MD/HTML) | 17k stars, ativo, themes bonitos, LaTeX quality |
| **Async** | asyncio + httpx | Scraping paralelo, LLM calls paralelos |
| **Packaging** | uv / pip / pipx | Distribuição simples |

---

## 10. Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| JobSpy quebra (mudança no LinkedIn) | Média | Alto | Wrapper isolado, fallback para RSS/email alerts |
| Anti-bot em sites brasileiros | Alta | Médio | Playwright + user-agent rotation, delays, proxy opcional |
| LLM hallucina no tailoring | Baixa | Médio | Prompt strict, validação schema, diff review antes de salvar |
| Embedding model grande | Baixa | Baixo | all-MiniLM-L6-v2 = 90MB, roda em CPU |
| Dados sensíveis no profile.yaml | Média | Alto | .gitignore, documentar não commitar, criptografia opcional |
| Manutenção de scrapers | Média | Médio | JobSpy mantido pela comunidade, brasileiros só quando necessário |

---

## 11. Referências e Links Úteis

### Projetos Base
- [JobSpy](https://github.com/speedyapply/JobSpy) - Job scraping library
- [RenderCV](https://github.com/rendercv/rendercv) - CV generator (YAML → PDF)
- [Resume-Matcher](https://github.com/srbhr/Resume-Matcher) - Matching + CV + tracker (referência)
- [sentence-transformers](https://www.sbert.net/) - Embeddings locais

### Documentação Técnica
- [JobSpy Docs](https://github.com/speedyapply/JobSpy/tree/main/jobspy)
- [RenderCV Docs](https://docs.rendercv.com/)
- [sentence-transformers Models](https://www.sbert.net/docs/pretrained_models.html)
- [Typer Tutorial](https://typer.tiangolo.com/tutorial/)
- [Rich Tables](https://rich.readthedocs.io/en/stable/tables.html)

### Padrões
- [JSON Resume Schema](https://jsonresume.org/schema/) - Schema padrão de CV
- [RenderCV Schema](https://docs.rendercv.com/user_guide/input_format/) - Schema do RenderCV

---

## 12. Aprovação do Escopo

> **Antes de iniciar implementação, confirmar:**

- [ ] Arquitetura Opção D (Híbrido Pragmático) aprovada
- [ ] MVP Mínimo (500 linhas, 2-3 dias) ou MVP Completo (2000 linhas, 2-3 semanas)
- [ ] LLM Provider: Claude API (pago) vs Ollama (grátis, local) vs ambos
- [ ] Brazilian scrapers no MVP ou pós-MVP
- [ ] Skill Claude Code incluída no MVP ou depois
- [ ] Licença: MIT ou Apache-2.0

---

*Documento criado em: 2026-01-15*
*Versão: 1.0*
*Status: Em aprovação*