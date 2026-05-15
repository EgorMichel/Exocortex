import asyncio
from datetime import timedelta

from app.agents.insights import Digest, Insight, InsightStore, InsightType
from app.agents.proactive import AgentSettings, ProactiveAgent
from app.core.models import Edge, EdgeType, Node, NodeType, utc_now
from app.core.repository import GraphRepository
from app.services.personalization import (
    FeedbackAction,
    FeedbackStore,
    InsightFeedback,
    PersonalizationService,
)


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
    repo.add_edge(Edge(source_id=first.id, target_id=second.id, edge_type=EdgeType.USED_IN))

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
        node_type=NodeType.FACT,
        metadata={"topic": "coffee sleep"},
    )
    second = Node(
        content="Coffee reduces sleep quality.",
        node_type=NodeType.FACT,
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
    assert insights[0].metadata["statement_a"] == first.content
    assert insights[0].metadata["statement_b"] == second.content


def test_contradiction_detection_batches_openai_compatible_client(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    nodes = [
        Node(content="Coffee improves sleep quality.", node_type=NodeType.FACT, metadata={"topic": "coffee sleep"}),
        Node(content="Coffee reduces sleep quality.", node_type=NodeType.FACT, metadata={"topic": "coffee sleep"}),
        Node(content="Coffee affects sleep quality.", node_type=NodeType.FACT, metadata={"topic": "coffee sleep"}),
    ]
    for node in nodes:
        repo.add_node(node)

    class FakeMessage:
        content = (
            '{"results": ['
            '{"pair_index": 1, "is_contradiction": true, "confidence": 0.9, '
            '"title": "Coffee sleep conflict", "reason": "The statements disagree."},'
            '{"pair_index": 2, "is_contradiction": false, "confidence": 0.2, '
            '"title": "", "reason": ""},'
            '{"pair_index": 3, "is_contradiction": false, "confidence": 0.2, '
            '"title": "", "reason": ""}'
            "]}"
        )

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def __init__(self):
            self.calls = 0
            self.last_messages = None

        async def create(self, **kwargs):
            self.calls += 1
            self.last_messages = kwargs["messages"]
            return FakeResponse()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self):
            self.chat = FakeChat()

    class FakeLLM:
        def __init__(self):
            self.client = FakeClient()
            self.model = "fake-model"

    llm = FakeLLM()
    agent = ProactiveAgent(
        repo,
        llm_service=llm,
        settings=AgentSettings(similarity_threshold=0.1, contradiction_batch_size=10),
    )

    insights = asyncio.run(agent.find_contradictions())

    assert len(insights) == 1
    assert insights[0].insight_type == InsightType.CONTRADICTION
    assert llm.client.chat.completions.calls == 1
    assert "русском языке" in llm.client.chat.completions.last_messages[0]["content"]
    assert "same language" not in llm.client.chat.completions.last_messages[0]["content"]
    assert "на русском языке" in llm.client.chat.completions.last_messages[1]["content"]
    assert "Пара 1" in llm.client.chat.completions.last_messages[1]["content"]
    assert "Пара 3" in llm.client.chat.completions.last_messages[1]["content"]


def test_contradiction_prompt_requires_russian_output(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    agent = ProactiveAgent(repo)

    prompt = agent._contradiction_prompt(
        "Python is a programming language.",
        "Python is a large snake.",
    )
    batch_prompt = agent._contradiction_batch_prompt([
        type(
            "Pair",
            (),
            {
                "left": type("Node", (), {"content": "Coffee improves sleep."})(),
                "right": type("Node", (), {"content": "Coffee reduces sleep."})(),
            },
        )()
    ])

    assert "на русском языке" in prompt
    assert "same language" not in prompt
    assert "на русском языке" in batch_prompt
    assert "same language" not in batch_prompt


def test_analyze_reuses_candidate_pairs_for_hidden_connections_and_contradictions(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    first = Node(
        content="Coffee improves sleep quality.",
        node_type=NodeType.FACT,
        metadata={"topic": "coffee sleep"},
    )
    second = Node(
        content="Coffee reduces sleep quality.",
        node_type=NodeType.FACT,
        metadata={"topic": "coffee sleep"},
    )
    repo.add_node(first)
    repo.add_node(second)

    class FakeLLM:
        async def detect_contradiction(self, left, right):
            return {"is_contradiction": False}

    agent = ProactiveAgent(
        repo,
        llm_service=FakeLLM(),
        settings=AgentSettings(similarity_threshold=0.1, digest_limit=5),
    )
    original_candidate_pairs = agent._candidate_pairs
    calls = 0

    def counted_candidate_pairs(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_candidate_pairs(*args, **kwargs)

    agent._candidate_pairs = counted_candidate_pairs

    asyncio.run(agent.analyze(save=False))

    assert calls == 1


def test_contradictions_skip_candidate_pairs_without_usable_llm(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    repo.add_node(Node(content="Python supports data analysis."))
    repo.add_node(Node(content="Python supports automation."))

    class UnconfiguredLLM:
        client = None

    agent = ProactiveAgent(
        repo,
        llm_service=UnconfiguredLLM(),
        settings=AgentSettings(similarity_threshold=0.1),
    )
    calls = 0

    def counted_candidate_pairs(*args, **kwargs):
        nonlocal calls
        calls += 1
        return []

    agent._candidate_pairs = counted_candidate_pairs

    insights = asyncio.run(agent.find_contradictions())

    assert insights == []
    assert calls == 0


def test_saved_analysis_state_skips_unchanged_node_pairs(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    first = Node(content="Python supports data analysis.", metadata={"topic": "python data"})
    second = Node(content="Python supports automation.", metadata={"topic": "python data"})
    repo.add_node(first)
    repo.add_node(second)

    class FakeLLM:
        def __init__(self):
            self.calls = 0

        async def detect_contradiction(self, left, right):
            self.calls += 1
            return {"is_contradiction": False}

    llm = FakeLLM()
    agent = ProactiveAgent(
        repo,
        llm_service=llm,
        settings=AgentSettings(similarity_threshold=0.1, digest_limit=5),
    )

    first_digest = asyncio.run(agent.analyze(save=True))
    second_digest = asyncio.run(agent.analyze(save=True))

    assert first_digest.insights
    assert second_digest.insights == []
    assert llm.calls == 1
    assert (tmp_path / "graph.analysis_state.json").exists()


def test_agent_persists_hidden_connections_as_proposals(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    first = Node(content="Python supports data analysis.", metadata={"topic": "python data"})
    second = Node(content="Python helps data analysis workflows.", metadata={"topic": "python data"})
    repo.add_node(first)
    repo.add_node(second)

    agent = ProactiveAgent(
        repo,
        settings=AgentSettings(similarity_threshold=0.1, digest_limit=5),
    )

    digest = asyncio.run(agent.analyze(save=True))
    proposals = repo.get_all_proposals()

    assert digest.insights
    assert proposals
    assert proposals[0].proposal_type.value == "proposed_edge"
    assert proposals[0].review_status.value == "pending"
    assert digest.insights[0].metadata["proposal_id"] == proposals[0].id
    assert repo.get_all_edges() == []


def test_analysis_state_rechecks_pairs_when_node_changes(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    first = Node(content="Python supports data analysis.", metadata={"topic": "python data"})
    second = Node(content="Python supports automation.", metadata={"topic": "python data"})
    repo.add_node(first)
    repo.add_node(second)

    class FakeLLM:
        def __init__(self):
            self.calls = 0

        async def detect_contradiction(self, left, right):
            self.calls += 1
            return {"is_contradiction": False}

    llm = FakeLLM()
    agent = ProactiveAgent(
        repo,
        llm_service=llm,
        settings=AgentSettings(similarity_threshold=0.1, digest_limit=5),
    )

    asyncio.run(agent.analyze(save=True))
    changed = repo.get_node(first.id)
    changed.content = "Python supports data analysis and reporting."
    repo.update_node(changed)
    digest = asyncio.run(agent.analyze(save=True))

    assert digest.insights
    assert llm.calls == 2


def test_analysis_state_rechecks_pairs_when_source_text_changes(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    first = Node(
        content="Python supports data analysis.",
        source_text="Python is often used for data workflows.",
        metadata={"topic": "python data"},
    )
    second = Node(content="Python supports automation.", metadata={"topic": "python data"})
    repo.add_node(first)
    repo.add_node(second)

    class FakeLLM:
        def __init__(self):
            self.calls = 0

        async def detect_contradiction(self, left, right):
            self.calls += 1
            return {"is_contradiction": False}

    llm = FakeLLM()
    agent = ProactiveAgent(
        repo,
        llm_service=llm,
        settings=AgentSettings(similarity_threshold=0.1, digest_limit=5),
    )

    asyncio.run(agent.analyze(save=True))
    changed = repo.get_node(first.id)
    changed.source_text = "Python is frequently used for data workflows and automation."
    repo.update_node(changed)
    digest = asyncio.run(agent.analyze(save=True))

    assert digest.insights
    assert llm.calls == 2


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


def test_digest_uses_interest_profile_for_same_priority_insights(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    learning_node = Node(
        content="Spaced repetition supports learning.",
        metadata={"topic": "learning memory", "interest_score": 2.0},
    )
    generic_node = Node(
        content="Generic archived note.",
        metadata={"topic": "archive"},
    )
    repo.add_node(learning_node)
    repo.add_node(generic_node)

    class FakePersonalization:
        def build_interest_profile(self):
            return {
                "total_feedback": 3,
                "action_counts": {"useful": 3},
                "top_topics": [{"topic": "learning", "score": 3}],
                "message_style": "concise",
            }

    agent = ProactiveAgent(
        repo,
        settings=AgentSettings(digest_limit=1),
        personalization_service=FakePersonalization(),
    )
    preferred = Insight(
        insight_type=InsightType.REMINDER,
        title="Learning reminder",
        description="A long learning reminder that should be shortened when concise style is active.",
        node_ids=[learning_node.id],
        score=0.1,
    )
    generic = Insight(
        insight_type=InsightType.REMINDER,
        title="Generic reminder",
        description="Generic reminder",
        node_ids=[generic_node.id],
        score=0.2,
    )

    digest = agent.generate_digest([generic, preferred])

    assert digest.insights == [preferred]
    personalization = preferred.metadata["personalization"]
    assert personalization["matched_topics"] == ["learning"]
    assert personalization["topic_boost"] > 0
    assert personalization["node_boost"] > 0
    assert personalization["message_style"] == "concise"


def test_digest_renders_contradiction_statements():
    digest = Digest(
        insights=[
            Insight(
                insight_type=InsightType.CONTRADICTION,
                title="Потенциальное противоречие",
                description="Одно утверждение говорит об улучшении сна, другое - об ухудшении.",
                score=0.9,
                metadata={
                    "statement_a": "Кофе улучшает качество сна.",
                    "statement_b": "Кофе ухудшает качество сна.",
                },
            )
        ]
    )

    output = digest.format_text()

    assert "Утверждение A: Кофе улучшает качество сна." in output
    assert "Утверждение B: Кофе ухудшает качество сна." in output


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


def test_personalization_confirm_connection_creates_manual_related_edge(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    first = Node(content="Python helps automate data workflows.", metadata={"topic": "python data"})
    second = Node(content="Automation improves data processing.", metadata={"topic": "python data"})
    repo.add_node(first)
    repo.add_node(second)

    insight = Insight(
        insight_type=InsightType.HIDDEN_CONNECTION,
        title="Possible hidden connection",
        description="These nodes look related.",
        node_ids=[first.id, second.id],
        score=0.8,
    )
    insight_store = InsightStore(repo.storage_path)
    insight_store.save_digest(Digest(insights=[insight]))
    service = PersonalizationService(repo, insight_store=insight_store)

    feedback = service.react_to_insight(insight.id, FeedbackAction.CONFIRM)

    edges = repo.get_edges_between(first.id, second.id)
    updated_first = repo.get_node(first.id)
    assert feedback.action == FeedbackAction.CONFIRM
    assert len(edges) == 1
    assert edges[0].edge_type == EdgeType.USED_IN
    assert edges[0].edge_layer.value == "manual"
    assert f"manual_edge:{edges[0].id}" in feedback.effects
    assert updated_first.metadata["last_feedback"] == "confirm"


def test_personalization_reminder_useful_refreshes_node_and_profile(tmp_path):
    repo = GraphRepository(storage_path=str(tmp_path / "graph"))
    node = Node(
        content="Spaced repetition keeps memory fresh.",
        metadata={"topic": "learning memory"},
        decay_rate=0.2,
    )
    node.last_interacted = utc_now() - timedelta(days=30)
    repo.add_node(node)
    before_strength = repo.get_node(node.id).calculate_current_strength()

    insight = Insight(
        insight_type=InsightType.REMINDER,
        title="Refresh fading knowledge",
        description=node.content,
        node_ids=[node.id],
        score=0.7,
    )
    insight_store = InsightStore(repo.storage_path)
    insight_store.save_digest(Digest(insights=[insight]))
    service = PersonalizationService(repo, insight_store=insight_store)

    feedback = service.react_to_insight(insight.id, "useful")
    refreshed = repo.get_node(node.id)
    profile = service.build_interest_profile()

    assert feedback.effects == [f"refreshed_node:{node.id}"]
    assert refreshed.calculate_current_strength() > before_strength
    assert profile["positive_feedback"] == 1
    assert profile["top_topics"][0]["topic"] == "learning"


def test_feedback_store_round_trips_feedback(tmp_path):
    store = FeedbackStore(tmp_path / "graph")
    feedback = InsightFeedback(
        insight_id="insight-1",
        insight_type=InsightType.REMINDER,
        action=FeedbackAction.USEFUL,
        node_ids=["node-1"],
    )

    store.save_feedback(feedback)
    loaded = store.load_feedback()
    latest = store.latest_by_insight()

    assert loaded[0].id == feedback.id
    assert latest["insight-1"].action == FeedbackAction.USEFUL
