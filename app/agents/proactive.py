"""Proactive graph analysis agent."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
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
    contradiction_batch_size: int = 8


@dataclass(frozen=True)
class NodePair:
    """A candidate pair of semantically related nodes."""

    left: Node
    right: Node
    score: float
    shared_terms: set[str]


@dataclass(frozen=True)
class AnalysisState:
    """Persisted state used to skip unchanged node comparisons."""

    node_fingerprints: dict[str, str]
    settings_fingerprint: str


class AnalysisStateStore:
    """Persist lightweight proactive analysis state next to graph storage."""

    def __init__(self, storage_path: Optional[str | Path]) -> None:
        self.storage_path = Path(storage_path).with_suffix(".analysis_state.json") if storage_path else None

    def load_state(self) -> AnalysisState:
        """Load the previous analysis state, if present."""
        if not self.storage_path or not self.storage_path.exists():
            return AnalysisState(node_fingerprints={}, settings_fingerprint="")

        try:
            with open(self.storage_path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return AnalysisState(node_fingerprints={}, settings_fingerprint="")

        node_fingerprints = data.get("node_fingerprints", {})
        return AnalysisState(
            node_fingerprints=node_fingerprints if isinstance(node_fingerprints, dict) else {},
            settings_fingerprint=str(data.get("settings_fingerprint") or ""),
        )

    def save_state(self, state: AnalysisState) -> None:
        """Save the latest analysis state."""
        if not self.storage_path:
            return

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "node_fingerprints": state.node_fingerprints,
                    "settings_fingerprint": state.settings_fingerprint,
                },
                file,
                ensure_ascii=False,
                indent=2,
            )


class ProactiveAgent:
    """Analyze a knowledge graph and produce proactive insights."""

    def __init__(
        self,
        repository: GraphRepository,
        llm_service: Optional[Any] = None,
        embedding_service: Optional[Any] = None,
        settings: Optional[AgentSettings] = None,
        insight_store: Optional[InsightStore] = None,
        personalization_service: Optional[Any] = None,
        analysis_state_store: Optional[AnalysisStateStore] = None,
    ) -> None:
        self.repository = repository
        self.llm_service = llm_service
        self.embedding_service = embedding_service or LocalTextEmbeddingService()
        self.settings = settings or AgentSettings()
        self.insight_store = insight_store or InsightStore(repository.storage_path)
        self.personalization_service = personalization_service
        self.analysis_state_store = analysis_state_store or AnalysisStateStore(repository.storage_path)

    async def analyze(self, save: bool = True) -> Digest:
        """Run all graph analyzers and return a prioritized digest."""
        logger.info("Starting proactive graph analysis")
        insights: list[Insight] = []
        analysis_state = self.analysis_state_store.load_state() if save else None

        reminder_insights = self.find_forgotten_content()
        candidate_pairs = self._candidate_pairs(analysis_state=analysis_state)
        hidden_connection_insights = self.find_hidden_connections(candidate_pairs)
        contradiction_insights = await self.find_contradictions(candidate_pairs)

        insights.extend(contradiction_insights)
        insights.extend(reminder_insights)
        insights.extend(hidden_connection_insights)

        digest = self.generate_digest(insights)
        if save:
            self.insight_store.save_digest(digest)
            self.analysis_state_store.save_state(self._current_analysis_state())

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

    def find_hidden_connections(
        self,
        candidate_pairs: Optional[list[NodePair]] = None,
    ) -> list[Insight]:
        """Find similar nodes that do not yet have an explicit edge."""
        pairs = candidate_pairs if candidate_pairs is not None else self._candidate_pairs()
        insights = []
        for pair in pairs:
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

    async def find_contradictions(
        self,
        candidate_pairs: Optional[list[NodePair]] = None,
    ) -> list[Insight]:
        """Use the configured LLM service to confirm likely contradictions."""
        if not self._can_detect_contradictions():
            return []

        candidate_pairs_without_existing_edges = []
        pairs = candidate_pairs if candidate_pairs is not None else self._candidate_pairs()
        for pair in pairs:
            if self._has_edge_type(pair.left.id, pair.right.id, EdgeType.CONTRADICTS):
                continue
            candidate_pairs_without_existing_edges.append(pair)

        detections = await self._detect_contradiction_pairs(candidate_pairs_without_existing_edges)
        insights = []
        for pair, detection in zip(candidate_pairs_without_existing_edges, detections):
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
        insights = self._personalize_insights(insights)
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

    def _can_detect_contradictions(self) -> bool:
        """Return whether the configured LLM service can actually check contradictions."""
        if not self.llm_service:
            return False
        if callable(getattr(self.llm_service, "detect_contradiction", None)):
            return True
        return bool(getattr(self.llm_service, "client", None))

    def _personalize_insights(self, insights: list[Insight]) -> list[Insight]:
        """Adjust insight scores and metadata from prior user feedback."""
        profile = self._interest_profile()
        if not profile or not profile.get("total_feedback"):
            return insights

        topic_scores = {
            str(item["topic"]): float(item["score"])
            for item in profile.get("top_topics", [])
        }
        action_counts = profile.get("action_counts", {})
        message_style = str(profile.get("message_style") or "balanced")
        personalized = []
        for insight in insights:
            base_score = insight.score
            insight_topics = self._insight_topics(insight)
            topic_boost = self._topic_boost(insight_topics, topic_scores)
            node_boost = self._node_interest_boost(insight.node_ids)
            type_factor = self._type_interest_factor(insight.insight_type, action_counts)
            insight.score = max(0.0, min(1.5, (base_score * type_factor) + topic_boost + node_boost))
            insight.metadata["personalization"] = {
                "base_score": base_score,
                "topic_boost": topic_boost,
                "node_boost": node_boost,
                "type_factor": type_factor,
                "matched_topics": sorted(insight_topics & set(topic_scores)),
                "message_style": message_style,
            }
            if message_style == "concise":
                insight.description = self._shorten(insight.description, limit=100)
            personalized.append(insight)
        return personalized

    def _interest_profile(self) -> dict[str, Any]:
        """Build the current interest profile, if feedback storage is available."""
        service = self.personalization_service
        if service is None:
            try:
                from app.services.personalization import PersonalizationService
            except ImportError:
                return {}
            service = PersonalizationService(
                repository=self.repository,
                insight_store=self.insight_store,
            )
        profile = service.build_interest_profile()
        return profile if isinstance(profile, dict) else {}

    def _insight_topics(self, insight: Insight) -> set[str]:
        """Extract comparable topics from an insight and its nodes."""
        topics = set(
            term.lower()
            for term in re.findall(
                r"\w+",
                " ".join(
                    str(value)
                    for value in (
                        insight.title,
                        insight.description,
                        " ".join(map(str, insight.metadata.get("shared_terms", []))),
                    )
                ),
                flags=re.UNICODE,
            )
            if len(term) > 2 and term.lower() not in STOPWORDS
        )
        for node_id in insight.node_ids:
            node = self.repository.get_node(node_id)
            if node:
                topics.update(self._terms(node))
        return topics

    def _topic_boost(self, insight_topics: set[str], topic_scores: dict[str, float]) -> float:
        if not insight_topics or not topic_scores:
            return 0.0
        boost = sum(min(0.06, max(0.0, topic_scores[topic]) * 0.03) for topic in insight_topics & set(topic_scores))
        return min(0.18, boost)

    def _node_interest_boost(self, node_ids: list[str]) -> float:
        score = 0.0
        for node_id in node_ids:
            node = self.repository.get_node(node_id)
            if not node:
                continue
            score += float(node.metadata.get("interest_score", 0.0)) * 0.04
        return max(-0.12, min(0.16, score))

    def _type_interest_factor(self, insight_type: InsightType, action_counts: dict[str, int]) -> float:
        positive_by_type = {
            InsightType.CONTRADICTION: (
                action_counts.get("choose_left", 0)
                + action_counts.get("choose_right", 0)
                + action_counts.get("resolved", 0)
                + action_counts.get("keep_both", 0)
            ),
            InsightType.HIDDEN_CONNECTION: (
                action_counts.get("confirm", 0) + action_counts.get("refine", 0)
            ),
            InsightType.REMINDER: action_counts.get("useful", 0),
        }
        negative_by_type = {
            InsightType.CONTRADICTION: 0,
            InsightType.HIDDEN_CONNECTION: action_counts.get("reject", 0),
            InsightType.REMINDER: action_counts.get("ignore", 0),
        }
        net = positive_by_type[insight_type] - negative_by_type[insight_type]
        return max(0.85, min(1.2, 1.0 + (net * 0.04)))

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

    async def _detect_contradiction_pairs(self, pairs: list[NodePair]) -> list[dict[str, Any]]:
        """Detect contradictions for candidate pairs, batching OpenAI-compatible calls."""
        if not pairs:
            return []

        batch_detector = getattr(self.llm_service, "detect_contradictions", None)
        if callable(batch_detector):
            payload = [(pair.left.content, pair.right.content) for pair in pairs]
            result = batch_detector(payload)
            if asyncio.iscoroutine(result):
                result = await result
            return self._normalize_detection_results(result, len(pairs))

        if callable(getattr(self.llm_service, "detect_contradiction", None)):
            detections = []
            for pair in pairs:
                detections.append(await self._detect_contradiction(pair.left, pair.right))
            return detections

        client = getattr(self.llm_service, "client", None)
        if not client:
            return [{} for _ in pairs]

        detections = []
        batch_size = max(1, self.settings.contradiction_batch_size)
        for index in range(0, len(pairs), batch_size):
            batch = pairs[index : index + batch_size]
            detections.extend(await self._detect_contradiction_batch(batch))
        return detections

    async def _detect_contradiction_batch(self, pairs: list[NodePair]) -> list[dict[str, Any]]:
        """Ask an OpenAI-compatible client to check several pairs in one prompt."""
        client = getattr(self.llm_service, "client", None)
        model = getattr(self.llm_service, "model", "gpt-4o-mini")
        if not client:
            return [{} for _ in pairs]

        prompt = self._contradiction_batch_prompt(pairs)
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You detect contradictions. Return JSON only. "
                            "Write titles and reasons in the same language as each pair's statements. "
                            "If a pair uses different languages, use the language of Statement A."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                return [{} for _ in pairs]
            return self._normalize_detection_results(json.loads(content), len(pairs))
        except Exception as exc:
            logger.warning("Batched contradiction detection failed: %s", exc)
            return [{} for _ in pairs]

    def _normalize_detection_results(self, result: Any, expected_count: int) -> list[dict[str, Any]]:
        """Normalize custom or LLM batch results to one detection dict per pair."""
        detections = [{} for _ in range(expected_count)]
        if isinstance(result, dict):
            raw_results = result.get("results", [])
        else:
            raw_results = result
        if not isinstance(raw_results, list):
            return detections

        for fallback_index, item in enumerate(raw_results[:expected_count]):
            if not isinstance(item, dict):
                continue
            pair_index = item.get("pair_index", fallback_index + 1)
            try:
                target_index = int(pair_index) - 1
            except (TypeError, ValueError):
                target_index = fallback_index
            if 0 <= target_index < expected_count:
                detections[target_index] = item
        return detections

    def _candidate_pairs(
        self,
        analysis_state: Optional[AnalysisState] = None,
    ) -> list[NodePair]:
        """Select semantically similar node pairs for deeper analysis."""
        pairs = []
        nodes = self.repository.get_all_nodes()
        changed_node_ids = self._changed_node_ids(nodes, analysis_state)
        terms_cache: dict[str, set[str]] = {}
        embedding_cache: dict[str, Optional[list[float]]] = {}
        for left, right in combinations(nodes, 2):
            if (
                changed_node_ids is not None
                and left.id not in changed_node_ids
                and right.id not in changed_node_ids
            ):
                continue
            score, shared_terms = self._similarity(
                left,
                right,
                terms_cache=terms_cache,
                embedding_cache=embedding_cache,
            )
            if score >= self.settings.similarity_threshold:
                pairs.append(NodePair(left, right, score, shared_terms))

        return sorted(pairs, key=lambda item: item.score, reverse=True)[: self.settings.max_pairs]

    def _changed_node_ids(
        self,
        nodes: list[Node],
        analysis_state: Optional[AnalysisState],
    ) -> Optional[set[str]]:
        """Return changed node ids, or None when a full comparison is required."""
        if not analysis_state:
            return None
        if analysis_state.settings_fingerprint != self._analysis_settings_fingerprint():
            return None
        if not analysis_state.node_fingerprints:
            return None

        current_fingerprints = self._node_fingerprints(nodes)
        return {
            node_id
            for node_id, fingerprint in current_fingerprints.items()
            if analysis_state.node_fingerprints.get(node_id) != fingerprint
        }

    def _current_analysis_state(self) -> AnalysisState:
        nodes = self.repository.get_all_nodes()
        return AnalysisState(
            node_fingerprints=self._node_fingerprints(nodes),
            settings_fingerprint=self._analysis_settings_fingerprint(),
        )

    def _node_fingerprints(self, nodes: list[Node]) -> dict[str, str]:
        return {node.id: self._node_fingerprint(node) for node in nodes}

    def _node_fingerprint(self, node: Node) -> str:
        semantic_metadata = {
            "original_name": node.metadata.get("original_name"),
            "topic": node.metadata.get("topic"),
        }
        payload = {
            "content": node.content,
            "node_type": node.node_type.value,
            "metadata": semantic_metadata,
        }
        return self._stable_hash(payload)

    def _analysis_settings_fingerprint(self) -> str:
        payload = {
            "version": 1,
            "similarity_threshold": self.settings.similarity_threshold,
            "embedding_similarity_threshold": self.settings.embedding_similarity_threshold,
            "max_pairs": self.settings.max_pairs,
            "contradiction_batch_size": self.settings.contradiction_batch_size,
            "embedding_service": self.embedding_service.__class__.__name__ if self.embedding_service else None,
            "embedding_dimensions": getattr(self.embedding_service, "dimensions", None),
            "contradiction_detector": self._contradiction_detector_fingerprint(),
        }
        return self._stable_hash(payload)

    def _contradiction_detector_fingerprint(self) -> str:
        if not self._can_detect_contradictions():
            return "none"

        provider = getattr(self.llm_service, "provider", self.llm_service.__class__.__name__)
        model = getattr(self.llm_service, "model", None)
        base_url = getattr(self.llm_service, "base_url", None)
        custom_detector = callable(getattr(self.llm_service, "detect_contradiction", None))
        return self._stable_hash(
            {
                "provider": provider,
                "model": model,
                "base_url": base_url,
                "custom_detector": custom_detector,
            }
        )

    def _stable_hash(self, payload: Any) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _similarity(
        self,
        left: Node,
        right: Node,
        terms_cache: Optional[dict[str, set[str]]] = None,
        embedding_cache: Optional[dict[str, Optional[list[float]]]] = None,
    ) -> tuple[float, set[str]]:
        left_terms = self._cached_terms(left, terms_cache)
        right_terms = self._cached_terms(right, terms_cache)
        shared = left_terms & right_terms
        union = left_terms | right_terms
        lexical_score = len(shared) / len(union) if union else 0.0
        embedding_score = cosine_similarity(
            self._cached_embedding(left, embedding_cache),
            self._cached_embedding(right, embedding_cache),
        )
        if embedding_score >= self.settings.embedding_similarity_threshold:
            score = max(lexical_score, embedding_score)
        else:
            score = max(lexical_score, embedding_score * 0.35)
        if left.node_type == right.node_type:
            score += 0.05
        return min(score, 1.0), shared

    def _cached_terms(
        self,
        node: Node,
        cache: Optional[dict[str, set[str]]],
    ) -> set[str]:
        if cache is None:
            return self._terms(node)
        if node.id not in cache:
            cache[node.id] = self._terms(node)
        return cache[node.id]

    def _cached_embedding(
        self,
        node: Node,
        cache: Optional[dict[str, Optional[list[float]]]],
    ) -> Optional[list[float]]:
        if cache is None:
            return self._embedding(node)
        if node.id not in cache:
            cache[node.id] = self._embedding(node)
        return cache[node.id]

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

    def _contradiction_batch_prompt(self, pairs: list[NodePair]) -> str:
        pair_blocks = []
        for index, pair in enumerate(pairs, start=1):
            pair_blocks.append(
                f"""
Pair {index}
Statement A:
{pair.left.content}

Statement B:
{pair.right.content}
"""
            )

        return f"""
Compare each pair of knowledge graph statements and decide whether the statements in that pair contradict each other.
Write each title and reason in the same language as that pair's statements. If a pair uses different languages, use the language of Statement A.

Pairs:
{"".join(pair_blocks)}

Return JSON with this exact structure:
{{
  "results": [
    {{
      "pair_index": 1,
      "is_contradiction": true,
      "confidence": 0.0,
      "title": "short title",
      "reason": "short explanation"
    }}
  ]
}}

Include exactly one result for each pair. Use is_contradiction=false when statements are merely different, complementary, or unrelated.
Return JSON only.
"""
