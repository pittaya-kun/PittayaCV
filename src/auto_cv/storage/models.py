# -*- coding: utf-8 -*-
"""
Auto-CV - Storage Models Module
Version: 1.0.0
Author: Pittaya
License: MIT
Description: SQLAlchemy models for jobs, applications, search history, and embedding cache.
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Float, Boolean,
    ForeignKey, Index, UniqueConstraint, JSON
)
from sqlalchemy.orm import relationship, declarative_base, declared_attr
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON

from auto_cv.config import get_settings


# ============================================================
# BASE & MIXINS (OCP - extensível sem modificar)
# ============================================================

Base = declarative_base()

# Schema version para migrações futuras
SCHEMA_VERSION = 1


class TimestampMixin:
    """Mixin para created_at/updated_at automáticos."""

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ============================================================
# ENUMS (Single Responsibility: cada enum uma responsabilidade)
# ============================================================

class JobSource(str, PyEnum):
    """Fontes de vagas suportadas."""
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    GLASSDOOR = "glassdoor"
    GUPY = "gupy"
    VAGAS_COM = "vagas.com"
    WELLFOUND = "wellfound"
    REMOTEOK = "remoteok"
    MANUAL = "manual"
    OTHER = "other"


class ApplicationStatus(str, PyEnum):
    """Status da candidatura."""
    NEW = "new"                    # Vaga encontrada, não analisada
    MATCHED = "matched"            # Passou no matching (embedding + LLM)
    CV_GENERATED = "cv_generated"  # CV personalizado gerado
    APPLIED = "applied"            # Candidatura enviada (manual)
    REJECTED = "rejected"          # Rejeitado
    INTERVIEW = "interview"        # Em processo seletivo
    OFFER = "offer"                # Recebeu proposta
    ARCHIVED = "archived"          # Arquivado pelo usuário


class MatchMethod(str, PyEnum):
    """Método usado para calcular match."""
    EMBEDDING = "embedding"        # Apenas cosine similarity
    LLM_RERANK = "llm_rerank"      # Embedding + LLM reranker
    HYBRID = "hybrid"              # Combinação ponderada
    MANUAL = "manual"              # Score manual


# ============================================================
# MODELS (SRP - cada model uma tabela, uma responsabilidade)
# ============================================================

class Job(Base, TimestampMixin):
    """
    Vaga de emprego (scraped ou manual).

    Single Responsibility: Armazena dados brutos e processados da vaga.
    Open/Closed: Novos campos via JSON raw_data sem migration.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        # Composite/unique indexes (não dá pra fazer com index=True)
        Index("ix_jobs_source_external_id", "source", "external_id", unique=True),
        Index("ix_jobs_title_company", "title", "company"),
        # Single-column indexes já definidos via index=True nas colunas
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identificação única por fonte
    source = Column(String(50), nullable=False, index=True)          # JobSource
    external_id = Column(String(200), nullable=False, index=True)    # ID original da fonte
    url = Column(String(1000), nullable=False, unique=True)          # URL canônica

    # Dados principais
    title = Column(String(300), nullable=False, index=True)
    company = Column(String(200), nullable=False, index=True)
    location = Column(String(200), nullable=True, index=True)
    work_mode = Column(String(20), nullable=True)                    # remote/hybrid/onsite
    job_type = Column(String(20), nullable=True)                     # full-time/contract/etc

    # Descrição
    description = Column(Text, nullable=True)                        # Texto limpo
    description_html = Column(Text, nullable=True)                   # HTML original
    raw_data = Column(SQLiteJSON, nullable=True)                     # JSON bruto completo (OCP)

    # Salário (se disponível)
    salary_min = Column(Integer, nullable=True)
    salary_max = Column(Integer, nullable=True)
    salary_currency = Column(String(10), default="BRL")
    salary_period = Column(String(20), default="monthly")            # monthly/yearly/hourly

    # Datas
    posted_date = Column(DateTime, nullable=True, index=True)
    expires_date = Column(DateTime, nullable=True)
    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Status
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_duplicate = Column(Boolean, default=False, nullable=False)    # Detectado como dup

    # Matching (preenchido pelo pipeline)
    embedding_id = Column(Integer, nullable=True)                    # Ref ao EmbeddingCache
    match_score = Column(Float, nullable=True)                       # 0-1
    match_method = Column(String(20), nullable=True)                 # MatchMethod
    matched_at = Column(DateTime, nullable=True)

    # Relacionamentos
    applications = relationship("Application", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, title='{self.title[:50]}', company='{self.company}')>"

    @property
    def source_enum(self) -> JobSource:
        """Retorna enum da fonte."""
        try:
            return JobSource(self.source)
        except ValueError:
            return JobSource.OTHER


