# -*- coding: utf-8 -*-
"""
Auto-CV - Matching Pipeline Module
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Orchestrates the full matching flow: embed → similarity → rerank → save.
"""

import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from auto_cv.config import get_settings
from auto_cv.matching.embeddings import (
    EmbeddingManager,
    build_job_text,
    build_profile_text,
    embed_job,
    embed_jobs_batch,
    embed_profile,
    get_embedding_manager,
)
from auto_cv.matching.reranker import (
    LLMReranker,
    RerankResult,
    RerankSummary,
    get_reranker,
    rerank_matches,
)
from auto_cv.matching.similarity import (
    MatchResult,
    MatchSummary,
    match_profile_to_jobs,
)
from auto_cv.profile.schema import Profile
from auto_cv.storage.models import Job
from auto_cv.storage.sqlite import JobRepository, MatchRepository, session_scope


# ============================================================
# DATA TYPES
# ============================================================

@dataclass
class PipelineResult:
    """Complete result of matching pipeline."""
    profile_id: int
    total_jobs: int
    cosine_matches: int
    reranked_matches: int
    final_matches: List[MatchResult]
    rerank_summary: Optional[RerankSummary] = None
    duration_seconds: float = 0.0
    embedding_stats: dict = field(default_factory=dict)


@dataclass
class MatchConfig:
    """Configuration for matching pipeline."""
    similarity_threshold: float = 0.30
    top_k_cosine: int = 50
    top_k_final: int = 20
    use_reranker: bool = True
    rerank_model: str = "claude-3-5-haiku-20241022"
    embedding_model: str = "all-MiniLM-L6-v2"


# ============================================================
# PIPELINE (SRP - orchestration only)
# ============================================================

class MatchingPipeline:
    """
    Full matching pipeline: embed → similarity → rerank → persist.

    Features:
    - Configurable thresholds and limits
    - Optional LLM reranking
    - Database persistence of matches
    - Embedding cache utilization
    - Detailed timing stats
    """

    def __init__(
        self,
        config: Optional[MatchConfig] = None,
        embedding_manager: Optional[EmbeddingManager] = None,
        reranker: Optional[LLMReranker] = None,
        settings=None,
    ):
        self.config = config or MatchConfig()
        self.settings = settings or get_settings()
        self.embedding_manager = embedding_manager or get_embedding_manager(
            model_name=self.config.embedding_model
        )
        self.reranker = reranker
        if self.config.use_reranker and self.reranker is None:
            self.reranker = get_reranker(model=self.config.rerank_model)
            # Disable reranker if not available
            if not self.reranker.is_available:
                self.reranker = None
                self.config.use_reranker = False

    def run(
        self,
        profile: Profile,
        jobs: List[Job],
        profile_id: Optional[int] = None,
        save_to_db: bool = True,
    ) -> PipelineResult:
        """
        Run full matching pipeline.

        Args:
            profile: Candidate profile
            jobs: List of jobs to match against
            profile_id: Profile ID for database (if saving)
            save_to_db: Whether to persist matches

        Returns:
            PipelineResult with final ranked matches
        """
        start_time = time.time()

        if not jobs:
            return PipelineResult(
                profile_id=profile_id or 0,
                total_jobs=0,
                cosine_matches=0,
                reranked_matches=0,
                final_matches=[],
                duration_seconds=time.time() - start_time,
            )

        # Step 1: Embed profile
        profile_embedding = embed_profile(profile, self.embedding_manager)

        # Step 2: Embed jobs (batch)
        job_embeddings = embed_jobs_batch(jobs, self.embedding_manager)

        # Step 3: Cosine similarity
        cosine_summary = match_profile_to_jobs(
            profile_embedding=profile_embedding,
            job_embeddings=job_embeddings,
            jobs=jobs,
            threshold=self.config.similarity_threshold,
            max_results=self.config.top_k_cosine,
        )

        cosine_matches = cosine_summary.results

        # Step 4: LLM Rerank (optional)
        final_matches = cosine_matches
        rerank_summary = None

        if self.config.use_reranker and self.reranker and cosine_matches:
            rerank_summary = self.reranker.rerank(
                profile=profile,
                match_results=cosine_matches,
                top_k=self.config.top_k_final,
            )

            # Convert rerank results to MatchResult format
            final_matches = self._merge_rerank_results(cosine_matches, rerank_summary)

        # Step 5: Save to database
        if save_to_db and final_matches and profile_id:
            self._save_matches(profile_id, final_matches)

        duration = time.time() - start_time

        return PipelineResult(
            profile_id=profile_id or 0,
            total_jobs=len(jobs),
            cosine_matches=len(cosine_matches),
            reranked_matches=len(final_matches),
            final_matches=final_matches,
            rerank_summary=rerank_summary,
            duration_seconds=duration,
            embedding_stats=self.embedding_manager.get_stats(),
        )

    def _merge_rerank_results(
        self,
        cosine_matches: List[MatchResult],
        rerank_summary: RerankSummary,
    ) -> List[MatchResult]:
        """Merge LLM rerank scores with cosine match results."""
        # Create lookup from job_id to cosine match
        cosine_by_job_id = {mr.job.id: mr for mr in cosine_matches}

        merged = []
        for rerank in rerank_summary.results:
            cosine_match = cosine_by_job_id.get(rerank.job_id)
            if cosine_match:
                # Create new MatchResult with LLM score
                merged.append(MatchResult(
                    job=cosine_match.job,
                    score=rerank.score,
                    rank=rerank.rank,
                    match_method="llm_rerank",
                    match_details={
                        "cosine_score": cosine_match.score,
                        "llm_score": rerank.score,
                        "reasoning": rerank.reasoning,
                    },
                ))

        # Add any cosine matches not in rerank (shouldn't happen but safe)
        reranked_job_ids = {r.job_id for r in rerank_summary.results}
        for cm in cosine_matches:
            if cm.job.id not in reranked_job_ids:
                merged.append(MatchResult(
                    job=cm.job,
                    score=cm.score,
                    rank=len(merged) + 1,
                    match_method="cosine",
                    match_details={"cosine_score": cm.score},
                ))

        # Sort by final score
        merged.sort(key=lambda x: x.score, reverse=True)

        # Re-rank
        for i, m in enumerate(merged, 1):
            m.rank = i

        return merged

    def _save_matches(
        self,
        profile_id: int,
        matches: List[MatchResult],
    ) -> int:
        """Save matches to database."""
        saved = 0
        with session_scope() as session:
            repo = MatchRepository(session)
            for match in matches:
                if match.job.id:
                    repo.upsert(
                        profile_id=profile_id,
                        job_id=match.job.id,
                        score=match.score,
                        match_method=match.match_method,
                        match_details=match.match_details,
                    )
                    saved += 1
        return saved


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def run_matching(
    profile: Profile,
    jobs: List[Job],
    profile_id: Optional[int] = None,
    config: Optional[MatchConfig] = None,
    save_to_db: bool = True,
) -> PipelineResult:
    """Convenience function to run matching pipeline."""
    pipeline = MatchingPipeline(config=config)
    return pipeline.run(profile, jobs, profile_id, save_to_db)


def get_pipeline(
    config: Optional[MatchConfig] = None,
    settings=None,
) -> MatchingPipeline:
    """Get configured pipeline instance."""
    return MatchingPipeline(config=config, settings=settings)


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Types
    "PipelineResult",
    "MatchConfig",
    # Pipeline
    "MatchingPipeline",
    "run_matching",
    "get_pipeline",
]