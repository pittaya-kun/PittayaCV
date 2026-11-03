# -*- coding: utf-8 -*-
"""
Auto-CV - LLM Reranker Module
Version: 1.0.0
Author: Pittaya
License: MIT
Description: Anthropic SDK-based LLM reranker for job-profile matching.
Uses Claude Code subscription (no extra API costs).
"""

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import anthropic
from anthropic import Anthropic

from auto_cv.config import get_settings
from auto_cv.matching.similarity import MatchResult
from auto_cv.profile.schema import Profile
from auto_cv.storage.models import Job


# ============================================================
# CONSTANTS
# ============================================================

DEFAULT_MODEL = "claude-3-5-haiku-20241022"  # Fast, cheap, good for ranking
MAX_TOKENS = 1024
TEMPERATURE = 0.1  # Low temp for consistent rankings
MAX_JOBS_PER_RERANK = 20  # Context window limit


# ============================================================
# DATA TYPES
# ============================================================

@dataclass
class RerankResult:
    """Result of LLM reranking."""
    job_id: int
    score: float  # 0.0 - 1.0 (LLM-assigned relevance)
    reasoning: str
    rank: int


@dataclass
class RerankSummary:
    """Summary of reranking."""
    original_count: int
    reranked_count: int
    model_used: str
    results: List[RerankResult]


# ============================================================
# ANTHROPIC CLIENT (SRP - only LLM client management)
# ============================================================

class AnthropicClient:
    """Wrapper for Anthropic SDK - supports direct API or FreeClaudeCode proxy."""

    _instance: Optional["AnthropicClient"] = None
    _client: Optional[Anthropic] = None

    def __new__(cls, *args, **kwargs) -> "AnthropicClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        settings=None,
    ):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self.settings = settings or get_settings()

        # Support FreeClaudeCode proxy via base_url
        # Priority: explicit base_url > settings.fcc_base_url > env var > None (direct API)
        self.base_url = base_url or getattr(self.settings, "fcc_base_url", None) or os.environ.get("FCC_BASE_URL")

        # API key: for direct API use real key; for FCC proxy can be dummy
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or self.settings.anthropic_api_key

        if self.base_url:
            # FCC proxy mode - api_key can be dummy
            self._client = Anthropic(
                base_url=self.base_url,
                api_key=self.api_key or "fcc-proxy",
            )
        elif self.api_key:
            # Direct Anthropic API mode
            self._client = Anthropic(api_key=self.api_key)
        else:
            # No client configured
            self._client = None

        self._initialized = True

    @property
    def client(self) -> Anthropic:
        return self._client

    def complete(
        self,
        prompt: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = MAX_TOKENS,
        temperature: float = TEMPERATURE,
        system: Optional[str] = None,
    ) -> str:
        """Send completion request."""
        if not self._client:
            raise RuntimeError("Anthropic client not configured (no API key)")

        try:
            kwargs = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system

            response = self._client.messages.create(**kwargs)
            return response.content[0].text if response.content else ""

        except anthropic.APIError as e:
            raise RuntimeError(f"Anthropic API error: {e}") from e
        except Exception as e:
            raise RuntimeError(f"LLM request failed: {e}") from e

    @property
    def is_available(self) -> bool:
        """Check if LLM client is configured."""
        return self._client is not None


# ============================================================
# PROMPT TEMPLATES (OCP - extensible prompt strategies)
# ============================================================

RERANK_SYSTEM_PROMPT = """You are an expert technical recruiter. Your task is to rank job postings by relevance to a candidate's profile.

Score each job from 0.0 to 1.0 where:
- 1.0 = Perfect match (skills, experience, preferences all align)
- 0.7 = Strong match (core skills match, minor gaps)
- 0.4 = Partial match (some relevant skills, significant gaps)
- 0.1 = Poor match (minimal relevance)
- 0.0 = No match (irrelevant)

Consider: technical skills match, experience level, role type, location preferences, work mode, and career trajectory.

Output ONLY valid JSON array with objects: {"job_index": int, "score": float, "reasoning": "brief explanation"}"""


def build_rerank_prompt(profile: Profile, jobs: List[Job], match_results: List[MatchResult]) -> str:
    """Build reranking prompt for LLM."""
    # Profile summary
    profile_summary = f"""CANDIDATE PROFILE:
Name: {profile.personal_info.full_name if profile.personal_info else "N/A"}
Current Role: {profile.current_role or "N/A"}
Experience: {profile.total_experience_years:.1f} years
Top Skills: {", ".join(profile.top_skills[:10]) if profile.top_skills else "N/A"}
Desired Titles: {", ".join(profile.preferences.desired_titles) if profile.preferences and profile.preferences.desired_titles else "Any"}
Locations: {", ".join(profile.preferences.locations) if profile.preferences and profile.preferences.locations else "Any"}
Work Mode: {profile.preferences.work_mode.value if profile.preferences and profile.preferences.work_mode else "Any"}
Job Type: {profile.preferences.job_type.value if profile.preferences and profile.preferences.job_type else "Any"}
Salary Expectation: {profile.preferences.salary_min or "N/A"} - {profile.preferences.salary_max or "N/A"} {profile.preferences.salary_currency or "BRL"}
"""

    # Jobs to rank
    jobs_text = "JOBS TO RANK:\n"
    for i, (job, match) in enumerate(zip(jobs, match_results)):
        salary_info = ""
        if job.salary_min and job.salary_max:
            salary_info = f" | Salary: {job.salary_min}-{job.salary_max} {job.salary_currency}/{job.salary_period}"

        jobs_text += f"""
[{i}] {job.title} at {job.company}
    Location: {job.location or "N/A"} | Mode: {job.work_mode or "N/A"} | Type: {job.job_type or "N/A"}{salary_info}
    Description: {job.description[:500] if job.description else "N/A"}...
    Initial similarity: {match.score:.3f}
"""

    prompt = f"""{profile_summary}

{jobs_text}

Rank these {len(jobs)} jobs by relevance to the candidate. Return JSON array only."""
    return prompt