class Application(Base, TimestampMixin):
    """
    Candidatura do usuário a uma vaga.

    Single Responsibility: Rastreia estado da candidatura do usuário.
    Open/Closed: Campos extras via JSON metadata.
    """

    __tablename__ = "applications"
    __table_args__ = (
        # job_id e status já têm index=True nas colunas
        Index("ix_applications_profile_version", "profile_version"),
        # created_at do TimestampMixin não tem index - adicionar se necessário
        UniqueConstraint("job_id", "profile_version", name="uq_app_job_profile"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # FK
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)

    # Versão do perfil usado (para reprodutibilidade)
    profile_version = Column(Integer, default=1, nullable=False)

    # Status pipeline
    status = Column(String(20), default=ApplicationStatus.NEW.value, nullable=False, index=True)

    # Matching
    match_score = Column(Float, nullable=True)                       # 0-1 final
    match_method = Column(String(20), nullable=True)                 # MatchMethod
    match_details = Column(SQLiteJSON, nullable=True)                # Breakdown do score

    # CV gerado
    cv_pdf_path = Column(String(500), nullable=True)
    cv_md_path = Column(String(500), nullable=True)
    cv_template = Column(String(50), default="base")
    cv_generated_at = Column(DateTime, nullable=True)

    # Ação do usuário
    applied_at = Column(DateTime, nullable=True)
    applied_method = Column(String(50), nullable=True)               # manual/email/linkedin/easyapply
    notes = Column(Text, nullable=True)                              # Notas pessoais

    # Metadados extras (OCP)
    metadata_json = Column(SQLiteJSON, nullable=True)

    # Relacionamentos
    job = relationship("Job", back_populates="applications")

    def __repr__(self) -> str:
        return f"<Application(id={self.id}, job_id={self.job_id}, status='{self.status}')>"

    @property
    def status_enum(self) -> ApplicationStatus:
        try:
            return ApplicationStatus(self.status)
        except ValueError:
            return ApplicationStatus.NEW

    @property
    def match_method_enum(self) -> Optional[MatchMethod]:
        if not self.match_method:
            return None
        try:
            return MatchMethod(self.match_method)
        except ValueError:
            return None


class SearchHistory(Base, TimestampMixin):
    """
    Histórico de buscas executadas.

    Single Responsibility: Auditoria e analytics de buscas.
    Open/Closed: Filtros flexíveis via JSON.
    """

    __tablename__ = "search_history"
    __table_args__ = (
        Index("ix_search_history_query", "query"),  # query não tem index=True
        # source e executed_at já têm index=True nas colunas
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Query executada
    query = Column(String(500), nullable=True)                       # Texto livre
    source = Column(String(50), nullable=False, index=True)          # JobSource
    filters = Column(SQLiteJSON, nullable=True)                      # Filtros aplicados (JSON)

    # Resultados
    results_count = Column(Integer, default=0, nullable=False)
    new_jobs_count = Column(Integer, default=0, nullable=False)      # Novos (não dup)
    matched_jobs_count = Column(Integer, default=0, nullable=False)  # Acima do threshold

    # Execução
    executed_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    duration_seconds = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)

    # Metadados
    metadata_json = Column(SQLiteJSON, nullable=True)

    def __repr__(self) -> str:
        return f"<SearchHistory(id={self.id}, query='{self.query[:30] if self.query else 'N/A'}', results={self.results_count})>"


class EmbeddingCache(Base, TimestampMixin):
    """
    Cache de embeddings para evitar recomputação.

    Single Responsibility: Armazena vetores de embedding com hash de conteúdo.
    Open/Closed: Modelo versionado via model_name.
    """

    __tablename__ = "embedding_cache"
    __table_args__ = (
        # content_hash e model_name já têm index=True (content_hash também unique=True)
        # created_at do TimestampMixin não tem index - adicionar se necessário
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identificação do conteúdo
    content_hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA256 do texto
    content_type = Column(String(50), nullable=False)                           # "job_description" | "profile" | "cv"
    content_preview = Column(String(200), nullable=True)                        # Primeiros 200 chars

    # Embedding
    model_name = Column(String(100), nullable=False, index=True)                # ex: "all-MiniLM-L6-v2"
    vector_blob = Column(Text, nullable=False)                                  # JSON array de floats
    dimensions = Column(Integer, nullable=False)                                # Tamanho do vetor

    # Stats
    hit_count = Column(Integer, default=0, nullable=False)
    last_accessed = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<EmbeddingCache(id={self.id}, hash={self.content_hash[:12]}, model={self.model_name})>"


class Match(Base, TimestampMixin):
    """
    Match entre perfil e vaga.

    Single Responsibility: Armazena resultado do matching para reprodutibilidade.
    Open/Closed: Detalhes do score via JSON match_details.
    """

    __tablename__ = "matches"
    __table_args__ = (
        Index("ix_matches_profile_id", "profile_id"),
        Index("ix_matches_job_id", "job_id"),
        UniqueConstraint("profile_id", "job_id", name="uq_match_profile_job"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # FKs
    profile_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)

    # Score
    score = Column(Float, nullable=False, index=True)                           # 0-1
    match_method = Column(String(20), nullable=False)                           # MatchMethod
    match_details = Column(SQLiteJSON, nullable=True)                           # Breakdown (cosine, llm, reasoning)

    # Relacionamento
    job = relationship("Job", backref="matches")

    def __repr__(self) -> str:
        return f"<Match(id={self.id}, profile={self.profile_id}, job={self.job_id}, score={self.score:.3f})>"


# ============================================================
# SCHEMA MANAGEMENT (SRP - separado dos models)
# ============================================================

def create_all_tables(engine) -> None:
    """Cria todas as tabelas no banco."""
    Base.metadata.create_all(engine)


def drop_all_tables(engine) -> None:
    """Remove todas as tabelas (CUIDADO: destrutivo)."""
    Base.metadata.drop_all(engine)


def get_table_names() -> List[str]:
    """Retorna nomes das tabelas definidas."""
    return list(Base.metadata.tables.keys())


# ============================================================
# MODEL FACTORIES (OCP - fácil criar instâncias para testes)
# ============================================================

def create_job(
    source: str,
    external_id: str,
    url: str,
    title: str,
    company: str,
    **kwargs
) -> Job:
    """Factory para criar Job com defaults sensatos."""
    return Job(
        source=source,
        external_id=external_id,
        url=url,
        title=title,
        company=company,
        **kwargs
    )


def create_application(
    job_id: int,
    profile_version: int = 1,
    **kwargs
) -> Application:
    """Factory para criar Application."""
    return Application(
        job_id=job_id,
        profile_version=profile_version,
        **kwargs
    )


def create_search_history(
    source: str,
    query: Optional[str] = None,
    **kwargs
) -> SearchHistory:
    """Factory para criar SearchHistory."""
    return SearchHistory(
        source=source,
        query=query,
        **kwargs
    )


def create_embedding_cache(
    content_hash: str,
    content_type: str,
    model_name: str,
    vector: List[float],
    **kwargs
) -> EmbeddingCache:
    """Factory para criar EmbeddingCache."""
    import json
    return EmbeddingCache(
        content_hash=content_hash,
        content_type=content_type,
        model_name=model_name,
        vector_blob=json.dumps(vector),
        dimensions=len(vector),
        **kwargs
    )


def create_match(
    profile_id: int,
    job_id: int,
    score: float,
    match_method: str,
    **kwargs
) -> Match:
    """Factory para criar Match."""
    return Match(
        profile_id=profile_id,
        job_id=job_id,
        score=score,
        match_method=match_method,
        **kwargs
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Base
    "Base",
    "SCHEMA_VERSION",
    "TimestampMixin",
    # Enums
    "JobSource",
    "ApplicationStatus",
    "MatchMethod",
    # Models
    "Job",
    "Application",
    "SearchHistory",
    "EmbeddingCache",
    "Match",
    # Schema management
    "create_all_tables",
    "drop_all_tables",
    "get_table_names",
    # Factories
    "create_job",
    "create_application",
    "create_search_history",
    "create_embedding_cache",
    "create_match",
]