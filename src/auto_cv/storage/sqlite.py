# -*- coding: utf-8 -*-
"""
Auto-CV - SQLite Storage Module
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Engine, session management, and repository classes for SQLite storage.
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any, Generator
from datetime import datetime

from sqlalchemy import create_engine, Engine, event
from sqlalchemy.orm import sessionmaker, Session, scoped_session
from sqlalchemy.pool import StaticPool
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from auto_cv.config import get_settings
from auto_cv.storage.models import (
    Base,
    Job,
    Application,
    SearchHistory,
    EmbeddingCache,
    Match,
    JobSource,
    ApplicationStatus,
    create_all_tables,
)


# ============================================================
# ENGINE & SESSION (SRP - só gerencia conexão)
# ============================================================

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None
_scoped_session: Optional[scoped_session] = None


def get_engine(settings=None) -> Engine:
    """
    Retorna engine SQLite singleton (thread-safe).

    Configurações:
    - WAL mode para melhor concorrência
    - Foreign keys ON
    - Synchronous NORMAL (balance speed/safety)
    - Cache size aumentado
    """
    global _engine
    if _engine is not None:
        return _engine

    settings = settings or get_settings()
    settings.ensure_directories()

    db_path = settings.jobs_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # SQLite URL
    url = f"sqlite:///{db_path}"

    # Engine com pool StaticPool (SQLite file-based)
    _engine = create_engine(
        url,
        poolclass=StaticPool,
        connect_args={
            "check_same_thread": False,  # Permite multi-thread
            "timeout": 30,
        },
        echo=False,
        future=True,
    )

    # Configurações SQLite via event listeners
    @event.listens_for(_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # WAL mode - melhor concorrência readers/writers
        cursor.execute("PRAGMA journal_mode=WAL")
        # Foreign keys
        cursor.execute("PRAGMA foreign_keys=ON")
        # Synchronous NORMAL - bom equilíbrio velocidade/segurança
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Cache size: -32000 = 32MB (negativo = KB)
        cursor.execute("PRAGMA cache_size=-32000")
        # Temp store em memoria
        cursor.execute("PRAGMA temp_store=MEMORY")
        # Mmap size 256MB
        cursor.execute("PRAGMA mmap_size=268435456")
        # Page size 4096 (padrão moderno)
        cursor.execute("PRAGMA page_size=4096")
        cursor.close()

    return _engine


def get_session_factory(settings=None) -> sessionmaker:
    """Retorna session factory (non-scoped)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(settings),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )
    return _session_factory


def get_scoped_session(settings=None) -> scoped_session:
    """Retorna scoped session (thread-local)."""
    global _scoped_session
    if _scoped_session is None:
        _scoped_session = scoped_session(get_session_factory(settings))
    return _scoped_session


def get_session(settings=None) -> Session:
    """Retorna nova session (para uso direto)."""
    return get_session_factory(settings)()


@contextmanager
def session_scope(settings=None) -> Generator[Session, None, None]:
    """
    Context manager para transação automática.

    Usage:
        with session_scope() as session:
            session.add(obj)
            # commit automático no fim, rollback em exception
    """
    session = get_session(settings)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(settings=None) -> None:
    """Inicializa banco: cria tabelas se não existem."""
    engine = get_engine(settings)
    create_all_tables(engine)


def close_db() -> None:
    """Fecha conexões (cleanup)."""
    global _engine, _session_factory, _scoped_session
    if _scoped_session:
        _scoped_session.remove()
        _scoped_session = None
    if _session_factory:
        _session_factory = None
    if _engine:
        _engine.dispose()
        _engine = None


# ============================================================
# REPOSITORY BASE (OCP - padrão comum para CRUD)
# ============================================================