# ============================================================
# RERANKER (Main orchestration)
# ============================================================

class LLMReranker:
    """
    LLM-based reranker using Anthropic SDK.

    Takes initial cosine similarity results and reranks using LLM reasoning.
    """

    def __init__(
        self,
        client: Optional[AnthropicClient] = None,
        model: str = DEFAULT_MODEL,
        max_jobs_per_batch: int = MAX_JOBS_PER_RERANK,
        settings=None,
    ):
        self.client = client or AnthropicClient(settings=settings)
        self.model = model
        self.max_jobs_per_batch = max_jobs_per_batch
        self.settings = settings or get_settings()

    @property
    def is_available(self) -> bool:
        """Check if LLM reranking is available."""
        return self.client.is_available

    def rerank(
        self,
        profile: Profile,
        match_results: List[MatchResult],
        top_k: Optional[int] = None,
    ) -> RerankSummary:
        """
        Rerank match results using LLM.

        Args:
            profile: Candidate profile
            match_results: Initial cosine similarity matches
            top_k: Number of top results to return (default: all)

        Returns:
            RerankSummary with LLM-assigned scores
        """
        if not match_results:
            return RerankSummary(
                original_count=0,
                reranked_count=0,
                model_used=self.model,
                results=[],
            )

        if not self.is_available:
            # Fallback: return cosine scores as-is
            return RerankSummary(
                original_count=len(match_results),
                reranked_count=len(match_results),
                model_used="cosine_only",
                results=[
                    RerankResult(
                        job_id=mr.job.id,
                        score=mr.score,
                        reasoning="LLM not available, using cosine similarity score",
                        rank=i + 1,
                    )
                    for i, mr in enumerate(match_results[:top_k] if top_k else match_results)
                ],
            )

        # Limit to max batch size
        jobs_to_rerank = match_results[:self.max_jobs_per_batch]
        jobs = [mr.job for mr in jobs_to_rerank]

        # Build prompt
        prompt = build_rerank_prompt(profile, jobs, jobs_to_rerank)

        # Call LLM
        response = self.client.complete(
            prompt=prompt,
            model=self.model,
            system=RERANK_SYSTEM_PROMPT,
        )

        # Parse response
        rerank_results = self._parse_response(response, jobs_to_rerank)

        # Sort by LLM score
        rerank_results.sort(key=lambda x: x.score, reverse=True)

        # Assign ranks
        for rank, result in enumerate(rerank_results, 1):
            result.rank = rank

        # Apply top_k if specified
        if top_k:
            rerank_results = rerank_results[:top_k]

        return RerankSummary(
            original_count=len(match_results),
            reranked_count=len(rerank_results),
            model_used=self.model,
            results=rerank_results,
        )

    def _parse_response(
        self,
        response: str,
        match_results: List[MatchResult],
    ) -> List[RerankResult]:
        """Parse LLM JSON response."""
        try:
            # Extract JSON from response (may have markdown code fences)
            json_str = response.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]
                json_str = json_str.strip("```").strip()

            data = json.loads(json_str)

            if not isinstance(data, list):
                raise ValueError("Expected JSON array")

            results = []
            for item in data:
                job_idx = item.get("job_index")
                if job_idx is None or job_idx < 0 or job_idx >= len(match_results):
                    continue

                score = float(item.get("score", 0.0))
                score = max(0.0, min(1.0, score))  # Clamp

                results.append(RerankResult(
                    job_id=match_results[job_idx].job.id,
                    score=score,
                    reasoning=item.get("reasoning", ""),
                    rank=0,  # Set after sorting
                ))

            return results

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # Fallback: keep original order with cosine scores
            return [
                RerankResult(
                    job_id=mr.job.id,
                    score=mr.score,
                    reasoning=f"LLM parse failed: {e}. Using cosine score.",
                    rank=i + 1,
                )
                for i, mr in enumerate(match_results)
            ]


# ============================================================
# CONVENIENCE FUNCTIONS
# ============================================================

def get_reranker(
    model: str = DEFAULT_MODEL,
    settings=None,
) -> LLMReranker:
    """Get or create reranker instance."""
    return LLMReranker(model=model, settings=settings)


def rerank_matches(
    profile: Profile,
    match_results: List[MatchResult],
    top_k: Optional[int] = None,
    reranker: Optional[LLMReranker] = None,
) -> RerankSummary:
    """Convenience function to rerank matches."""
    reranker = reranker or get_reranker()
    return reranker.rerank(profile, match_results, top_k)


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    # Types
    "RerankResult",
    "RerankSummary",
    # Client
    "AnthropicClient",
    # Reranker
    "LLMReranker",
    "get_reranker",
    "rerank_matches",
    # Prompt building
    "build_rerank_prompt",
    # Constants
    "DEFAULT_MODEL",
    "MAX_JOBS_PER_RERANK",
]