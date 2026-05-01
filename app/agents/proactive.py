"""Proactive graph analysis agent."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Optional

from app.agents.embeddings import LocalTextEmbeddingService, cosine_similarity
from app.agents.insights import Digest, Insight, InsightStore, InsightType
from app.core.models import EdgeType, Node
from app.core.repository import GraphRepository


logger = logging.getLogger(__name__)

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "в",
    "во",
    "и",
    "или",
    "к",
    "на",
    "не",
    "но",
    "о",
    "об",
    "от",
    "по",
    "с",
    "у",
    "что",
    "это",
}


@dataclass(frozen=True)
class AgentSettings:
    """Runtime settings for proactive graph analysis."""

    digest_limit: int = 3
    forgotten_threshold: float = 0.3
    similarity_threshold: float = 0.18
    embedding_similarity_threshold: float = 0.72
    max_pairs: int = 25


@dataclass(frozen=True)
class NodePair:
    """A candidate pair of semantically related nodes."""

    left: Node
    right: Node
    score: float
    shared_terms: set[str]


class ProactiveAgent:
    """Analyze a knowledge graph and produce proactive insights."""

    def __init__(
        self,
        repository: GraphRepository,
        llm_service: Optional[Any] = None,
        embedding_service: Optional[Any] = None,
        settings: Optional[AgentSettings] = None,
        insight_store: Optional[InsightStore] = None,
    ) -> None:
        self.repository = repository
        self.llm_service = llm_service
        self.embedding_service = embedding_service or LocalTextEmbeddingService()
        self.settings = settings or AgentSettings()
        self.insight_store = insight_store or InsightStore(repository.storage_path)

    async def analyze(self, save: bool = True) -> Digest:
        """Run all graph analyzers and return a prioritized digest."""
        logger.info("Starting proactive graph analysis")
        insights: list[Insight] = []

        reminder_insights = self.find_forgotten_content()
        hidden_connection_insights = self.find_hidden_connections()
        contradiction_insights = await self.find_contradictions()

        insights.extend(contradiction_insights)
        insights.extend(reminder_insights)
        insights.extend(hidden_connection_insights)

        digest = self.generate_digest(insights)
        if save:
            self.insight_store.save_digest(digest)

        logger.info(
            "Proactive analysis finished: %s insights in digest",
            len(digest.insights),
        )
        return digest

    def analyze_sync(self, save: bool = True) -> Digest:
        """Synchronous wrapper for CLI and scheduled jobs."""
        return asyncio.run(self.analyze(save=save))

    def find_forgotten_content(self) -> list[Insight]:
        """Find nodes whose memory strength has decayed below the threshold."""
        forgotten_nodes = self.repository.get_forgotten_nodes(
            threshold=self.settings.forgotten_threshold
        )
        insights = []
        for node in forgotten_nodes:
            current_strength = node.calculate_current_strength()
            score = max(0.0, self.settings.forgotten_threshold - current_strength)
            insights.append(
                Insight(
                    insight_type=InsightType.REMINDER,
                    title="Refresh fading knowledge",
                    description=self._shorten(node.content),
                    node_ids=[node.id],
                    score=score,
                    metadata={
                        "current_strength": current_strength,
                        "threshold": self.settings.forgotten_threshold,
                    },
                )
            )

        return sorted(insights, key=lambda item: item.score, reverse=True)

    def find_hidden_connections(self) -> list[Insight]:
        """Find similar nodes that do not yet have an explicit edge."""
        insights = []
        for pair in self._candidate_pairs():
            if self._has_direct_edge(pair.left.id, pair.right.id):
                continue
            insights.append(
                Insight(
                    insight_type=InsightType.HIDDEN_CONNECTION,
                    title="Possible hidden connection",
                    description=(
                        f"{self._shorten(pair.left.content)} <-> "
                        f"{self._shorten(pair.right.content)}"
                    ),
                    node_ids=[pair.left.id, pair.right.id],
                    score=pair.score,
                    metadata={"shared_terms": sorted(pair.shared_terms)},
                )
            )

        return sorted(insights, key=lambda item: item.score, reverse=True)

    async def find_contradictions(self) -> list[Insight]:
        """Use the configured LLM service to confirm likely contradictions."""
        if not self.llm_service:
            return []

        insights = []
        for pair in self._candidate_pairs():
            if self._has_edge_type(pair.left.id, pair.right.id, EdgeType.CONTRADICTS):
                continue

            detection = await self._detect_contradiction(pair.left, pair.right)
            if not detection.get("is_contradiction"):
                continue

            confidence = float(detection.get("confidence", pair.score))
            reason = str(detection.get("reason") or "Potential contradiction detected.")
            title = str(
                detection.get("title")
                or self._default_contradiction_title(pair.left.content, pair.right.content)
            )
            insights.append(
                Insight(
                    insight_type=InsightType.CONTRADICTION,
                    title=title,
                    description=reason,
                    node_ids=[pair.left.id, pair.right.id],
                    score=max(confidence, pair.score),
                    metadata={
                        "candidate_score": pair.score,
                        "shared_terms": sorted(pair.shared_terms),
                        "statement_a": pair.left.content,
                        "statement_b": pair.right.content,
                        "statement_a_node_id": pair.left.id,
                        "statement_b_node_id": pair.right.id,
                    },
                )
            )

        return sorted(insights, key=lambda item: item.score, reverse=True)

    def generate_digest(self, insights: list[Insight]) -> Digest:
        """Prioritize and limit insights for a compact digest."""
        priority = {
            InsightType.CONTRADICTION: 3,
            InsightType.REMINDER: 2,
            InsightType.HIDDEN_CONNECTION: 1,
        }
        ranked = sorted(
            insights,
            key=lambda item: (priority[item.insight_type], item.score),
            reverse=True,
        )
        return Digest(insights=ranked[: self.settings.digest_limit])

    def get_latest_digest(self) -> Optional[Digest]:
        """Load the latest persisted digest."""
        return self.insight_store.get_latest_digest()

    async def _detect_contradiction(self, left: Node, right: Node) -> dict[str, Any]:
        """Ask an LLM-like service whether two nodes contradict each other."""
        if hasattr(self.llm_service, "detect_contradiction"):
            result = self.llm_service.detect_contradiction(left.content, right.content)
            if asyncio.iscoroutine(result):
                result = await result
            return result if isinstance(result, dict) else {}

        client = getattr(self.llm_service, "client", None)
        model = getattr(self.llm_service, "model", "gpt-4o-mini")
        if not client:
            return {}

        prompt = self._contradiction_prompt(left.content, right.content)
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You detect contradictions. Return JSON only. "
                            "Write title and reason in the same language as the compared statements. "
                            "If the statements use different languages, use the language of Statement A."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                return {}
            return json.loads(content)
        except Exception as exc:
            logger.warning("Contradiction detection failed: %s", exc)
            return {}

    def _candidate_pairs(self) -> list[NodePair]:
        """Select semantically similar node pairs for deeper analysis."""
        pairs = []
        nodes = self.repository.get_all_nodes()
        for left, right in combinations(nodes, 2):
            score, shared_terms = self._similarity(left, right)
            if score >= self.settings.similarity_threshold:
                pairs.append(NodePair(left, right, score, shared_terms))

        return sorted(pairs, key=lambda item: item.score, reverse=True)[: self.settings.max_pairs]

    def _similarity(self, left: Node, right: Node) -> tuple[float, set[str]]:
        left_terms = self._terms(left)
        right_terms = self._terms(right)
        shared = left_terms & right_terms
        union = left_terms | right_terms
        lexical_score = len(shared) / len(union) if union else 0.0
        embedding_score = cosine_similarity(
            self._embedding(left),
            self._embedding(right),
        )
        if embedding_score >= self.settings.embedding_similarity_threshold:
            score = max(lexical_score, embedding_score)
        else:
            score = max(lexical_score, embedding_score * 0.35)
        if left.node_type == right.node_type:
            score += 0.05
        return min(score, 1.0), shared

    def _embedding(self, node: Node) -> Optional[list[float]]:
        if node.embeddings:
            return node.embeddings
        if not self.embedding_service:
            return None

        embed = getattr(self.embedding_service, "embed", None)
        if not callable(embed):
            return None

        node.embeddings = embed(node.content)
        self.repository.update_node(node)
        return node.embeddings

    def _terms(self, node: Node) -> set[str]:
        text = " ".join(
            str(value)
            for value in (
                node.content,
                node.metadata.get("original_name", ""),
                node.metadata.get("topic", ""),
            )
        )
        return {
            term.lower()
            for term in re.findall(r"\w+", text, flags=re.UNICODE)
            if len(term) > 2 and term.lower() not in STOPWORDS
        }

    def _has_direct_edge(self, left_id: str, right_id: str) -> bool:
        return bool(
            self.repository.get_edges_between(left_id, right_id)
            or self.repository.get_edges_between(right_id, left_id)
        )

    def _has_edge_type(self, left_id: str, right_id: str, edge_type: EdgeType) -> bool:
        edges = (
            self.repository.get_edges_between(left_id, right_id)
            + self.repository.get_edges_between(right_id, left_id)
        )
        return any(edge.edge_type == edge_type for edge in edges)

    def _shorten(self, text: str, limit: int = 160) -> str:
        normalized = " ".join(text.split())
        return normalized if len(normalized) <= limit else f"{normalized[: limit - 3]}..."

    def _default_contradiction_title(self, left: str, right: str) -> str:
        text = f"{left} {right}"
        return "Потенциальное противоречие" if self._looks_cyrillic(text) else "Potential contradiction"

    def _looks_cyrillic(self, text: str) -> bool:
        letters = [char for char in text if char.isalpha()]
        if not letters:
            return False
        cyrillic = sum(1 for char in letters if "\u0400" <= char <= "\u04ff")
        return cyrillic / len(letters) >= 0.3

    def _contradiction_prompt(self, left: str, right: str) -> str:
        return f"""
Compare two knowledge graph statements and decide whether they contradict each other.
Write the title and reason in the same language as the statements. If the statements use different languages, use the language of Statement A.

Statement A:
{left}

Statement B:
{right}

Return JSON with this exact structure:
{{
  "is_contradiction": true,
  "confidence": 0.0,
  "title": "short title",
  "reason": "short explanation"
}}

Use is_contradiction=false when statements are merely different, complementary, or unrelated.
Return JSON only.
"""
