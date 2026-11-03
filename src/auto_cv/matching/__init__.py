# -*- coding: utf-8 -*-
"""
Auto-CV - Matching Package
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Job-profile matching with local embeddings + LLM reranking.
"""

from auto_cv.matching.embeddings import (
    EmbeddingManager,
    build_job_text,
    build_profile_text,
    embed_job,
    embed_jobs_batch,
    embed_profile,
    get_embedding_manager,
    DEFAULT_MODEL,
    EMBEDDING_DIM,
)

from auto_cv.matching.pipeline import (
    MatchingPipeline,
    MatchConfig,
    PipelineResult,
    get_pipeline,
    run_matching,
)

from auto_cv.matching.reranker import (
    AnthropicClient,
    LLMReranker,
    RerankResult,
    RerankSummary,
    build_rerank_prompt,
    get_reranker,
    rerank_matches,
    DEFAULT_MODEL as RERANK_DEFAULT_MODEL,
    MAX_JOBS_PER_RERANK,
)

from auto_cv.matching.similarity import (
    MatchResult,
    MatchSummary,
    cosine_similarity,
    cosine_similarity_batch,
    filter_by_threshold,
    match_jobs_to_profile,
    match_profile_to_jobs,
    top_k,
    DEFAULT_THRESHOLD,
    DEFAULT_TOP_K,
)

__all__ = [
    # Embeddings
    "EmbeddingManager",
    "get_embedding_manager",
    "build_profile_text",
    "build_job_text",
    "embed_profile",
    "embed_job",
    "embed_jobs_batch",
    "DEFAULT_MODEL",
    "EMBEDDING_DIM",
    # Similarity
    "MatchResult",
    "MatchSummary",
    "cosine_similarity",
    "cosine_similarity_batch",
    "filter_by_threshold",
    "top_k",
    "match_profile_to_jobs",
    "match_jobs_to_profile",
    "DEFAULT_THRESHOLD",
    "DEFAULT_TOP_K",
    # Reranker
    "AnthropicClient",
    "LLMReranker",
    "RerankResult",
    "RerankSummary",
    "get_reranker",
    "rerank_matches",
    "build_rerank_prompt",
    "RERANK_DEFAULT_MODEL",
    "MAX_JOBS_PER_RERANK",
    # Pipeline
    "MatchingPipeline",
    "MatchConfig",
    "PipelineResult",
    "get_pipeline",
    "run_matching",
]