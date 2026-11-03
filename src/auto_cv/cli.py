# -*- coding: utf-8 -*-
"""
Auto-CV - CLI Module
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Typer CLI with Rich output for Auto-CV.
"""

import sys
from pathlib import Path
from typing import Optional, List
from datetime import datetime

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

from auto_cv.config import get_settings, create_settings, Settings
from auto_cv.profile.manager import (
    get_manager, load_profile, save_profile, ensure_profile,
    validate_profile, interview_profile, ProfileManager,
    LoadResult, ValidationResult,
)
from auto_cv.profile.schema import (
    Profile, PersonalInfo, Experience, Education, Skill, Language,
    Preferences, WorkMode, JobType, LanguageLevel, SkillCategory,
    create_default_profile, create_minimal_profile,
)
from auto_cv.storage.sqlite import (
    init_db, close_db, session_scope,
    JobRepository, ApplicationRepository,
    SearchHistoryRepository, EmbeddingCacheRepository,
)
from auto_cv.storage.models import (
    Job, Application, SearchHistory, EmbeddingCache,
    JobSource, ApplicationStatus, MatchMethod,
)
from auto_cv.storage.files import get_cv_output_dir, list_cvs


# ============================================================
# TYPER APP & CONSOLE
# ============================================================

app = typer.Typer(
    name="auto-cv",
    help="🤖 Auto-CV - Busca automatizada de vagas + CV personalizado",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
err_console = Console(stderr=True)


# ============================================================
# CALLBACKS & HELPERS
# ============================================================

def _get_settings(ctx: typer.Context) -> Settings:
    """Recupera settings do contexto ou cria novo."""
    return ctx.obj.get("settings") or get_settings()


def _print_validation(result: ValidationResult, title: str = "Validação") -> None:
    """Print formatado de ValidationResult."""
    if result.is_valid:
        console.print(f"✅ [green]{title}: Válido[/green]")
    else:
        console.print(f"❌ [red]{title}: Inválido[/red]")

    for err in result.errors:
        console.print(f"  [red]✗[/red] {err}")
    for warn in result.warnings:
        console.print(f"  [yellow]⚠[/yellow] {warn}")


def _print_profile_summary(profile: Profile) -> None:
    """Print resumo do perfil."""
    table = Table(title="📋 Resumo do Perfil", show_header=True, header_style="bold cyan")
    table.add_column("Campo", style="cyan")
    table.add_column("Valor", style="white")

    p = profile.personal
    table.add_row("Nome", p.name)
    table.add_row("Email", p.email)
    table.add_row("Localização", p.location)
    table.add_row("LinkedIn", str(p.linkedin) if p.linkedin else "—")
    table.add_row("GitHub", str(p.github) if p.github else "—")
    table.add_row("Resumo", p.summary[:60] + "..." if len(p.summary) > 60 else p.summary or "—")
    table.add_row("Experiências", str(len(profile.experience)))
    table.add_row("Formações", str(len(profile.education)))
    table.add_row("Skills", str(len(profile.skills)))
    table.add_row("Idiomas", ", ".join(f"{l.language}({l.level.value})" for l in profile.languages))
    table.add_row("Exp. Total", f"{profile.total_experience_years:.1f} anos")
    table.add_row("Cargo Atual", profile.current_role or "—")
    table.add_row("Empresa Atual", profile.current_company or "—")
    table.add_row("Nível Sênior", "Sim" if profile.is_senior_level else "Não")
    table.add_row("Versão Schema", str(profile.meta.version))
    table.add_row("Atualizado", profile.meta.updated_at.strftime("%d/%m/%Y %H:%M"))

    console.print(table)


def _print_job_table(jobs: List[Job], title: str = "Vagas") -> None:
    """Print tabela de vagas."""
    if not jobs:
        console.print(f"[yellow]{title}: nenhuma encontrada[/yellow]")
        return

    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Título", style="white", max_width=40)
    table.add_column("Empresa", style="cyan", max_width=25)
    table.add_column("Local", style="green", max_width=20)
    table.add_column("Modalidade", style="yellow", max_width=12)
    table.add_column("Score", justify="right", style="magenta")
    table.add_column("Fonte", style="blue", max_width=12)

    for job in jobs:
        score_str = f"{job.match_score:.2f}" if job.match_score else "—"
        table.add_row(
            str(job.id),
            job.title[:38] + ".." if len(job.title) > 40 else job.title,
            job.company[:23] + ".." if len(job.company) > 25 else job.company,
            job.location[:18] + ".." if job.location and len(job.location) > 20 else (job.location or "—"),
            job.work_mode or "—",
            score_str,
            job.source,
        )

    console.print(table)


def _print_application_table(apps: List[Application], title: str = "Candidaturas") -> None:
    """Print tabela de candidaturas."""
    if not apps:
        console.print(f"[yellow]{title}: nenhuma[/yellow]")
        return

    status_colors = {
        "new": "dim",
        "matched": "cyan",
        "cv_generated": "blue",
        "applied": "green",
        "interview": "yellow",
        "offer": "bold green",
        "rejected": "red",
        "archived": "dim",
    }

    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Vaga", style="white", max_width=35)
    table.add_column("Empresa", style="cyan", max_width=20)
    table.add_column("Status", style="white", max_width=15)
    table.add_column("Score", justify="right", style="magenta")
    table.add_column("CV", style="green", max_width=10)
    table.add_column("Atualizado", style="dim", max_width=16)

    for app in apps:
        status = app.status
        color = status_colors.get(status, "white")
        cv_status = "✓" if app.cv_pdf_path or app.cv_md_path else "✗"
        table.add_row(
            str(app.id),
            app.job.title[:33] + ".." if app.job and len(app.job.title) > 35 else (app.job.title if app.job else "—"),
            app.job.company[:18] + ".." if app.job and len(app.job.company) > 20 else (app.job.company if app.job else "—"),
            f"[{color}]{status}[/{color}]",
            f"{app.match_score:.2f}" if app.match_score else "—",
            cv_status,
            app.updated_at.strftime("%d/%m %H:%M"),
        )

    console.print(table)


# ============================================================
# COMMANDS: INIT
# ============================================================

@app.command()
def init(
    minimal: bool = typer.Option(False, "--minimal", "-m", help="Cria perfil mínimo (apenas obrigatórios)"),
    force: bool = typer.Option(False, "--force", "-f", help="Sobrescreve profile.yaml se existir"),
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Caminho customizado para profile.yaml"),
):
    """
    Inicializa estrutura do Auto-CV e cria profile.yaml template.
    """
    settings = create_settings(profile_path=path) if path else get_settings()
    settings.ensure_directories()

    manager = ProfileManager(settings)

    # Verifica se já existe
    if manager.profile_path.exists() and not force:
        console.print(f"[yellow]⚠[/yellow] Profile já existe em: {manager.profile_path}")
        if not Confirm.ask("Sobrescrever?"):
            console.print("Cancelado.")
            return

    # Cria perfil
    with console.status("[bold green]Criando perfil..."):
        profile = manager.create_default(minimal=minimal)
        result = manager.save_profile(profile, backup=False)

    if result.is_valid:
        console.print(f"✅ [green]Perfil criado:[/green] {manager.profile_path}")
        console.print(f"   [dim]Modo: {'mínimo' if minimal else 'completo'}[/dim]")
        console.print("\n[bold]Próximos passos:[/bold]")
        console.print("  1. Edite o profile.yaml com seus dados")
        console.print("  2. Rode: [cyan]auto-cv profile validate[/cyan]")
        console.print("  3. Rode: [cyan]auto-cv hunt[/cyan] para buscar vagas")
    else:
        console.print(f"❌ [red]Erro ao criar:[/red] {result.errors}")
        raise typer.Exit(1)


# ============================================================
# COMMANDS: PROFILE
# ============================================================

profile_app = typer.Typer(name="profile", help="Gerencia perfil do usuário")
app.add_typer(profile_app)


@profile_app.command("show")
def profile_show(
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Caminho customizado do profile.yaml"),
):
    """Mostra perfil atual."""
    settings = create_settings(profile_path=path) if path else get_settings()
    manager = ProfileManager(settings)

    result = manager.load_profile(validate=True)

    if not result.file_exists:
        console.print(f"[yellow]⚠[/yellow] Profile não encontrado em: {manager.profile_path}")
        console.print("Rode: [cyan]auto-cv init[/cyan]")
        return

    if not result.profile:
        console.print(f"❌ [red]Erro ao carregar:[/red] {result.validation.errors}")
        return

    _print_profile_summary(result.profile)
    _print_validation(result.validation, "Validação")


@profile_app.command("edit")
def profile_edit(
    interactive: bool = typer.Option(True, "--interactive/--no-interactive", "-i/-n", help="Modo entrevista interativa"),
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Caminho customizado do profile.yaml"),
):
    """Edita perfil (modo entrevista interativa)."""
    settings = create_settings(profile_path=path) if path else get_settings()
    manager = ProfileManager(settings)

    result = manager.load_profile(validate=False)

    if not result.file_exists:
        console.print(f"[yellow]⚠[/yellow] Profile não encontrado. Criando novo...")
        profile = manager.create_default(minimal=False)
    else:
        profile = result.profile

    if interactive:
        console.print("[bold cyan]Iniciando entrevista interativa...[/bold cyan]")
        console.print("[dim]Pressione Enter para manter valor atual[/dim]\n")
        profile = interview_profile(profile)
    else:
        # TODO: abrir no $EDITOR
        console.print("[yellow]Modo não-interativo não implementado ainda. Use --interactive.[/yellow]")
        return

    # Salva
    save_result = manager.save_profile(profile)
    if save_result.is_valid:
        console.print(f"✅ [green]Perfil salvo:[/green] {manager.profile_path}")
        _print_validation(manager.validate_profile(profile))
    else:
        console.print(f"❌ [red]Erro ao salvar:[/red] {save_result.errors}")
        raise typer.Exit(1)


@profile_app.command("validate")
def profile_validate(
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Caminho customizado do profile.yaml"),
):
    """Valida perfil atual."""
    settings = create_settings(profile_path=path) if path else get_settings()
    manager = ProfileManager(settings)

    result = manager.load_profile(validate=True)

    if not result.file_exists:
        console.print(f"[yellow]⚠[/yellow] Profile não encontrado: {manager.profile_path}")
        raise typer.Exit(1)

    if not result.profile:
        console.print(f"❌ [red]Erro ao carregar:[/red] {result.validation.errors}")
        raise typer.Exit(1)

    _print_validation(result.validation, "Validação do Perfil")

    if result.validation.warnings:
        console.print(f"\n[dim]Total: {len(result.validation.errors)} erro(s), {len(result.validation.warnings)} aviso(s)[/dim]")
    else:
        console.print("\n✅ [green]Perfil válido e completo![/green]")


@profile_app.command("backup")
def profile_backup(
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Caminho customizado do profile.yaml"),
):
    """Cria backup manual do perfil."""
    settings = create_settings(profile_path=path) if path else get_settings()
    manager = ProfileManager(settings)

    backup_path = manager.backup_profile()
    if backup_path:
        console.print(f"✅ [green]Backup criado:[/green] {backup_path}")
    else:
        console.print("[yellow]⚠[/yellow] Nenhum perfil para backup")


# ============================================================
# COMMANDS: HUNT (Pipeline completo)
# ============================================================

@app.command()
def hunt(
    sources: Optional[List[str]] = typer.Option(None, "--source", "-s", help="Fontes: linkedin, indeed, glassdoor, gupy, vagas, wellfound, remoteok"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Termo de busca (ex: 'python remote')"),
    location: Optional[str] = typer.Option(None, "--location", "-l", help="Localização (ex: 'Brasil', 'Remote Global')"),
    remote_only: bool = typer.Option(False, "--remote-only", "-r", help="Apenas vagas remotas"),
    limit: int = typer.Option(50, "--limit", "-n", help="Máximo de vagas por fonte"),
    min_score: float = typer.Option(0.3, "--min-score", help="Score mínimo de match (0-1)"),
    top_n: int = typer.Option(20, "--top-n", help="Top N para LLM reranker"),
    generate_cv: bool = typer.Option(False, "--generate-cv", "-g", help="Gera CV para top matches"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simula sem salvar no banco"),
):
    """
    Executa pipeline completo: scrape → match → (opcional) CV.
    """
    settings = get_settings()
    init_db(settings)

    manager = ProfileManager(settings)
    profile_result = manager.ensure_profile()

    if not profile_result.profile:
        console.print("❌ [red]Perfil não configurado. Rode:[/red] auto-cv init")
        raise typer.Exit(1)

    profile = profile_result.profile

    console.print(Panel.fit(
        f"[bold]Auto-CV Hunt Pipeline[/bold]\n"
        f"Perfil: {profile.personal.name} ({profile.current_role or 'sem cargo'})\n"
        f"Fontes: {', '.join(sources) if sources else 'todas'}\n"
        f"Query: {query or 'padrão do perfil'}\n"
        f"Min Score: {min_score}\n"
        f"Top N LLM: {top_n}",
        title="🚀 Iniciando Hunt",
        border_style="cyan",
    ))

    # TODO: Implementar scrapers reais
    console.print("\n[yellow]⚠ Scrapers não implementados ainda (Fase 2)[/yellow]")
    console.print("[dim]Use 'auto-cv scrape --help' quando disponível[/dim]")

    # Placeholder: cria job fake para teste
    with session_scope(settings) as session:
        job_repo = JobRepository(session)
        app_repo = ApplicationRepository(session)

        # Demo job
        demo_job = Job(
            source=JobSource.LINKEDIN.value,
            external_id="demo_001",
            url="https://linkedin.com/jobs/demo",
            title="Senior Python Engineer",
            company="Tech Corp",
            location="São Paulo, SP",
            work_mode="remote",
            job_type="full-time",
            description="Vaga para Python, AWS, Kubernetes...",
            salary_min=18000,
            salary_max=30000,
            is_active=True,
        )
        demo_job = job_repo.upsert(demo_job)

        # Match simples (placeholder)
        demo_job.match_score = 0.87
        demo_job.match_method = MatchMethod.HYBRID.value
        demo_job.matched_at = datetime.utcnow()
        session.commit()

        # Cria application
        app = Application(
            job_id=demo_job.id,
            profile_version=profile.meta.version,
            status=ApplicationStatus.MATCHED.value,
            match_score=0.87,
            match_method=MatchMethod.HYBRID.value,
        )
        session.add(app)
        session.commit()

        console.print(f"\n✅ [green]Demo job criado:[/green] {demo_job.title} @ {demo_job.company}")
        console.print(f"   Match: {demo_job.match_score:.0%} ({demo_job.match_method})")

    if generate_cv:
        console.print("\n[yellow]⚠ Geração de CV não implementada ainda (Fase 4)[/yellow]")

    close_db()


# ============================================================
# COMMANDS: LIST
# ============================================================

list_app = typer.Typer(name="list", help="Lista vagas, matches, candidaturas")
app.add_typer(list_app)


@list_app.command("jobs")
def list_jobs(
    status: Optional[str] = typer.Option(None, "--status", help="Filtro: active, matched, unmatched"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Filtrar por fonte"),
    limit: int = typer.Option(20, "--limit", "-n", help="Máximo de resultados"),
    offset: int = typer.Option(0, "--offset", "-o", help="Offset para paginação"),
):
    """Lista vagas no banco."""
    settings = get_settings()
    init_db(settings)

    with session_scope(settings) as session:
        repo = JobRepository(session)

        if status == "matched":
            jobs = repo.get_matched(min_score=0.3, limit=limit)
        elif status == "unmatched":
            jobs = repo.get_unmatched(min_score=0.3, limit=limit)
        else:
            jobs = repo.get_active(limit=limit, offset=offset)

        if source:
            jobs = [j for j in jobs if j.source == source]

        _print_job_table(jobs, f"Vagas ({len(jobs)})")

    close_db()


@list_app.command("matches")
def list_matches(
    min_score: float = typer.Option(0.3, "--min-score", help="Score mínimo"),
    limit: int = typer.Option(20, "--limit", "-n", help="Máximo de resultados"),
):
    """Lista top matches."""
    settings = get_settings()
    init_db(settings)

    with session_scope(settings) as session:
        repo = JobRepository(session)
        jobs = repo.get_matched(min_score=min_score, limit=limit)
        _print_job_table(jobs, f"Top Matches (score ≥ {min_score:.0%})")

    close_db()


@list_app.command("applications")
def list_applications(
    status: Optional[str] = typer.Option(None, "--status", help="Filtrar por status"),
    limit: int = typer.Option(20, "--limit", "-n", help="Máximo de resultados"),
):
    """Lista candidaturas."""
    settings = get_settings()
    init_db(settings)

    with session_scope(settings) as session:
        repo = ApplicationRepository(session)

        if status:
            apps = repo.get_by_status(status, limit=limit)
        else:
            # Pipeline completo
            pipeline = repo.get_pipeline()
            total = sum(len(v) for v in pipeline.values())
            console.print(f"\n[bold]Pipeline de Candidaturas ({total} total)[/bold]\n")
            for st, apps in pipeline.items():
                color = {
                    "new": "dim", "matched": "cyan", "cv_generated": "blue",
                    "applied": "green", "interview": "yellow", "offer": "bold green",
                    "rejected": "red", "archived": "dim",
                }.get(st, "white")
                console.print(f"  [{color}]{st}[/{color}]: {len(apps)}")
            return

        _print_application_table(apps, f"Candidaturas ({len(apps)})")

    close_db()


@list_app.command("cvs")
def list_cvs_cmd():
    """Lista CVs gerados."""
    settings = get_settings()
    cvs = list_cvs(settings)

    if not cvs:
        console.print("[yellow]Nenhum CV gerado ainda[/yellow]")
        return

    table = Table(title="CVs Gerados", show_header=True, header_style="bold cyan")
    table.add_column("Arquivo", style="white")
    table.add_column("Tamanho", justify="right", style="green")
    table.add_column("Modificado", style="dim")

    for cv in cvs:
        table.add_row(cv.name, cv.size_human, cv.modified.strftime("%d/%m/%Y %H:%M"))

    console.print(table)


# ============================================================
# COMMANDS: TAILOR (Gera CV para vaga específica)
# ============================================================

@app.command()
def tailor(
    job_id: int = typer.Argument(..., help="ID da vaga"),
    template: str = typer.Option("base", "--template", "-t", help="Template do CV"),
    formats: List[str] = typer.Option(["pdf", "md"], "--format", "-f", help="Formatos: pdf, md"),
    output_dir: Optional[Path] = typer.Option(None, "--output", "-o", help="Diretório de saída"),
):
    """
    Gera CV personalizado para uma vaga específica.
    """
    settings = get_settings()
    init_db(settings)

    with session_scope(settings) as session:
        job_repo = JobRepository(session)
        app_repo = ApplicationRepository(session)

        job = job_repo.find_by_id(job_id)
        if not job:
            console.print(f"❌ [red]Vaga {job_id} não encontrada[/red]")
            raise typer.Exit(1)

        console.print(f"[bold]Gerando CV para:[/bold] {job.title} @ {job.company}")

        # TODO: Implementar geração de CV (Fase 4)
        console.print("\n[yellow]⚠ Geração de CV não implementada ainda (Fase 4)[/yellow]")
        console.print("[dim]Use 'auto-cv list cvs' para ver CVs existentes[/dim]")

    close_db()


# ============================================================
# COMMANDS: STATUS (Kanban)
# ============================================================

@app.command()
def status():
    """Mostra kanban do pipeline de candidaturas."""
    settings = get_settings()
    init_db(settings)

    with session_scope(settings) as session:
        repo = ApplicationRepository(session)
        pipeline = repo.get_pipeline()

        # Colunas do kanban
        columns = [
            ("NEW", "new", "dim"),
            ("MATCHED", "matched", "cyan"),
            ("CV_GENERATED", "cv_generated", "blue"),
            ("APPLIED", "applied", "green"),
            ("INTERVIEW", "interview", "yellow"),
            ("OFFER", "offer", "bold green"),
            ("REJECTED", "rejected", "red"),
            ("ARCHIVED", "archived", "dim"),
        ]

        for title, key, color in columns:
            apps = pipeline.get(key, [])
            console.print(f"\n[bold {color}]{title}[/bold {color}] ({len(apps)})")
            for app in apps[:5]:  # Top 5 por coluna
                job_title = app.job.title if app.job else "N/A"
                company = app.job.company if app.job else "N/A"
                score = f"{app.match_score:.0%}" if app.match_score else "—"
                cv = "📄" if app.cv_pdf_path or app.cv_md_path else ""
                console.print(f"  {cv} {job_title[:40]} @ {company} [{score}]")
            if len(apps) > 5:
                console.print(f"  [dim]... e mais {len(apps) - 5}[/dim]")

    close_db()


# ============================================================
# COMMANDS: CONFIG
# ============================================================

config_app = typer.Typer(name="config", help="Gerencia configurações")
app.add_typer(config_app)


@config_app.command("show")
def config_show():
    """Mostra configurações atuais."""
    settings = get_settings()

    table = Table(title="⚙️ Configurações", show_header=True, header_style="bold cyan")
    table.add_column("Setting", style="cyan")
    table.add_column("Valor", style="white")

    # Paths
    table.add_row("data_dir", str(settings.data_dir))
    table.add_row("profile_path", str(settings.profile_path))
    table.add_row("jobs_db_path", str(settings.jobs_db_path))
    table.add_row("cvs_dir", str(settings.cvs_dir))
    table.add_row("cache_dir", str(settings.cache_dir))

    # LLM
    table.add_row("llm_provider", settings.llm_provider)
    table.add_row("llm_model", settings.llm_model)
    table.add_row("llm_temperature", str(settings.llm_temperature))
    table.add_row("llm_max_tokens", str(settings.llm_max_tokens))

    # Scraper
    table.add_row("scraper_timeout", f"{settings.scraper_timeout}s")
    table.add_row("scraper_max_retries", str(settings.scraper_max_retries))
    table.add_row("scraper_delay", f"{settings.scraper_delay_min}-{settings.scraper_delay_max}s")

    # Matching
    table.add_row("embedding_model", settings.embedding_model)
    table.add_row("match_top_n", str(settings.match_top_n))
    table.add_row("match_min_score", str(settings.match_min_score))

    # CV
    table.add_row("cv_template", settings.cv_template)
    table.add_row("cv_output_formats", ", ".join(settings.cv_output_formats))

    console.print(table)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Chave da configuração"),
    value: str = typer.Argument(..., help="Novo valor"),
):
    """Define uma configuração (salva no .env)."""
    # TODO: Implementar escrita no .env
    console.print(f"[yellow]⚠[/yellow] Config set não implementado ainda")
    console.print(f"   Edite o arquivo .env diretamente")


# ============================================================
# COMMANDS: SCRAPE (Fase 2 - placeholder)
# ============================================================

scrape_app = typer.Typer(name="scrape", help="Scraping de vagas (Fase 2)")
app.add_typer(scrape_app)


@scrape_app.command("linkedin")
def scrape_linkedin(
    query: str = typer.Option("python", "--query", "-q"),
    location: str = typer.Option("Brasil", "--location", "-l"),
    pages: int = typer.Option(3, "--pages", "-p"),
):
    """Scrapa LinkedIn (placeholder)."""
    console.print("[yellow]⚠ LinkedIn scraper não implementado (Fase 2)[/yellow]")


@scrape_app.command("indeed")
def scrape_indeed(
    query: str = typer.Option("python", "--query", "-q"),
    location: str = typer.Option("Brasil", "--location", "-l"),
    pages: int = typer.Option(3, "--pages", "-p"),
):
    """Scrapa Indeed (placeholder)."""
    console.print("[yellow]⚠ Indeed scraper não implementado (Fase 2)[/yellow]")


@scrape_app.command("gupy")
def scrape_gupy(
    query: str = typer.Option("python", "--query", "-q"),
    pages: int = typer.Option(3, "--pages", "-p"),
):
    """Scrapa Gupy (placeholder)."""
    console.print("[yellow]⚠ Gupy scraper não implementado (Fase 2)[/yellow]")


# ============================================================
# COMMANDS: MATCH (Fase 3 - placeholder)
# ============================================================

match_app = typer.Typer(name="match", help="Matching de vagas (Fase 3)")
app.add_typer(match_app)


@match_app.command("run")
def match_run(
    min_score: float = typer.Option(0.3, "--min-score"),
    top_n: int = typer.Option(20, "--top-n"),
    rerank: bool = typer.Option(True, "--rerank/--no-rerank"),
):
    """Executa matching embeddings + LLM (placeholder)."""
    console.print("[yellow]⚠ Matching não implementado (Fase 3)[/yellow]")


@match_app.command("embeddings")
def match_embeddings(
    rebuild: bool = typer.Option(False, "--rebuild"),
):
    """Gerencia cache de embeddings (placeholder)."""
    console.print("[yellow]⚠ Embeddings não implementado (Fase 3)[/yellow]")


# ============================================================
# ENTRY POINT
# ============================================================

def main():
    """Entry point para console script."""
    app()


if __name__ == "__main__":
    main()