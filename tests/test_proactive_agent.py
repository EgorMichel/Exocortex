import asyncio
from datetime import timedelta

from app.agents.insights import Digest, Insight, InsightStore, InsightType
from app.agents.proactive import AgentSettings, ProactiveAgent
from app.core.models import Edge, EdgeType, Node, NodeType, utc_now
from app.core.repository import GraphRepository


def test_forgotten_content_generates_reminder(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    old_node = Node(content="Spaced repetition should refresh old knowledge.", decay_rate=0.2)
    old_node.last_interacted = utc_now() - timedelta(days=30)
    repo.add_node(old_node)

    agent = ProactiveAgent(repo, settings=AgentSettings(forgotten_threshold=0.3))

    insights = agent.find_forgotten_content()

    assert len(insights) == 1
    assert insights[0].insight_type == InsightType.REMINDER
    assert insights[0].node_ids == [old_node.id]


def test_hidden_connections_skip_existing_edges(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    first = Node(content="Python supports data analysis and automation.")
    second = Node(content="Python helps data analysis workflows.")
    third = Node(content="Python supports automation scripts.")
    repo.add_node(first)
    repo.add_node(second)
    repo.add_node(third)
    repo.add_edge(Edge(source_id=first.id, target_id=second.id, edge_type=EdgeType.RELATED_TO))

    agent = ProactiveAgent(
        repo,
        settings=AgentSettings(similarity_threshold=0.1, digest_limit=5),
    )

    insights = agent.find_hidden_connections()

    assert insights
    assert all(set(insight.node_ids) != {first.id, second.id} for insight in insights)
    assert any(set(insight.node_ids) == {first.id, third.id} for insight in insights)


def test_hidden_connections_use_existing_vector_embeddings(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    first = Node(content="Alpha", embeddings=[1.0, 0.0, 0.0])
    second = Node(content="Beta", embeddings=[0.98, 0.2, 0.0])
    third = Node(content="Gamma", embeddings=[0.0, 1.0, 0.0])
    repo.add_node(first)
    repo.add_node(second)
    repo.add_node(third)

    agent = ProactiveAgent(
        repo,
        embedding_service=None,
        settings=AgentSettings(similarity_threshold=0.7),
    )

    insights = agent.find_hidden_connections()

    assert len(insights) == 1
    assert set(insights[0].node_ids) == {first.id, second.id}


def test_contradiction_detection_uses_llm_service(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    first = Node(
        content="Coffee improves sleep quality.",
        node_type=NodeType.THESIS,
        metadata={"topic": "coffee sleep"},
    )
    second = Node(
        content="Coffee reduces sleep quality.",
        node_type=NodeType.THESIS,
        metadata={"topic": "coffee sleep"},
    )
    repo.add_node(first)
    repo.add_node(second)

    class FakeLLM:
        async def detect_contradiction(self, left, right):
            return {
                "is_contradiction": True,
                "confidence": 0.91,
                "reason": "One statement says coffee improves sleep while the other says it reduces it.",
            }

    agent = ProactiveAgent(
        repo,
        llm_service=FakeLLM(),
        settings=AgentSettings(similarity_threshold=0.1),
    )

    insights = asyncio.run(agent.find_contradictions())

    assert len(insights) == 1
    assert insights[0].insight_type == InsightType.CONTRADICTION
    assert insights[0].score == 0.91


def test_digest_prioritizes_contradictions_before_other_insights(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    agent = ProactiveAgent(repo, settings=AgentSettings(digest_limit=2))
    reminder = Insight(
        insight_type=InsightType.REMINDER,
        title="Reminder",
        description="Reminder",
        score=1.0,
    )
    hidden = Insight(
        insight_type=InsightType.HIDDEN_CONNECTION,
        title="Hidden",
        description="Hidden",
        score=1.0,
    )
    contradiction = Insight(
        insight_type=InsightType.CONTRADICTION,
        title="Contradiction",
        description="Contradiction",
        score=0.1,
    )

    digest = agent.generate_digest([hidden, reminder, contradiction])

    assert [item.insight_type for item in digest.insights] == [
        InsightType.CONTRADICTION,
        InsightType.REMINDER,
    ]


def test_insight_store_round_trips_digest(tmp_path):
    store = InsightStore(tmp_path / "graph")
    digest = Digest(
        insights=[
            Insight(
                insight_type=InsightType.HIDDEN_CONNECTION,
                title="Connection",
                description="A possible link",
                node_ids=["a", "b"],
                score=0.5,
            )
        ]
    )

    store.save_digest(digest)
    latest = store.get_latest_digest()

    assert latest is not None
    assert latest.id == digest.id
    assert latest.insights[0].node_ids == ["a", "b"]
