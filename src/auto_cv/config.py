# -*- coding: utf-8 -*-
"""
Auto-CV - Configuration Module
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Central configuration using Pydantic Settings with env var support.
"""

from pathlib import Path
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, computed_field


class Settings(BaseSettings):
    """
    Configurações globais da aplicação.

    Single Responsibility: Apenas gerencia configuração (SRP).
    Open/Closed: Extensível via herança ou novos campos sem modificar existentes (OCP).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ============================================================
    # PATHS
    # ============================================================
    data_dir: Path = Field(
        default=Path("data"),
        description="Diretório base para dados (profile, jobs.db, cvs, cache)",
    )
    profile_path: Path = Field(
        default=Path("data/profile.yaml"),
        description="Caminho do arquivo de perfil do usuário",
    )
    jobs_db_path: Path = Field(
        default=Path("data/jobs.db"),
        description="Caminho do banco SQLite de vagas",
    )
    cvs_dir: Path = Field(
        default=Path("data/cvs"),
        description="Diretório para CVs gerados",
    )
    cache_dir: Path = Field(
        default=Path("data/cache"),
        description="Diretório para cache (embeddings, etc.)",
    )

    # ============================================================
    # LLM PROVIDER (Strategy Pattern ready - OCP)
    # ============================================================
    llm_provider: str = Field(
        default="anthropic",
        description="Provedor LLM: 'anthropic' | 'claude-cli' | 'ollama'",
    )
    llm_model: str = Field(
        default="claude-sonnet-5-5",
        description="Modelo a usar (ex: claude-sonnet-5-5, llama3.2, etc.)",
    )
    anthropic_api_key: Optional[str] = Field(
        default=None,
        description="API Key Anthropic (opcional se usar claude-cli)",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="URL base do Ollama (se provider=ollama)",
    )
    llm_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Temperatura para geração (0.0-1.0)",
    )
    llm_max_tokens: int = Field(
        default=4000,
        gt=0,
        description="Max tokens na resposta",
    )

    # ============================================================
    # SCRAPER
    # ============================================================
    scraper_timeout: int = Field(
        default=30,
        gt=0,
        description="Timeout HTTP em segundos",
    )
    scraper_max_retries: int = Field(
        default=3,
        ge=0,
        description="Máximo de tentativas por request",
    )
    scraper_delay_min: float = Field(
        default=1.0,
        ge=0.0,
        description="Delay mínimo entre requests (segundos)",
    )
    scraper_delay_max: float = Field(
        default=3.0,
        ge=0.0,
        description="Delay máximo entre requests (segundos)",
    )
    linkedin_cookies: Optional[str] = Field(
        default=None,
        description="Cookies do LinkedIn para scraping autenticado (opcional)",
    )

    # ============================================================
    # MATCHING / EMBEDDINGS
    # ============================================================
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Modelo sentence-transformers para embeddings",
    )
    embedding_cache: bool = Field(
        default=True,
        description="Cachear embeddings em disco",
    )
    match_top_n: int = Field(
        default=20,
        gt=0,
        description="Top N vagas para passar pro LLM ranker",
    )
    match_min_score: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Score mínimo de similaridade (0-1) para considerar match",
    )

    # ============================================================
    # CV GENERATION
    # ============================================================
    cv_template: str = Field(
        default="base",
        description="Template base do CV (YAML)",
    )
    cv_output_formats: List[str] = Field(
        default=["pdf", "md"],
        description="Formatos de saída: pdf, md, html",
    )

    # ============================================================
    # CLI
    # ============================================================
    cli_rich_output: bool = Field(
        default=True,
        description="Usar Rich para output colorido",
    )
    cli_page_size: int = Field(
        default=20,
        gt=0,
        description="Itens por página nas listagens",
    )

    # ============================================================
    # COMPUTED PROPERTIES (Lazy - sem side effects no __init__)
    # ============================================================
    @computed_field
    @property
    def jobs_db_url(self) -> str:
        """URL de conexão SQLite (computed field)."""
        return f"sqlite:///{self.jobs_db_path}"

    @computed_field
    @property
    def embedding_cache_dir(self) -> Path:
        """Diretório de cache de embeddings."""
        return self.cache_dir / "embeddings"

    # ============================================================
    # DIRECTORY MANAGEMENT (Lazy initialization - SRP)
    # ============================================================
    def ensure_directories(self) -> None:
        """
        Cria diretórios necessários.
        Called explicitly (não no __init__) para evitar side effects.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cvs_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_cache_dir.mkdir(parents=True, exist_ok=True)


# ============================================================
# FACTORY / DEPENDENCY INJECTION (OCP - fácil de mockar em testes)
# ============================================================
def create_settings(**overrides) -> Settings:
    """
    Factory para criar Settings.
    Permite overrides para testes sem modificar singleton global.
    """
    return Settings(**overrides)


# Singleton global (padrão para CLI)
settings = Settings()


def get_settings() -> Settings:
    """Dependency injection para testes - retorna singleton ou override."""
    return settings