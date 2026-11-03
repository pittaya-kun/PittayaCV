# ROADMAP - Auto-CV (Execução Passo a Passo)

> **Regra de Ouro:** Uma fase por vez. Só avança quando a anterior estiver **rodando e testada**.

---

## 📦 FASE 0: Setup do Ambiente (30 min)

### 0.1 Verificar/Instalar Dependências de Sistema
```bash
# Verificar Python
python3 --version  # precisa 3.11+

# Verificar uv (gerenciador rápido) ou pip
uv --version || pip --version

# Verificar git
git --version

# LaTeX para RenderCV (TinyTeX auto-instala, mas pode pré-instalar)
# Opcional: brew install --cask basictex  # macOS
```

### 0.2 Criar Estrutura Inicial do Projeto
```bash
cd /Users/Pittaya/Documents/Craudio/Auto-cv

# Estrutura de pastas
mkdir -p src/auto_cv/{profile,scraper,matcher,cv,storage,pipeline}
mkdir -p data/{cvs,cache/embeddings}
mkdir -p tests
mkdir -p .claude/skills/auto-cv
```

### 0.3 Inicializar Git + .gitignore
```bash
git init
cat > .gitignore << 'EOF'
# Data (sensível e grande)
data/profile.yaml
data/jobs.db
data/cvs/
data/cache/

# Python
__pycache__/
*.pyc
.venv/
venv/
.env

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# Logs
*.log
EOF
```

### 0.4 Criar pyproject.toml
```bash
# Vou criar na Fase 1 junto com o código
```

