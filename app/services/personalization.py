"""User feedback and lightweight personalization services."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from app.agents.insights import Insight, InsightStore, InsightType
from app.core.models import Edge, EdgeLayer, EdgeType, Node, Origin, ReviewStatus, TrustStatus
from app.core.repository import GraphRepository


def utc_now() -> datetime:
    """Get current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class FeedbackAction(Enum):
    """Supported user reactions to proactive insights."""

    CHOOSE_LEFT = "choose_left"
    CHOOSE_RIGHT = "choose_right"
    RESOLVED = "resolved"
    KEEP_BOTH = "keep_both"
    CONFIRM = "confirm"
    REJECT = "reject"
    REFINE = "refine"
    USEFUL = "useful"
    IGNORE = "ignore"


@dataclass
class InsightFeedback:
    """A single user reaction to an insight."""

    insight_id: str
    insight_type: InsightType
    action: FeedbackAction
    node_ids: list[str] = field(default_factory=list)
    edge_ids: list[str] = field(default_factory=list)
    note: Optional[str] = None
    effects: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if isinstance(self.insight_type, str):
            self.insight_type = InsightType(self.insight_type)
        if isinstance(self.action, str):
            self.action = FeedbackAction(self.action)

    def to_dict(self) -> dict[str, Any]:
        """Serialize feedback to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "insight_id": self.insight_id,
            "insight_type": self.insight_type.value,
            "action": self.action.value,
            "node_ids": self.node_ids,
            "edge_ids": self.edge_ids,
            "note": self.note,
            "effects": self.effects,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InsightFeedback":
        """Deserialize feedback from a dictionary."""
        values = data.copy()
        values["insight_type"] = InsightType(values["insight_type"])
        values["action"] = FeedbackAction(values["action"])
        values["created_at"] = datetime.fromisoformat(values["created_at"])
        return cls(**values)


class FeedbackStore:
    """Persist insight feedback as JSON next to the graph storage."""

    def __init__(self, storage_path: Optional[str | Path]) -> None:
        self.storage_path = Path(storage_path).with_suffix(".feedback.json") if storage_path else None

    def save_feedback(self, feedback: InsightFeedback) -> None:
        """Append feedback to persistent storage."""
        if not self.storage_path:
            return

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        items = self.load_feedback()
        items.append(feedback)
        with open(self.storage_path, "w", encoding="utf-8") as file:
            json.dump([item.to_dict() for item in items], file, ensure_ascii=False, indent=2)

    def load_feedback(self) -> list[InsightFeedback]:
        """Load all saved feedback items."""
        if not self.storage_path or not self.storage_path.exists():
            return []

        with open(self.storage_path, "r", encoding="utf-8") as file:
            data = json.load(file)
        return [InsightFeedback.from_dict(item) for item in data]

    def latest_by_insight(self) -> dict[str, InsightFeedback]:
        """Return the latest feedback for each insight id."""
        latest: dict[str, InsightFeedback] = {}
        for item in self.load_feedback():
            latest[item.insight_id] = item
        return latest


@dataclass
class InboxItem:
    """Insight plus the latest user reaction, if any."""

    insight: Insight
    feedback: Optional[InsightFeedback] = None


class PersonalizationService:
    """Apply user reactions to insights and derive a basic interest model."""

    POSITIVE_ACTIONS = {
        FeedbackAction.CHOOSE_LEFT,
        FeedbackAction.CHOOSE_RIGHT,
        FeedbackAction.RESOLVED,
        FeedbackAction.KEEP_BOTH,
        FeedbackAction.CONFIRM,
        FeedbackAction.REFINE,
        FeedbackAction.USEFUL,
    }
    NEGATIVE_ACTIONS = {FeedbackAction.REJECT, FeedbackAction.IGNORE}

    def __init__(
        self,
        repository: GraphRepository,
        insight_store: Optional[InsightStore] = None,
        feedback_store: Optional[FeedbackStore] = None,
    ) -> None:
        self.repository = repository
        self.insight_store = insight_store or InsightStore(repository.storage_path)
        self.feedback_store = feedback_store or FeedbackStore(repository.storage_path)

    def list_inbox(self, include_reacted: bool = True, limit: int = 50) -> list[InboxItem]:
        """List saved insights with their feedback status."""
        latest_feedback = self.feedback_store.latest_by_insight()
        items = []
        for insight in self._all_insights():
            feedback = latest_feedback.get(insight.id)
            if feedback and not include_reacted:
                continue
            items.append(InboxItem(insight=insight, feedback=feedback))

        items.sort(key=lambda item: item.insight.created_at, reverse=True)
        return items[:limit]

    def react_to_insight(
        self,
        insight_id: str,
        action: str | FeedbackAction,
        note: Optional[str] = None,
        edge_type: Optional[str | EdgeType] = None,
    ) -> InsightFeedback:
        """Record and apply a user reaction to an insight."""
        feedback_action = FeedbackAction(action)
        insight = self.find_insight(insight_id)
        if insight is None:
            raise ValueError(f"Insight not found: {insight_id}")

        self._validate_action(insight.insight_type, feedback_action)
        effects = self._apply_feedback(insight, feedback_action, note=note, edge_type=edge_type)
        feedback = InsightFeedback(
            insight_id=insight.id,
            insight_type=insight.insight_type,
            action=feedback_action,
            node_ids=list(insight.node_ids),
            edge_ids=list(insight.edge_ids),
            note=note,
            effects=effects,
        )
        self.feedback_store.save_feedback(feedback)
        if self.repository.storage_path:
            self.repository.save()
        return feedback

    def find_insight(self, insight_id: str) -> Optional[Insight]:
        """Find an insight across all saved digests."""
        for insight in self._all_insights():
            if insight.id == insight_id:
                return insight
        return None

    def build_interest_profile(self) -> dict[str, Any]:
        """Build a compact personalization profile from saved feedback."""
        feedback_items = self.feedback_store.load_feedback()
        action_counts: dict[str, int] = {}
        topic_counts: dict[str, int] = {}
        node_interactions: dict[str, int] = {}
        positive = 0
        negative = 0

        for item in feedback_items:
            action_counts[item.action.value] = action_counts.get(item.action.value, 0) + 1
            if item.action in self.POSITIVE_ACTIONS:
                positive += 1
            elif item.action in self.NEGATIVE_ACTIONS:
                negative += 1

            weight = -1 if item.action in self.NEGATIVE_ACTIONS else 1
            for node_id in item.node_ids:
                node_interactions[node_id] = node_interactions.get(node_id, 0) + 1
                node = self.repository.get_node(node_id)
                if not node:
                    continue
                for topic in self._node_topics(node):
                    topic_counts[topic] = topic_counts.get(topic, 0) + weight

        sorted_topic_items = sorted(
            ((topic, score) for topic, score in topic_counts.items() if score > 0),
            key=lambda item: item[1],
            reverse=True,
        )
        return {
            "total_feedback": len(feedback_items),
            "positive_feedback": positive,
            "negative_feedback": negative,
            "action_counts": action_counts,
            "top_topics": [
                {"topic": topic, "score": score}
                for topic, score in sorted_topic_items[:10]
            ],
            "node_interactions": node_interactions,
            "message_style": self._message_style(positive, negative),
        }

    def _all_insights(self) -> list[Insight]:
        insights: list[Insight] = []
        for digest in self.insight_store.load_digests():
            insights.extend(digest.insights)
        return insights

    def _validate_action(self, insight_type: InsightType, action: FeedbackAction) -> None:
        allowed = {
            InsightType.CONTRADICTION: {
                FeedbackAction.CHOOSE_LEFT,
                FeedbackAction.CHOOSE_RIGHT,
                FeedbackAction.RESOLVED,
                FeedbackAction.KEEP_BOTH,
            },
            InsightType.HIDDEN_CONNECTION: {
                FeedbackAction.CONFIRM,
                FeedbackAction.REJECT,
                FeedbackAction.REFINE,
            },
            InsightType.REMINDER: {
                FeedbackAction.USEFUL,
                FeedbackAction.IGNORE,
            },
        }[insight_type]
        if action not in allowed:
            allowed_values = ", ".join(sorted(item.value for item in allowed))
            raise ValueError(
                f"Action '{action.value}' is not valid for {insight_type.value}. "
                f"Allowed actions: {allowed_values}"
            )

    def _apply_feedback(
        self,
        insight: Insight,
        action: FeedbackAction,
        note: Optional[str],
        edge_type: Optional[str | EdgeType] = None,
    ) -> list[str]:
        if insight.insight_type == InsightType.CONTRADICTION:
            return self._apply_contradiction_feedback(insight, action, note)
        if insight.insight_type == InsightType.HIDDEN_CONNECTION:
            return self._apply_connection_feedback(insight, action, note, edge_type=edge_type)
        return self._apply_reminder_feedback(insight, action, note)

    def _apply_contradiction_feedback(
        self,
        insight: Insight,
        action: FeedbackAction,
        note: Optional[str],
    ) -> list[str]:
        effects: list[str] = []
        nodes = [self.repository.get_node(node_id) for node_id in insight.node_ids[:2]]
        left, right = (nodes + [None, None])[:2]

        if action in {FeedbackAction.CHOOSE_LEFT, FeedbackAction.CHOOSE_RIGHT}:
            chosen = left if action == FeedbackAction.CHOOSE_LEFT else right
            rejected = right if action == FeedbackAction.CHOOSE_LEFT else left
            if chosen:
                self._mark_node_interaction(chosen, "accepted", note)
                effects.append(f"accepted_node:{chosen.id}")
            if rejected:
                self._mark_node_resolution(rejected, "rejected_after_contradiction", note)
                effects.append(f"marked_node:{rejected.id}")
        elif action in {FeedbackAction.RESOLVED, FeedbackAction.KEEP_BOTH}:
            for node in (left, right):
                if node:
                    self._mark_node_interaction(node, action.value, note)
                    effects.append(f"updated_node:{node.id}")

        if left and right:
            edge = self._ensure_edge(
                left.id,
                right.id,
                EdgeType.CONTRADICTS,
                weight=0.6 if action == FeedbackAction.KEEP_BOTH else 1.0,
                metadata={
                    "source": "user_feedback",
                    "insight_id": insight.id,
                    "resolution": action.value,
                    "note": note,
                },
            )
            effects.append(f"contradiction_edge:{edge.id}")
            effects.extend(self._mark_proposal_review(insight, ReviewStatus.ACCEPTED))
        return effects

    def _apply_connection_feedback(
        self,
        insight: Insight,
        action: FeedbackAction,
        note: Optional[str],
        edge_type: Optional[str | EdgeType] = None,
    ) -> list[str]:
        effects: list[str] = []
        node_ids = insight.node_ids[:2]
        if len(node_ids) < 2:
            return effects

        left = self.repository.get_node(node_ids[0])
        right = self.repository.get_node(node_ids[1])
        if not left or not right:
            return effects

        if action in {FeedbackAction.CONFIRM, FeedbackAction.REFINE}:
            selected_edge_type = self._selected_edge_type(edge_type)
            for node in (left, right):
                self._mark_node_interaction(node, action.value, note)
                effects.append(f"updated_node:{node.id}")
            edge = self._ensure_edge(
                left.id,
                right.id,
                selected_edge_type,
                weight=max(0.1, insight.score),
                metadata={
                    "source": "user_feedback",
                    "insight_id": insight.id,
                    "proposal_id": insight.metadata.get("proposal_id"),
                    "action": action.value,
                    "note": note,
                },
            )
            effects.append(f"manual_edge:{edge.id}")
            effects.extend(self._mark_proposal_review(insight, ReviewStatus.ACCEPTED))
        else:
            for node in (left, right):
                self._mark_node_resolution(node, "connection_rejected", note)
                effects.append(f"marked_node:{node.id}")
            effects.extend(self._mark_proposal_review(insight, ReviewStatus.REJECTED))
        return effects

    def _apply_reminder_feedback(
        self,
        insight: Insight,
        action: FeedbackAction,
        note: Optional[str],
    ) -> list[str]:
        effects = []
        for node_id in insight.node_ids:
            node = self.repository.get_node(node_id)
            if not node:
                continue
            if action == FeedbackAction.USEFUL:
                self._mark_node_interaction(node, "reminder_useful", note)
                effects.append(f"refreshed_node:{node.id}")
            else:
                self._mark_node_resolution(node, "reminder_ignored", note)
                effects.append(f"marked_node:{node.id}")
        return effects

    def _mark_node_interaction(self, node: Node, reason: str, note: Optional[str]) -> None:
        node.interact()
        node.metadata["last_feedback"] = reason
        node.metadata["feedback_count"] = int(node.metadata.get("feedback_count", 0)) + 1
        if note:
            node.metadata["last_feedback_note"] = note
        node.metadata["interest_score"] = float(node.metadata.get("interest_score", 0.0)) + 1.0
        self.repository.update_node(node)

    def _mark_node_resolution(self, node: Node, reason: str, note: Optional[str]) -> None:
        node.metadata["last_feedback"] = reason
        node.metadata["feedback_count"] = int(node.metadata.get("feedback_count", 0)) + 1
        if note:
            node.metadata["last_feedback_note"] = note
        if reason in {"connection_rejected", "reminder_ignored"}:
            node.metadata["interest_score"] = float(node.metadata.get("interest_score", 0.0)) - 0.25
        self.repository.update_node(node)

    def _ensure_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        weight: float,
        metadata: dict[str, Any],
    ) -> Edge:
        existing = (
            self.repository.get_edges_between(source_id, target_id)
            + self.repository.get_edges_between(target_id, source_id)
        )
        for edge in existing:
            if edge.edge_type == edge_type:
                edge.weight = max(edge.weight, weight)
                edge.metadata.update({key: value for key, value in metadata.items() if value is not None})
                self.repository.delete_edge(edge.id)
                self.repository.add_edge(edge)
                return edge

        edge = Edge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            edge_layer=EdgeLayer.MANUAL,
            weight=weight,
            metadata={key: value for key, value in metadata.items() if value is not None},
            trust_status=TrustStatus.CONFIRMED,
            origin=Origin.USER,
            review_status=ReviewStatus.ACCEPTED,
            user_comment=metadata.get("note"),
        )
        self.repository.add_edge(edge)
        return edge

    def _selected_edge_type(self, edge_type: Optional[str | EdgeType]) -> EdgeType:
        if edge_type is None:
            return EdgeType.USED_IN
        if isinstance(edge_type, EdgeType):
            return edge_type
        return EdgeType(edge_type)

    def _mark_proposal_review(self, insight: Insight, status: ReviewStatus) -> list[str]:
        proposal_id = insight.metadata.get("proposal_id")
        if not proposal_id:
            return []
        proposal = self.repository.get_proposal(str(proposal_id))
        if not proposal:
            return []
        proposal.review_status = status
        self.repository.update_proposal(proposal)
        return [f"proposal_{status.value}:{proposal.id}"]

    def _node_topics(self, node: Node) -> list[str]:
        explicit_topic = node.metadata.get("topic")
        if explicit_topic:
            return [term.lower() for term in re.findall(r"\w+", str(explicit_topic)) if len(term) > 2]

        original_name = node.metadata.get("original_name")
        text = str(original_name or node.content)
        terms = [term.lower() for term in re.findall(r"\w+", text, flags=re.UNICODE) if len(term) > 3]
        return terms[:4] or [node.node_type.value]

    def _message_style(self, positive: int, negative: int) -> str:
        if negative > positive:
            return "concise"
        if positive >= 3:
            return "exploratory"
        return "balanced"