class BaseRepository:
    """Base para repositórios com retry em operações de escrita."""

    def __init__(self, session: Optional[Session] = None, settings=None):
        self._session = session
        self._settings = settings or get_settings()
        self._owns_session = session is None

    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = get_session(self._settings)
        return self._session

    def _get_or_create_session(self) -> Session:
        """Garante session válida."""
        if self._session is None:
            self._session = get_session(self._settings)
            self._owns_session = True
        return self._session

    def close(self) -> None:
        """Fecha session se criada internamente."""
        if self._owns_session and self._session:
            self._session.close()
            self._session = None

    def __enter__(self) -> "BaseRepository":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type:
            self.session.rollback()
        else:
            self.session.commit()
        self.close()


# ============================================================
# JOB REPOSITORY (SRP - só operações de Job)
# ============================================================

class JobRepository(BaseRepository):
    """CRUD + queries específicas para Job."""

    # --------------------------------------------------------
    # UPSERT (idempotente por source+external_id)
    # --------------------------------------------------------

    def upsert(self, job: Job) -> Job:
        """
        Insere ou atualiza Job por (source, external_id).

        Retorna Job com ID preenchido.
        """
        existing = self.find_by_source_external(job.source, job.external_id)

        def _to_datetime(val):
            if val is None:
                return None
            if isinstance(val, str):
                try:
                    return datetime.fromisoformat(val)
                except (ValueError, TypeError):
                    return None
            return val

        if existing:
            # Atualiza apenas campos não-None do novo job
            update_fields = {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "work_mode": job.work_mode,
                "job_type": job.job_type,
                "description": job.description,
                "description_html": job.description_html,
                "raw_data": job.raw_data,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "salary_currency": job.salary_currency,
                "salary_period": job.salary_period,
                "posted_date": _to_datetime(job.posted_date),
                "expires_date": _to_datetime(job.expires_date),
                "is_active": job.is_active,
                "is_duplicate": job.is_duplicate,
                "embedding_id": job.embedding_id,
                "match_score": job.match_score,
                "match_method": job.match_method,
                "matched_at": _to_datetime(job.matched_at),
            }
            for field, value in update_fields.items():
                if value is not None:
                    setattr(existing, field, value)
            existing.updated_at = datetime.utcnow()
            self.session.commit()
            return existing
        else:
            # Also convert dates for new job
            if isinstance(job.posted_date, str):
                job.posted_date = _to_datetime(job.posted_date)
            if isinstance(job.expires_date, str):
                job.expires_date = _to_datetime(job.expires_date)
            if isinstance(job.matched_at, str):
                job.matched_at = _to_datetime(job.matched_at)
            self.session.add(job)
            self.session.commit()
            self.session.refresh(job)
            return job

    def upsert_many(self, jobs: List[Job]) -> List[Job]:
        """Upsert em lote (transação única)."""
        results = []
        for job in jobs:
            results.append(self.upsert(job))
        return results

    # --------------------------------------------------------
    # READ
    # --------------------------------------------------------

    def find_by_id(self, job_id: int) -> Optional[Job]:
        return self.session.query(Job).filter(Job.id == job_id).first()

    def find_by_source_external(self, source: str, external_id: str) -> Optional[Job]:
        return (
            self.session.query(Job)
            .filter(Job.source == source, Job.external_id == external_id)
            .first()
        )

    def find_by_url(self, url: str) -> Optional[Job]:
        return self.session.query(Job).filter(Job.url == url).first()

    def get_active(self, limit: int = 100, offset: int = 0) -> List[Job]:
        return (
            self.session.query(Job)
            .filter(Job.is_active == True)
            .order_by(Job.posted_date.desc().nullslast())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def get_unmatched(self, min_score: float = 0.3, limit: int = 100) -> List[Job]:
        """Vagas ativas sem match ou com score baixo."""
        return (
            self.session.query(Job)
            .filter(Job.is_active == True)
            .filter((Job.match_score.is_(None)) | (Job.match_score < min_score))
            .order_by(Job.posted_date.desc().nullslast())
            .limit(limit)
            .all()
        )

    def get_matched(self, min_score: float = 0.3, limit: int = 50) -> List[Job]:
        """Vagas com match acima do threshold."""
        return (
            self.session.query(Job)
            .filter(Job.is_active == True, Job.match_score >= min_score)
            .order_by(Job.match_score.desc())
            .limit(limit)
            .all()
        )

    def search(
        self,
        query: Optional[str] = None,
        source: Optional[str] = None,
        location: Optional[str] = None,
        work_mode: Optional[str] = None,
        job_type: Optional[str] = None,
        company: Optional[str] = None,
        is_active: Optional[bool] = True,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Job]:
        """Busca flexível com múltiplos filtros."""
        q = self.session.query(Job)

        if is_active is not None:
            q = q.filter(Job.is_active == is_active)
        if query:
            q = q.filter(
                (Job.title.ilike(f"%{query}%")) |
                (Job.company.ilike(f"%{query}%")) |
                (Job.description.ilike(f"%{query}%"))
            )
        if source:
            q = q.filter(Job.source == source)
        if location:
            q = q.filter(Job.location.ilike(f"%{location}%"))
        if work_mode:
            q = q.filter(Job.work_mode == work_mode)
        if job_type:
            q = q.filter(Job.job_type == job_type)
        if company:
            q = q.filter(Job.company.ilike(f"%{company}%"))

        return q.order_by(Job.posted_date.desc().nullslast()).limit(limit).offset(offset).all()

    def count_active(self) -> int:
        return self.session.query(Job).filter(Job.is_active == True).count()

    def count_by_source(self) -> Dict[str, int]:
        from sqlalchemy import func
        results = (
            self.session.query(Job.source, func.count(Job.id))
            .filter(Job.is_active == True)
            .group_by(Job.source)
            .all()
        )
        return {source: count for source, count in results}

    def mark_duplicate(self, job_id: int) -> None:
        job = self.find_by_id(job_id)
        if job:
            job.is_duplicate = True
            self.session.commit()

    def update_match(
        self,
        job_id: int,
        score: float,
        method: str,
        embedding_id: Optional[int] = None,
    ) -> Optional[Job]:
        job = self.find_by_id(job_id)
        if job:
            job.match_score = score
            job.match_method = method
            job.matched_at = datetime.utcnow()
            if embedding_id:
                job.embedding_id = embedding_id
            self.session.commit()
        return job


# ============================================================
# APPLICATION REPOSITORY
# ============================================================

class ApplicationRepository(BaseRepository):
    """CRUD + queries para Application."""

    def create(self, application: Application) -> Application:
        self.session.add(application)
        self.session.commit()
        self.session.refresh(application)
        return application

    def find_by_id(self, app_id: int) -> Optional[Application]:
        return self.session.query(Application).filter(Application.id == app_id).first()

    def find_by_job_profile(self, job_id: int, profile_version: int) -> Optional[Application]:
        return (
            self.session.query(Application)
            .filter(Application.job_id == job_id, Application.profile_version == profile_version)
            .first()
        )

    def get_by_job(self, job_id: int) -> List[Application]:
        return (
            self.session.query(Application)
            .filter(Application.job_id == job_id)
            .order_by(Application.created_at.desc())
            .all()
        )

    def get_by_status(self, status: str, limit: int = 50) -> List[Application]:
        return (
            self.session.query(Application)
            .filter(Application.status == status)
            .order_by(Application.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_pipeline(self, profile_version: int = 1) -> Dict[str, List[Application]]:
        """Retorna aplicações agrupadas por status (kanban)."""
        apps = (
            self.session.query(Application)
            .filter(Application.profile_version == profile_version)
            .order_by(Application.created_at.desc())
            .all()
        )
        result = {}
        for app in apps:
            result.setdefault(app.status, []).append(app)
        return result

    def update_status(
        self,
        app_id: int,
        status: str,
        **extra_fields
    ) -> Optional[Application]:
        app = self.find_by_id(app_id)
        if app:
            app.status = status
            for k, v in extra_fields.items():
                if hasattr(app, k):
                    setattr(app, k, v)
            if status == ApplicationStatus.APPLIED.value:
                app.applied_at = datetime.utcnow()
            elif status == ApplicationStatus.CV_GENERATED.value:
                app.cv_generated_at = datetime.utcnow()
            self.session.commit()
        return app

    def update_match(self, app_id: int, score: float, method: str, details: Optional[Dict] = None) -> Optional[Application]:
        app = self.find_by_id(app_id)
        if app:
            app.match_score = score
            app.match_method = method
            if details:
                app.match_details = details
            self.session.commit()
        return app

    def set_cv_paths(self, app_id: int, pdf_path: Optional[str] = None, md_path: Optional[str] = None) -> Optional[Application]:
        app = self.find_by_id(app_id)
        if app:
            if pdf_path:
                app.cv_pdf_path = pdf_path
            if md_path:
                app.cv_md_path = md_path
            app.cv_generated_at = datetime.utcnow()
            self.session.commit()
        return app

    def count_by_status(self, profile_version: int = 1) -> Dict[str, int]:
        from sqlalchemy import func
        results = (
            self.session.query(Application.status, func.count(Application.id))
            .filter(Application.profile_version == profile_version)
            .group_by(Application.status)
            .all()
        )
        return {status: count for status, count in results}


# ============================================================
# SEARCH HISTORY REPOSITORY
# ============================================================

class SearchHistoryRepository(BaseRepository):
    """CRUD para SearchHistory."""

    def create(self, history: SearchHistory) -> SearchHistory:
        self.session.add(history)
        self.session.commit()
        self.session.refresh(history)
        return history

    def update(self, history_id: int, **kwargs) -> Optional[SearchHistory]:
        """Update search history fields."""
        history = self.session.query(SearchHistory).filter(SearchHistory.id == history_id).first()
        if history:
            for key, value in kwargs.items():
                if hasattr(history, key):
                    setattr(history, key, value)
            self.session.commit()
        return history

    def get_recent(self, limit: int = 20) -> List[SearchHistory]:
        return (
            self.session.query(SearchHistory)
            .order_by(SearchHistory.executed_at.desc())
            .limit(limit)
            .all()
        )

    def get_by_source(self, source: str, limit: int = 50) -> List[SearchHistory]:
        return (
            self.session.query(SearchHistory)
            .filter(SearchHistory.source == source)
            .order_by(SearchHistory.executed_at.desc())
            .limit(limit)
            .all()
        )

    def get_stats(self, days: int = 30) -> Dict[str, Any]:
        from sqlalchemy import func
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(days=days)

        total_searches = (
            self.session.query(func.count(SearchHistory.id))
            .filter(SearchHistory.executed_at >= cutoff)
            .scalar()
        )

        total_results = (
            self.session.query(func.sum(SearchHistory.results_count))
            .filter(SearchHistory.executed_at >= cutoff)
            .scalar() or 0
        )

        total_new = (
            self.session.query(func.sum(SearchHistory.new_jobs_count))
            .filter(SearchHistory.executed_at >= cutoff)
            .scalar() or 0
        )

        total_matched = (
            self.session.query(func.sum(SearchHistory.matched_jobs_count))
            .filter(SearchHistory.executed_at >= cutoff)
            .scalar() or 0
        )

        avg_duration = (
            self.session.query(func.avg(SearchHistory.duration_seconds))
            .filter(SearchHistory.executed_at >= cutoff, SearchHistory.duration_seconds.isnot(None))
            .scalar()
        )

        return {
            "period_days": days,
            "total_searches": total_searches or 0,
            "total_results": total_results,
            "total_new_jobs": total_new,
            "total_matched": total_matched,
            "avg_duration_seconds": round(avg_duration, 2) if avg_duration else 0,
        }


# ============================================================
# EMBEDDING CACHE REPOSITORY
# ============================================================

class EmbeddingCacheRepository(BaseRepository):
    """CRUD para EmbeddingCache (get/set por hash)."""

    def get(self, content_hash: str, model_name: str) -> Optional[EmbeddingCache]:
        return (
            self.session.query(EmbeddingCache)
            .filter(EmbeddingCache.content_hash == content_hash, EmbeddingCache.model_name == model_name)
            .first()
        )

    def get_vector(self, content_hash: str, model_name: str) -> Optional[List[float]]:
        """Retorna vetor desserializado ou None."""
        import json
        entry = self.get(content_hash, model_name)
        if entry:
            entry.hit_count += 1
            entry.last_accessed = datetime.utcnow()
            self.session.commit()
            return json.loads(entry.vector_blob)
        return None

    def set(self, content_hash: str, content_type: str, model_name: str, vector: List[float], preview: str = "") -> EmbeddingCache:
        import json
        entry = self.get(content_hash, model_name)

        if entry:
            entry.vector_blob = json.dumps(vector)
            entry.dimensions = len(vector)
            entry.content_preview = preview
            entry.hit_count += 1
            entry.last_accessed = datetime.utcnow()
        else:
            entry = EmbeddingCache(
                content_hash=content_hash,
                content_type=content_type,
                model_name=model_name,
                vector_blob=json.dumps(vector),
                dimensions=len(vector),
                content_preview=preview,
            )
            self.session.add(entry)

        self.session.commit()
        self.session.refresh(entry)
        return entry

    def delete_old(self, max_age_days: int = 90, max_entries: int = 10000) -> int:
        """Limpa cache antigo (LRU + TTL)."""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)

        # Deleta por idade
        deleted = (
            self.session.query(EmbeddingCache)
            .filter(EmbeddingCache.last_accessed < cutoff)
            .delete(synchronize_session=False)
        )

        # Se ainda excede max_entries, deleta menos acessados
        total = self.count()
        if total > max_entries:
            excess = total - max_entries
            oldest = (
                self.session.query(EmbeddingCache.id)
                .order_by(EmbeddingCache.hit_count.asc(), EmbeddingCache.last_accessed.asc())
                .limit(excess)
                .subquery()
            )
            deleted += self.session.query(EmbeddingCache).filter(EmbeddingCache.id.in_(oldest)).delete(synchronize_session=False)

        self.session.commit()
        return deleted

    def count(self) -> int:
        """Conta total de entradas no cache."""
        from sqlalchemy import func
        return self.session.query(func.count(EmbeddingCache.id)).scalar() or 0

    def get_stats(self) -> Dict[str, Any]:
        from sqlalchemy import func
        total = self.session.query(func.count(EmbeddingCache.id)).scalar() or 0
        by_model = dict(
            self.session.query(EmbeddingCache.model_name, func.count(EmbeddingCache.id))
            .group_by(EmbeddingCache.model_name)
            .all()
        )
        by_type = dict(
            self.session.query(EmbeddingCache.content_type, func.count(EmbeddingCache.id))
            .group_by(EmbeddingCache.content_type)
            .all()
        )
        total_hits = self.session.query(func.sum(EmbeddingCache.hit_count)).scalar() or 0
        return {
            "total_entries": total,
            "by_model": by_model,
            "by_type": by_type,
            "total_hits": total_hits,
        }


# ============================================================
# MATCH REPOSITORY
# ============================================================

class MatchRepository(BaseRepository):
    """CRUD para Match (profile-job matches)."""

    def upsert(
        self,
        profile_id: int,
        job_id: int,
        score: float,
        match_method: str,
        match_details: Optional[Dict] = None,
    ) -> Match:
        """Insere ou atualiza match."""
        existing = (
            self.session.query(Match)
            .filter(Match.profile_id == profile_id, Match.job_id == job_id)
            .first()
        )

        if existing:
            existing.score = score
            existing.match_method = match_method
            if match_details:
                existing.match_details = match_details
            existing.created_at = datetime.utcnow()
        else:
            existing = Match(
                profile_id=profile_id,
                job_id=job_id,
                score=score,
                match_method=match_method,
                match_details=match_details or {},
            )
            self.session.add(existing)

        self.session.commit()
        self.session.refresh(existing)
        return existing

    def get_by_profile(self, profile_id: int, min_score: float = 0.0, limit: int = 50) -> List[Match]:
        """Busca matches de um perfil."""
        return (
            self.session.query(Match)
            .filter(Match.profile_id == profile_id, Match.score >= min_score)
            .order_by(Match.score.desc())
            .limit(limit)
            .all()
        )

    def get_by_job(self, job_id: int, limit: int = 50) -> List[Match]:
        """Busca matches de uma vaga."""
        return (
            self.session.query(Match)
            .filter(Match.job_id == job_id)
            .order_by(Match.score.desc())
            .limit(limit)
            .all()
        )

    def delete_old(self, max_age_days: int = 90) -> int:
        """Remove matches antigos."""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        deleted = (
            self.session.query(Match)
            .filter(Match.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        self.session.commit()
        return deleted


# ============================================================
# FACTORY / CONVENIENCE (OCP - fácil trocar implementação)
# ============================================================

def get_job_repo(session: Optional[Session] = None, settings=None) -> JobRepository:
    return JobRepository(session, settings)


def get_application_repo(session: Optional[Session] = None, settings=None) -> ApplicationRepository:
    return ApplicationRepository(session, settings)


def get_search_history_repo(session: Optional[Session] = None, settings=None) -> SearchHistoryRepository:
    return SearchHistoryRepository(session, settings)


def get_embedding_cache_repo(session: Optional[Session] = None, settings=None) -> EmbeddingCacheRepository:
    return EmbeddingCacheRepository(session, settings)


def get_match_repo(session: Optional[Session] = None, settings=None) -> MatchRepository:
    return MatchRepository(session, settings)


# Context managers para uso direto
@contextmanager
def job_repo_scope(settings=None) -> Generator[JobRepository, None, None]:
    with session_scope(settings) as session:
        yield JobRepository(session, settings)

@contextmanager
def application_repo_scope(settings=None) -> Generator[ApplicationRepository, None, None]:
    with session_scope(settings) as session:
        yield ApplicationRepository(session, settings)

@contextmanager
def search_history_repo_scope(settings=None) -> Generator[SearchHistoryRepository, None, None]:
    with session_scope(settings) as session:
        yield SearchHistoryRepository(session, settings)

@contextmanager
def embedding_cache_repo_scope(settings=None) -> Generator[EmbeddingCacheRepository, None, None]:
    with session_scope(settings) as session:
        yield EmbeddingCacheRepository(session, settings)


@contextmanager
def match_repo_scope(settings=None) -> Generator[MatchRepository, None, None]:
    with session_scope(settings) as session:
        yield MatchRepository(session, settings)


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Engine/Session
    "get_engine",
    "get_session_factory",
    "get_scoped_session",
    "get_session",
    "session_scope",
    "init_db",
    "close_db",
    # Repositories
    "BaseRepository",
    "JobRepository",
    "ApplicationRepository",
    "SearchHistoryRepository",
    "EmbeddingCacheRepository",
    "MatchRepository",
    # Factories
    "get_job_repo",
    "get_application_repo",
    "get_search_history_repo",
    "get_embedding_cache_repo",
    "get_match_repo",
    # Scoped context managers
    "job_repo_scope",
    "application_repo_scope",
    "search_history_repo_scope",
    "embedding_cache_repo_scope",
    "match_repo_scope",
]