### 0.5 Criar Virtual Env + Instalar Base
```bash
# Com uv (recomendado - 10x mais rápido)
uv venv
source .venv/bin/activate
uv pip install --upgrade pip

# Ou com pip padrão
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

---

## 🏗️ FASE 1: Fundação - Config, Profile, Storage, CLI (2-3h)

### 1.1 pyproject.toml (Dependências Completas)
**Arquivo:** `pyproject.toml`

### 1.2 Config Central (Pydantic Settings)
**Arquivo:** `src/auto_cv/config.py`
- Settings com env vars
- Paths de dados
- LLM config (provider, model, api_key)
- Scraper config

### 1.3 Profile Schema (Pydantic Models)
**Arquivo:** `src/auto_cv/profile/schema.py`
- `PersonalInfo`, `Experience`, `Education`, `Skill`, `Language`
- `Preferences` (job_types, locations, keywords, salary)
- `Profile` (root model)
- Validadores

### 1.4 Profile Manager (CRUD + YAML)
**Arquivo:** `src/auto_cv/profile/manager.py`
- `load_profile()` → Profile
- `save_profile(profile)` 
- `create_default()` → template YAML
- `validate_profile(profile)` → erros/avisos

### 1.5 Storage (SQLite + SQLAlchemy)
**Arquivos:** 
- `src/auto_cv/storage/models.py` (SQLAlchemy models)
- `src/auto_cv/storage/sqlite.py` (engine, session, CRUD)
- `src/auto_cv/storage/files.py` (YAML/JSON helpers)

### 1.6 CLI Base (Typer + Rich)
**Arquivo:** `src/auto_cv/cli.py`
- `app = typer.Typer()`
- Comando `init` (cria profile.yaml interativo)
- Comando `profile show/edit/validate`
- Comando `hunt` (stub)
- Comando `list` (stub)
- Comando `tailor` (stub)
- Rich table para listagem

### 1.7 Entry Point
**Arquivo:** `src/auto_cv/__init__.py` + `pyproject.toml [project.scripts]`
- `auto-cv = "auto_cv.cli:app"`

### ✅ TESTE FASE 1
```bash
auto-cv --help
auto-cv init          # Cria profile.yaml
auto-cv profile show  # Mostra perfil
auto-cv profile edit  # Abre no $EDITOR
```

---

## 🔍 FASE 2: Scraping + Pipeline Básico (2-3h)

### 2.1 JobSpy Wrapper
**Arquivo:** `src/auto_cv/scraper/jobspy_wrapper.py`
- `search_jobs(params)` → List[RawJob]
- Mapeia campos JobSpy → schema interno
- Tratamento de erros + retry

### 2.2 Scrapers Adicionais (Stubs)
**Arquivos:**
- `src/auto_cv/scraper/brazil.py` (stub com `NotImplementedError`)
- `src/auto_cv/scraper/remote.py` (stub)

### 2.3 Aggregator + Dedup
**Arquivo:** `src/auto_cv/scraper/aggregator.py`
- `aggregate_all(sources)` → List[Job]
- `deduplicate(jobs)` → remove duplicatas (title+company+location hash)
- `basic_filter(jobs, profile)` → location, remote, keywords, salary

### 2.4 Pipeline de Hunt
**Arquivo:** `src/auto_cv/pipeline/run.py`
- `run_hunt(params)` orquestra tudo:
  1. Load profile
  2. Scrape (JobSpy)
  3. Aggregate + Dedup
  4. Basic Filter
  5. Save to SQLite (marca `is_new=True`)
  6. Return HuntResult

### 2.5 Conectar CLI `hunt` + `list`
**Atualiza:** `src/auto_cv/cli.py`
- `hunt` chama pipeline + mostra rich table
- `list` lê SQLite + mostra rich table com filtros (--new, --applied)

### ✅ TESTE FASE 2
```bash
auto-cv hunt --keywords "python backend" --limit 20
auto-cv list --new
auto-cv show <job_id>  # Detalhes da vaga
```

---

## 🧠 FASE 3: Matching - Embeddings + Ranking (2-3h)

### 3.1 Embedding do Perfil
**Arquivo:** `src/auto_cv/matcher/embeddings.py`
- `ProfileEmbedder` class
- `embed_profile(profile)` → vector (cache em disco)
- `embed_job(job)` → vector
- `cosine_similarity(vec1, vec2)` → float 0-1
- Modelo: `all-MiniLM-L6-v2` (384 dims, ~90MB, CPU)

### 3.2 Scorer (Embedding Match)
**Arquivo:** `src/auto_cv/matcher/scorer.py`
- `score_jobs(profile, jobs)` → List[(job, score)]
- Ordena por score desc
- Pega top-N (ex: 20)

### 3.3 LLM Ranker (Opcional - Pular no MVP Mínimo)
**Arquivo:** `src/auto_cv/matcher/llm_ranker.py` (stub)
- Para depois: prompt com perfil + top-20 vagas → score detalhado + razão

### 3.4 Integrar no Pipeline
**Atualiza:** `src/auto_cv/pipeline/run.py`
- Após basic_filter → embedding match → salva `match_score` no SQLite
- `list` já mostra ordenado por score

### ✅ TESTE FASE 3
```bash
auto-cv hunt --keywords "python backend"  # Agora com scores
auto-cv list --new  # Ordenado por match_score
```

---

## 📝 FASE 4: CV Generation - RenderCV + Tailoring (3-4h)

### 4.1 Template Base RenderCV
**Arquivo:** `src/auto_cv/cv/templates/base.yaml`
- Template YAML RenderCV com placeholders
- Sections: personal, experience, education, skills, etc.
- Design: clean, ATS-friendly, 1 página

### 4.2 CV Builder (RenderCV Integration)
**Arquivo:** `src/auto_cv/cv/builder.py`
- `build_cv(profile, template="base")` → RenderCVDataModel
- `render_cv(data, output_dir)` → PDF + Markdown
- Validação de schema

### 4.3 LLM Tailoring (Anthropic SDK)
**Arquivo:** `src/auto_cv/cv/tailor.py`
- `tailor_cv(profile, job, template)` → tailored YAML
- Prompt engineering:
  - "Reescreva bullets destacando skills da vaga"
  - "Mantenha fatos, não invente"
  - "Priorize keywords: X, Y, Z"
  - "Retorne só YAML válido RenderCV"
- Parse + validação + fallback para template base

### 4.4 Salvamento de CVs
**Arquivo:** `src/auto_cv/cv/manager.py`
- `save_tailored_cv(job_id, cv_yaml, pdf_bytes, md_text)`
- Estrutura: `data/cvs/{job_id}/cv.yaml, cv.pdf, cv.md, prompt.txt`

### 4.5 Conectar CLI `tailor`
**Atualiza:** `src/auto_cv/cli.py`
- `tailor <job_id>` → gera CV para uma vaga
- `tailor 1,3,5-7` → múltiplas (parse range)
- `tailor --all-new` → todas novas não aplicadas

### ✅ TESTE FASE 4
```bash
auto-cv tailor <job_id>        # Gera CV personalizado
auto-cv tailor --all-new       # Batch
ls data/cvs/<job_id>/          # cv.pdf, cv.md, prompt.txt
```

---

## 🎨 FASE 5: Polish + Skill FCC + Docs (2-3h)

### 5.1 CLI Polish
- Rich tables bonitas (cores, truncagem, scroll)
- Progress bars no hunt/tailor
- Confirmações interativas
- Help texts completos

### 5.2 Comandos Extras
- `stats` - Estatísticas (buscadas, aplicadas, taxa resposta)
- `applied <job_id>` - Marca como aplicado
- `status <job_id> <status>` - interview/offer/rejected
- `clean` - Remove vagas >90 dias + CVs órfãos
- `export/import` - Backup JSON

### 5.3 Skill Claude Code
**Arquivos:** `.claude/skills/auto-cv/`
- `__init__.py` - Registro da skill
- `commands.py` - Slash commands (`/auto-cv:hunt`, `/auto-cv:tailor`)
- `hooks.py` - Se necessário (auto-complete, etc.)

### 5.4 README.md
- Instalação (`uvx auto-cv` ou `pip install`)
- Quickstart (3 comandos)
- Comandos reference
- Arquitetura
- Contribuindo

### 5.5 Testes Básicos
**Arquivo:** `tests/test_basic.py`
- Test profile load/save
- Test scraper returns data
- Test embedding similarity
- Test cv render

### ✅ TESTE FASE 5 (MVP COMPLETO)
```bash
# Fluxo completo
auto-cv init
auto-cv hunt --keywords "python backend" --remote-only
auto-cv list --new
auto-cv tailor 1,2,3
auto-cv applied 1
auto-cv stats
```

---

## 🌎 FASE 6: Brazilian Scrapers (Pós-MVP - Opcional)

### 6.1 Gupy Scraper (Playwright)
### 6.2 Vagas.com Scraper
### 6.3 Catho Scraper
### 6.4 Integrar no Aggregator

---

## 📋 CHECKLIST DE ENTREGA POR FASE

| Fase | Entregável | Comando de Teste | Status |
|------|------------|------------------|--------|
| 0 | Ambiente pronto + git | `git status` | ⬜ |
| 1 | `auto-cv init/profile` funciona | `auto-cv profile show` | ⬜ |
| 2 | `auto-cv hunt/list` busca vagas reais | `auto-cv hunt` | ⬜ |
| 3 | Scores de matching aparecem | `auto-cv list --new` | ⬜ |
| 4 | `auto-cv tailor` gera PDF personalizado | `open data/cvs/.../cv.pdf` | ⬜ |
| 5 | Skill FCC + docs + polish | `/auto-cv:hunt` no FCC | ⬜ |

---

## 🚨 REGRAS DE EXECUÇÃO

1. **Uma fase por vez** - Não começa a Fase 2 sem testar Fase 1
2. **Commit a cada fase** - `git add -A && git commit -m "feat: Fase X - ..."`
3. **Teste manual obrigatório** - Rode o comando de teste antes de marcar ✅
4. **Dúvida para na hora** - Não assume, pergunta
5. **MVP Mínimo = Fases 0-4** - Fase 5 é polish, Fase 6 é extra

---

## 🎯 PRÓXIMO PASSO IMEDIATO

**FASE 0** - Vamos executar agora:

1. Verificar ambiente
2. Criar estrutura de pastas
3. `.gitignore`
4. `pyproject.toml`
5. Virtual env + install base

**Bora começar a Fase 0?** 🚀