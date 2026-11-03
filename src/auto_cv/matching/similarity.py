# -*- coding: utf-8 -*-
"""
Auto-CV - Similarity Module
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Cosine similarity computation and threshold filtering for job matching.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from auto_cv.storage.models import Job


# ============================================================
# DATA TYPES
# ============================================================

@dataclass
class MatchResult:
    """Result of a single job-profile match."""
    job: Job
    score: float  # 0.0 - 1.0
    rank: int
    match_method: str = "cosine"
    match_details: Optional[dict] = None

    def __lt__(self, other: "MatchResult") -> bool:
        return self.score > other.score  # Higher score = better match


@dataclass
class MatchSummary:
    """Summary of matching results."""
    profile_id: int
    total_jobs_compared: int
    matches_above_threshold: int
    top_score: float
    avg_score: float
    threshold_used: float
    results: List[MatchResult] = field(default_factory=list)


# ============================================================
# SIMILARITY COMPUTATION (SRP - only similarity logic)
# ============================================================

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Compute cosine similarity between two vectors.

    Args:
        a: First vector (1D array)
        b: Second vector (1D array)

    Returns:
        Similarity score in [-1, 1], typically [0, 1] for normalized embeddings
    """
    # Handle edge cases
    if a.size == 0 or b.size == 0:
        return 0.0

    # Ensure 1D
    a = a.flatten()
    b = b.flatten()

    # Cosine similarity = dot(a, b) / (||a|| * ||b||)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(np.dot(a, b) / (norm_a * norm_b))


def cosine_similarity_batch(
    query: np.ndarray,
    candidates: np.ndarray,
) -> np.ndarray:
    """
    Compute cosine similarity between one query and multiple candidates.

    Args:
        query: Query vector (1D, shape: [dim])
        candidates: Candidate matrix (2D, shape: [n_candidates, dim])

    Returns:
        Similarity scores (1D, shape: [n_candidates])
    """
    if candidates.size == 0 or query.size == 0:
        return np.array([], dtype=np.float32)

    query = query.flatten()
    candidates = np.atleast_2d(candidates)

    # Normalize
    query_norm = np.linalg.norm(query)
    cand_norms = np.linalg.norm(candidates, axis=1)

    if query_norm == 0:
        return np.zeros(candidates.shape[0], dtype=np.float32)

    # Avoid division by zero
    cand_norms = np.where(cand_norms == 0, 1.0, cand_norms)

    # Vectorized cosine similarity
    similarities = np.dot(candidates, query) / (cand_norms * query_norm)

    # Clip to [-1, 1] for numerical stability
    return np.clip(similarities, -1.0, 1.0).astype(np.float32)


def filter_by_threshold(
    scores: np.ndarray,
    threshold: float,
    indices: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Filter scores by threshold.

    Args:
        scores: Similarity scores
        threshold: Minimum score to keep
        indices: Optional original indices (if None, uses 0..n)

    Returns:
        (filtered_scores, filtered_indices)
    """
    mask = scores >= threshold
    filtered_scores = scores[mask]
    if indices is not None:
        filtered_indices = indices[mask]
    else:
        filtered_indices = np.where(mask)[0]
    return filtered_scores, filtered_indices


def top_k(
    scores: np.ndarray,
    k: int,
    indices: Optional[np.ndarray] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Get top-k scores and indices.

    Args:
        scores: Similarity scores
        k: Number of top results
        indices: Optional original indices

    Returns:
        (top_scores, top_indices) sorted descending
    """
    if len(scores) == 0:
        return np.array([]), np.array([], dtype=int)

    k = min(k, len(scores))
    # argpartition for O(n) selection, then sort top-k
    top_idx = np.argpartition(scores, -k)[-k:]
    top_idx = top_idx[np.argsort(scores[top_idx])[::-1]]  # Sort descending

    top_scores = scores[top_idx]
    if indices is not None:
        top_indices = indices[top_idx]
    else:
        top_indices = top_idx

    return top_scores, top_indices


# ============================================================
# MATCHING PIPELINE (Orchestration)
# ============================================================

DEFAULT_THRESHOLD = 0.30
DEFAULT_TOP_K = 50


def match_profile_to_jobs(
    profile_embedding: np.ndarray,
    job_embeddings: np.ndarray,
    jobs: List[Job],
    threshold: float = DEFAULT_THRESHOLD,
    max_results: int = DEFAULT_TOP_K,
) -> MatchSummary:
    """
    Match a profile embedding against job embeddings.

    Args:
        profile_embedding: Profile embedding vector
        job_embeddings: Job embeddings matrix [n_jobs, dim]
        jobs: List of Job objects (same order as embeddings)
        threshold: Minimum similarity score
        max_results: Maximum results to return

    Returns:
        MatchSummary with ranked results
    """
    if len(jobs) == 0 or job_embeddings.size == 0:
        return MatchSummary(
            profile_id=0,
            total_jobs_compared=0,
            matches_above_threshold=0,
            top_score=0.0,
            avg_score=0.0,
            threshold_used=threshold,
            results=[],
        )

    # Compute similarities
    scores = cosine_similarity_batch(profile_embedding, job_embeddings)

    # Filter by threshold
    filtered_scores, filtered_indices = filter_by_threshold(scores, threshold)

    # Get top-k
    top_scores, top_indices = top_k(filtered_scores, max_results, filtered_indices)

    # Build results
    results = []
    for rank, (idx, score) in enumerate(zip(top_indices, top_scores), 1):
        job = jobs[idx]
        results.append(MatchResult(
            job=job,
            score=float(score),
            rank=rank,
            match_method="cosine",
            match_details={"similarity": float(score)},
        ))

    return MatchSummary(
        profile_id=0,  # Set by caller if needed
        total_jobs_compared=len(jobs),
        matches_above_threshold=len(filtered_scores),
        top_score=float(top_scores[0]) if len(top_scores) > 0 else 0.0,
        avg_score=float(np.mean(filtered_scores)) if len(filtered_scores) > 0 else 0.0,
        threshold_used=threshold,
        results=results,
    )


def match_jobs_to_profile(
    job_embeddings: np.ndarray,
    jobs: List[Job],
    profile_embedding: np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
    top_k: int = DEFAULT_TOP_K,
) -> MatchSummary:
    """Alias for match_profile_to_jobs (semantic clarity)."""
    return match_profile_to_jobs(profile_embedding, job_embeddings, jobs, threshold, top_k)


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Types
    "MatchResult",
    "MatchSummary",
    # Core functions
    "cosine_similarity",
    "cosine_similarity_batch",
    "filter_by_threshold",
    "top_k",
    # Pipeline
    "match_profile_to_jobs",
    "match_jobs_to_profile",
    # Constants
    "DEFAULT_THRESHOLD",
    "DEFAULT_TOP_K",
]