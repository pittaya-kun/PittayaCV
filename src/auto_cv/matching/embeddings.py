# -*- coding: utf-8 -*-
"""
Auto-CV - Embeddings Module
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Local embeddings using sentence-transformers for job/profile matching.
"""

import hashlib
import json
import os
import pickle
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer

from auto_cv.config import get_settings
from auto_cv.storage.models import EmbeddingCache
from auto_cv.storage.sqlite import EmbeddingCacheRepository, session_scope


# ============================================================
# CONSTANTS
# ============================================================

DEFAULT_MODEL = "all-MiniLM-L6-v2"  # 384 dims, fast, good for semantic search
EMBEDDING_DIM = 384
CACHE_TTL_DAYS = 30


# ============================================================
# EMBEDDING MANAGER (SRP - only embedding concerns)
# ============================================================

class EmbeddingManager:
    """
    Manages local embeddings with caching.

    Features:
    - sentence-transformers model (CPU by default, GPU if available)
    - SQLite cache with TTL + LRU eviction
    - File-based backup cache (pickle) for fast startup
    - Batch encoding for efficiency
    """

    _instance: Optional["EmbeddingManager"] = None
    _model: Optional[SentenceTransformer] = None

    def __new__(cls, *args, **kwargs) -> "EmbeddingManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        cache_dir: Optional[Path] = None,
        device: Optional[str] = None,
        settings=None,
    ):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self.settings = settings or get_settings()
        self.model_name = model_name
        self.device = device or ("cuda" if self._has_cuda() else "cpu")

        # Cache directory
        self.cache_dir = cache_dir or self.settings.embedding_cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "embeddings_cache.pkl"

        # In-memory cache
        self._memory_cache: Dict[str, np.ndarray] = {}
        self._cache_hits = 0
        self._cache_misses = 0

        self._initialized = True

    def _has_cuda(self) -> bool:
        """Check if CUDA is available."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    @property
    def model(self) -> SentenceTransformer:
        """Lazy-load model."""
        if self._model is None:
            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def encode(
        self,
        texts: List[str],
        batch_size: int = 32,
        show_progress: bool = False,
        normalize: bool = True,
    ) -> np.ndarray:
        """
        Encode texts to embeddings.

        Args:
            texts: List of texts to encode
            batch_size: Batch size for encoding
            show_progress: Show progress bar
            normalize: L2-normalize embeddings (for cosine similarity)

        Returns:
            numpy array of shape (n_texts, embedding_dim)
        """
        if not texts:
            return np.empty((0, EMBEDDING_DIM), dtype=np.float32)

        # Check cache first
        cached_embeddings = []
        uncached_texts = []
        uncached_indices = []

        for i, text in enumerate(texts):
            cache_key = self._cache_key(text)
            cached = self._get_cached(cache_key)
            if cached is not None:
                cached_embeddings.append((i, cached))
                self._cache_hits += 1
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)
                self._cache_misses += 1

        # Encode uncached texts
        new_embeddings = []
        if uncached_texts:
            new_embeddings = self.model.encode(
                uncached_texts,
                batch_size=batch_size,
                show_progress_bar=show_progress,
                normalize_embeddings=normalize,
                convert_to_numpy=True,
            )
            # Cache new embeddings
            for text, emb in zip(uncached_texts, new_embeddings):
                cache_key = self._cache_key(text)
                self._set_cached(cache_key, emb)

        # Combine cached + new in original order
        result = np.empty((len(texts), EMBEDDING_DIM), dtype=np.float32)
        for idx, emb in cached_embeddings:
            result[idx] = emb
        for idx, emb in zip(uncached_indices, new_embeddings):
            result[idx] = emb

        return result

    def encode_single(self, text: str, normalize: bool = True) -> np.ndarray:
        """Encode a single text."""
        return self.encode([text], normalize=normalize)[0]

    def _cache_key(self, text: str) -> str:
        """Generate cache key from text."""
        # Include model name in key for safety
        content = f"{self.model_name}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _get_cached(self, key: str) -> Optional[np.ndarray]:
        """Get embedding from cache (memory -> SQLite -> file)."""
        # Memory cache
        if key in self._memory_cache:
            return self._memory_cache[key]

        # SQLite cache
        with session_scope() as session:
            repo = EmbeddingCacheRepository(session)
            cached = repo.get(key, self.model_name)
            if cached and cached.embedding is not None:
                emb = np.frombuffer(cached.embedding, dtype=np.float32)
                self._memory_cache[key] = emb
                return emb

        # File cache (backup)
        file_cache = self._load_file_cache()
        if key in file_cache:
            emb = file_cache[key]
            self._memory_cache[key] = emb
            # Also save to SQLite for next time
            self._save_to_sqlite(key, emb)
            return emb

        return None

    def _set_cached(self, key: str, embedding: np.ndarray) -> None:
        """Set embedding in all cache layers."""
        self._memory_cache[key] = embedding
        self._save_to_sqlite(key, embedding)
        # File cache updated periodically via _persist_file_cache

    def _save_to_sqlite(self, key: str, embedding: np.ndarray) -> None:
        """Save embedding to SQLite."""
        try:
            with session_scope() as session:
                repo = EmbeddingCacheRepository(session)
                repo.upsert(key, embedding.tobytes(), self.model_name)
        except Exception:
            pass  # Cache failures shouldn't break encoding

    def _load_file_cache(self) -> Dict[str, np.ndarray]:
        """Load file-based cache."""
        if not self.cache_file.exists():
            return {}
        try:
            with open(self.cache_file, "rb") as f:
                data = pickle.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _persist_file_cache(self) -> None:
        """Persist memory cache to file."""
        try:
            with open(self.cache_file, "wb") as f:
                pickle.dump(self._memory_cache, f)
        except Exception:
            pass

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with session_scope() as session:
            repo = EmbeddingCacheRepository(session)
            sqlite_count = repo.count()
        return {
            "model": self.model_name,
            "device": self.device,
            "memory_cache_size": len(self._memory_cache),
            "sqlite_cache_size": sqlite_count,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "hit_rate": self._cache_hits / max(1, self._cache_hits + self._cache_misses),
        }

    def clear_cache(self) -> None:
        """Clear all caches."""
        self._memory_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        with session_scope() as session:
            repo = EmbeddingCacheRepository(session)
            repo.clear()
        if self.cache_file.exists():
            self.cache_file.unlink()

    def __del__(self):
        """Persist cache on destruction."""
        self._persist_file_cache()


# ============================================================
# PROFILE / JOB TEXT BUILDERS (SRP - text preparation)
# ============================================================

def build_profile_text(profile: Any) -> str:
    """
    Build searchable text from profile for embedding.

    Includes: skills, experience roles/companies, education, preferences.
    """
    parts = []

    # Skills (most important for matching)
    if hasattr(profile, "skills") and profile.skills:
        skill_names = [s.name for s in profile.skills if s.name]
        if skill_names:
            parts.append("Skills: " + ", ".join(skill_names))

    # Experience
    if hasattr(profile, "experience") and profile.experience:
        exp_parts = []
        for exp in profile.experience:
            if getattr(exp, "role", None):
                exp_parts.append(exp.role)
            if exp.company:
                exp_parts.append(exp.company)
            if getattr(exp, "description", None):
                exp_parts.append(exp.description[:200])
            if getattr(exp, "technologies", None):
                exp_parts.append(", ".join(exp.technologies[:10]))
        if exp_parts:
            parts.append("Experience: " + " | ".join(exp_parts))

    # Education
    if hasattr(profile, "education") and profile.education:
        edu_parts = []
        for edu in profile.education:
            if getattr(edu, "degree", None):
                edu_parts.append(edu.degree)
            if getattr(edu, "field_of_study", None):
                edu_parts.append(edu.field_of_study)
            if getattr(edu, "institution", None):
                edu_parts.append(edu.institution)
        if edu_parts:
            parts.append("Education: " + " | ".join(edu_parts))

    # Preferences (keywords)
    if hasattr(profile, "preferences") and profile.preferences:
        prefs = profile.preferences
        if getattr(prefs, "keywords_include", None):
            parts.append("Keywords: " + ", ".join(prefs.keywords_include))
        if getattr(prefs, "locations", None):
            parts.append("Locations: " + ", ".join(prefs.locations))
        if getattr(prefs, "job_types", None):
            parts.append("Job types: " + ", ".join([jt.value for jt in prefs.job_types]))
        if getattr(prefs, "work_modes", None):
            parts.append("Work modes: " + ", ".join([wm.value for wm in prefs.work_modes]))

    return "\n\n".join(parts)


def build_job_text(job: Any) -> str:
    """
    Build searchable text from job for embedding.

    Includes: title, company, description, skills/tech mentioned.
    """
    parts = []

    if job.title:
        parts.append(f"Title: {job.title}")
    if job.company:
        parts.append(f"Company: {job.company}")
    if job.location:
        parts.append(f"Location: {job.location}")
    if job.work_mode:
        parts.append(f"Work mode: {job.work_mode}")
    if job.job_type:
        parts.append(f"Job type: {job.job_type}")
    if job.description:
        # Truncate long descriptions
        desc = job.description[:1500]
        parts.append(f"Description: {desc}")

    # Extract tech stack from raw_data if available
    if job.raw_data and isinstance(job.raw_data, dict):
        tech = job.raw_data.get("tech_stack") or job.raw_data.get("skills")
        if tech:
            if isinstance(tech, list):
                parts.append("Tech stack: " + ", ".join(str(t) for t in tech))
            else:
                parts.append(f"Tech stack: {tech}")

    return "\n\n".join(parts)


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def get_embedding_manager(
    model_name: str = DEFAULT_MODEL,
    cache_dir: Optional[Path] = None,
) -> EmbeddingManager:
    """Get or create embedding manager singleton."""
    return EmbeddingManager(model_name=model_name, cache_dir=cache_dir)


def embed_profile(profile: Any, manager: Optional[EmbeddingManager] = None) -> np.ndarray:
    """Embed a profile."""
    manager = manager or get_embedding_manager()
    text = build_profile_text(profile)
    return manager.encode_single(text)


def embed_job(job: Any, manager: Optional[EmbeddingManager] = None) -> np.ndarray:
    """Embed a job."""
    manager = manager or get_embedding_manager()
    text = build_job_text(job)
    return manager.encode_single(text)


def embed_jobs_batch(jobs: List[Any], manager: Optional[EmbeddingManager] = None) -> np.ndarray:
    """Embed multiple jobs efficiently."""
    manager = manager or get_embedding_manager()
    texts = [build_job_text(job) for job in jobs]
    return manager.encode(texts)


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Manager
    "EmbeddingManager",
    "get_embedding_manager",
    # Builders
    "build_profile_text",
    "build_job_text",
    # Convenience
    "embed_profile",
    "embed_job",
    "embed_jobs_batch",
    # Constants
    "DEFAULT_MODEL",
    "EMBEDDING_DIM",
]