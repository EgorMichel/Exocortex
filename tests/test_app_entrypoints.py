import io

from fastapi.testclient import TestClient
from datetime import timedelta

from app import cli
from app.agents.insights import Digest, Insight, InsightStore, InsightType
from app.api import routes
from app.config import load_settings
from app.core.models import AgentProposal, Edge, EdgeLayer, EdgeType, Node, NodeType, ProposalType, utc_now
from app.core.repository import GraphRepository
from app.llm.extraction import SuggestedItem, SuggestionResult


class _InteractiveStdin(io.StringIO):
    def isatty(self):
        return True


def _disable_llm(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LLM_API_BASE", "")
    monkeypatch.setenv("OPENAI_API_BASE", "")
    monkeypatch.setenv("OLLAMA_BASE_URL", "")


def _reset_route_state():
    routes._repository = None
    routes._llm_service = None
    routes._agent = None
    routes._personalization_service = None


def test_load_settings_reads_env(monkeypatch, tmp_path):
    storage_path = tmp_path / "graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_BASE", "https://example.test/v1")
    monkeypatch.setenv("AGENT_CONTRADICTION_BATCH_SIZE", "4")

    settings = load_settings(env_path=tmp_path / "missing.env")

    assert settings.storage_path == str(storage_path)
    assert settings.llm_provider == "openai"
    assert settings.llm_api_key == "test-key"
    assert settings.llm_model == "test-model"
    assert settings.llm_api_base == "https://example.test/v1"
    assert settings.agent_contradiction_batch_size == 4


def test_load_settings_supports_ollama(monkeypatch, tmp_path):
    storage_path = tmp_path / "graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LLM_API_BASE", "")
    monkeypatch.setenv("OPENAI_API_BASE", "")

    settings = load_settings(env_path=tmp_path / "missing.env")

    assert settings.storage_path == str(storage_path)
    assert settings.llm_provider == "ollama"
    assert settings.llm_api_key is None
    assert settings.llm_model == "qwen2.5"
    assert settings.llm_api_base == "http://127.0.0.1:11434"


def test_repository_save_creates_storage_directory(tmp_path):
    storage_path = tmp_path / "nested" / "knowledge_graph"
    repo = GraphRepository(storage_path=str(storage_path))
    repo.add_node(Node(content="Persisted node"))

    repo.save()

    assert storage_path.with_suffix(".graph.json").exists()
    assert storage_path.with_suffix(".gexf").exists()
    assert storage_path.with_suffix(".fragments.json").exists()


def test_web_app_is_served(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "web_graph"))
    routes._repository = None
    routes._llm_service = None
    routes._agent = None
    routes._personalization_service = None

    client = TestClient(routes.app)
    root_response = client.get("/")
    app_response = client.get("/app")

    assert root_response.status_code == 200
    assert root_response.json()["app"] == "/app"
    assert app_response.status_code == 200
    assert "Exocortex Review" in app_response.text
    assert "/api/review" in app_response.text
    assert 'id="themeToggle"' in app_response.text
    assert "exocortex-theme" in app_response.text
    assert ':root[data-theme="dark"]' in app_response.text


def test_reader_app_is_served(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "reader_graph"))
    routes._repository = None
    routes._llm_service = None
    routes._agent = None
    routes._personalization_service = None

    client = TestClient(routes.app)
    root_response = client.get("/")
    reader_response = client.get("/reader")

    assert root_response.status_code == 200
    assert root_response.json()["reader"] == "/reader"
    assert reader_response.status_code == 200
    assert "Exocortex Reader" in reader_response.text
    assert "/api/manual-fragments" in reader_response.text
    assert 'id="themeToggle"' in reader_response.text
    assert 'id="thoughtInput"' in reader_response.text
    assert 'id="sourceInput"' in reader_response.text
    assert 'id="selectionNodeType"' in reader_response.text
    assert 'id="selectionTagsInput"' in reader_response.text
    assert 'id="thoughtNodeType"' in reader_response.text
    assert 'id="thoughtTagsInput"' in reader_response.text
    assert 'id="menuAddSource"' in reader_response.text
    assert "Add as Idea" in reader_response.text
    assert "Add as Source" in reader_response.text
    assert 'id="openGraph"' in reader_response.text
    assert "exocortex-theme" in reader_response.text
    assert ':root[data-theme="dark"]' in reader_response.text


def test_graph_app_is_served(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "graph_app"))
    routes._repository = None
    routes._llm_service = None
    routes._agent = None
    routes._personalization_service = None

    client = TestClient(routes.app)
    root_response = client.get("/")
    graph_response = client.get("/graph")

    assert root_response.status_code == 200
    assert root_response.json()["graph"] == "/graph"
    assert graph_response.status_code == 200
    assert "Exocortex Graph" in graph_response.text
    assert "/api/nodes?limit=500" in graph_response.text
    assert "/api/edges?limit=1000" in graph_response.text
    assert 'id="themeToggle"' in graph_response.text
    assert 'id="graphSvg"' in graph_response.text
    assert 'id="createNodeButton"' in graph_response.text
    assert 'id="saveNodeButton"' in graph_response.text
    assert 'id="createEdgeButton"' in graph_response.text
    assert 'id="selectedTags"' in graph_response.text
    assert 'id="layerFilters"' in graph_response.text
    assert "EDGE_LAYERS" in graph_response.text


def test_api_add_knowledge_uses_configured_storage(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    routes._repository = None
    routes._llm_service = None

    client = TestClient(routes.app)
    response = client.post(
        "/api/knowledge",
        json={"text": "Python is a programming language. It is used for data analysis."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes_created"] == 0
    assert storage_path.with_suffix(".gexf").exists()


def test_api_knowledge_creates_reviewable_suggestions_without_graph_writes(monkeypatch, tmp_path):
    storage_path = tmp_path / "api_knowledge_suggestions_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    _reset_route_state()

    class FakeSuggestionLLM:
        last_status = "skipped"
        last_warnings = []
        last_errors = []

        async def suggest_for_text(self, text, source_type="manual", source_url=None):
            self.last_status = "succeeded"
            return SuggestionResult(
                suggestions=[
                    SuggestedItem(
                        type="node_type",
                        payload={
                            "content": "Python helps automate repeatable work.",
                            "title": "Python automation",
                            "node_type": "fact",
                            "tags": ["python", "automation"],
                            "source_text": text,
                        },
                        score=0.82,
                    )
                ],
                summary="Reviewable candidate node.",
            )

    routes._llm_service = FakeSuggestionLLM()
    client = TestClient(routes.app)
    response = client.post(
        "/api/knowledge",
        json={
            "text": "Python helps automate repeatable work.",
            "source_type": "note",
            "source_url": "local:notes.md",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes_created"] == 0
    assert payload["edges_created"] == 0
    assert payload["suggestions_created"] == 1
    assert payload["llm_status"] == "succeeded"

    repo = GraphRepository(storage_path=str(storage_path))
    assert repo.get_all_nodes() == []
    assert repo.get_all_edges() == []
    assert len(repo.get_all_fragments()) == 1
    suggestions = repo.get_all_proposals()
    assert len(suggestions) == 1
    assert suggestions[0].proposal_type.value == "node_type"
    assert suggestions[0].payload["source_fragment"] == payload["fragment_id"]

    accept_response = client.post(f"/api/suggestions/{suggestions[0].id}/accept", json={})
    assert accept_response.status_code == 200
    assert accept_response.json()["effects"][0].startswith("node_created:")

    repo = GraphRepository(storage_path=str(storage_path))
    nodes = repo.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0].origin.value == "user"
    assert nodes[0].trust_status.value == "confirmed"
    assert nodes[0].metadata["suggested_by"] == "llm"
    assert nodes[0].metadata["source_fragment"] == payload["fragment_id"]


def test_api_agent_analyze_generates_digest(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_agent_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    routes._repository = None
    routes._llm_service = None
    routes._agent = None
    routes._personalization_service = None

    repo = GraphRepository(storage_path=str(storage_path))
    node = Node(content="Old knowledge should be refreshed.", decay_rate=0.2)
    node.last_interacted = utc_now() - timedelta(days=30)
    repo.add_node(node)
    repo.save()

    client = TestClient(routes.app)
    response = client.post("/api/agent/analyze")

    assert response.status_code == 200
    payload = response.json()
    assert payload["insights"][0]["insight_type"] == "reminder"
    assert storage_path.with_suffix(".insights.json").exists()


def test_api_add_source_text(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_source_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    routes._repository = None
    routes._llm_service = None
    routes._agent = None
    routes._personalization_service = None

    client = TestClient(routes.app)
    response = client.post(
        "/api/sources",
        json={"text": "External source content.", "source_type": "note"},
    )

    assert response.status_code == 200
    assert response.json()["nodes_created"] == 0
    repo = GraphRepository(storage_path=str(storage_path))
    assert repo.get_all_fragments()[0].source_type == "note"


def test_api_add_manual_fragment_without_llm(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_manual_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    routes._repository = None
    routes._llm_service = None
    routes._agent = None
    routes._personalization_service = None

    client = TestClient(routes.app)
    response = client.post(
        "/api/manual-fragments",
        json={
            "text": "A manually selected excerpt should be stored verbatim.",
            "source_type": "reader",
            "source_url": "local:notes.md",
            "document_title": "notes.md",
            "metadata": {"offset_start": 10, "offset_end": 58},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes_created"] == 1
    assert payload["edges_created"] == 0
    assert payload["node_type"] == "quote"

    repo = GraphRepository(storage_path=str(storage_path))
    node = repo.get_node(payload["node_id"])
    assert node is not None
    assert node.node_type == NodeType.QUOTE
    assert node.content == "A manually selected excerpt should be stored verbatim."
    assert node.trust_status.value == "confirmed"
    assert node.origin.value == "user"
    assert node.review_status.value == "accepted"
    assert node.metadata["entry_mode"] == "manual_selection"
    assert node.metadata["document_title"] == "notes.md"
    assert node.provenance is not None
    assert node.provenance.source_url == "local:notes.md"
    assert node.provenance.document_title == "notes.md"
    assert node.provenance.offset_start == 10
    assert node.provenance.offset_end == 58
    assert node.provenance.source_text == "A manually selected excerpt should be stored verbatim."
    assert repo.get_all_fragments()[0].extracted_nodes == [node.id]


def test_api_create_and_update_node_provenance(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_provenance_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    _reset_route_state()

    client = TestClient(routes.app)
    create_response = client.post(
        "/api/nodes",
        json={
            "content": "A claim grounded in a source.",
            "node_type": "fact",
            "provenance": {
                "source_url": "https://example.test/article",
                "document_title": "Example Article",
                "author": "Ada",
                "published_at": "2026-05-01",
                "source_type": "url",
                "position": "section 2",
                "offset_start": 15,
                "offset_end": 42,
                "source_text": "The exact quoted source text.",
                "user_comment": "Useful context.",
            },
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["source_id"].startswith("src_")
    assert created["source_url"] == "https://example.test/article"
    assert created["document_title"] == "Example Article"
    assert created["source_text"] == "The exact quoted source text."
    assert created["provenance"]["offset_start"] == 15

    patch_response = client.patch(
        f"/api/nodes/{created['id']}/provenance",
        json={
            "document_title": "Updated Article",
            "position": "section 3",
            "offset_start": 50,
            "offset_end": 90,
            "source_text": "Updated quoted text.",
        },
    )

    assert patch_response.status_code == 200
    updated = patch_response.json()
    assert updated["document_title"] == "Updated Article"
    assert updated["source_url"] == "https://example.test/article"
    assert updated["source_text"] == "Updated quoted text."
    assert updated["provenance"]["position"] == "section 3"
    assert updated["provenance"]["offset_end"] == 90

    repo = GraphRepository(storage_path=str(storage_path))
    node = repo.get_node(created["id"])
    assert node is not None
    assert node.provenance is not None
    assert node.provenance.document_title == "Updated Article"
    assert node.metadata["provenance"]["source_text"] == "Updated quoted text."


def test_reader_provenance_reuses_source_id_and_creates_no_source_nodes_or_edges(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_reader_provenance_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    _reset_route_state()

    client = TestClient(routes.app)
    first_response = client.post(
        "/api/manual-fragments",
        json={
            "text": "First selected passage.",
            "source_type": "reader",
            "source_url": "local:shared.md",
            "document_title": "shared.md",
            "metadata": {"offset_start": 4, "offset_end": 27},
        },
    )
    second_response = client.post(
        "/api/manual-fragments",
        json={
            "text": "Second selected passage.",
            "source_type": "reader",
            "source_url": "local:shared.md",
            "document_title": "shared.md",
            "metadata": {"offset_start": 40, "offset_end": 63},
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    repo = GraphRepository(storage_path=str(storage_path))
    first = repo.get_node(first_response.json()["node_id"])
    second = repo.get_node(second_response.json()["node_id"])
    assert first is not None
    assert second is not None
    assert first.provenance is not None
    assert second.provenance is not None
    assert first.provenance.source_id == second.provenance.source_id
    assert first.provenance.source_url == "local:shared.md"
    assert first.provenance.document_title == "shared.md"
    assert first.provenance.offset_start == 4
    assert first.provenance.offset_end == 27
    assert first.provenance.source_text == "First selected passage."
    assert repo.get_nodes_by_type(NodeType.SOURCE) == []
    assert repo.get_all_edges() == []


def test_reader_capture_rejects_source_node_type(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_reader_no_source_node_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    _reset_route_state()

    client = TestClient(routes.app)
    response = client.post(
        "/api/manual-fragments",
        json={
            "text": "Reader should not create source nodes.",
            "node_type": "source",
            "source_type": "reader",
        },
    )

    assert response.status_code == 400
    repo = GraphRepository(storage_path=str(storage_path))
    assert repo.get_all_nodes() == []


def test_api_add_manual_thought_with_source_text(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_manual_thought_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    routes._repository = None
    routes._llm_service = None
    routes._agent = None
    routes._personalization_service = None

    client = TestClient(routes.app)
    response = client.post(
        "/api/manual-fragments",
        json={
            "text": "Capital accumulation can intensify bargaining asymmetry.",
            "source_text": "A paragraph from the book about capital and labor bargaining.",
            "source_type": "reader",
            "source_url": "local:economics.txt",
            "document_title": "economics.txt",
            "metadata": {"entry_mode": "reader_thought"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["node_type"] == "idea"
    assert payload["summary"] == "Capital accumulation can intensify bargaining asymmetry."

    repo = GraphRepository(storage_path=str(storage_path))
    node = repo.get_node(payload["node_id"])
    assert node is not None
    assert node.node_type == NodeType.IDEA
    assert node.content == "Capital accumulation can intensify bargaining asymmetry."
    assert node.source_text == "A paragraph from the book about capital and labor bargaining."
    assert repo.get_all_fragments()[0].content == node.source_text


def test_api_create_and_update_manual_node(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_manual_node_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    _reset_route_state()

    client = TestClient(routes.app)
    create_response = client.post(
        "/api/nodes",
        json={
            "content": "Manual graph nodes should be first-class.",
            "node_type": "idea",
            "source_text": "Reader context",
            "title": "Manual nodes",
            "tags": ["graph", "manual", "graph"],
            "user_comment": "Created from graph UI.",
            "trust_status": "suggested",
            "origin": "llm",
            "review_status": "pending",
            "metadata": {"entry_mode": "test"},
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["node_type"] == "idea"
    assert created["title"] == "Manual nodes"
    assert created["tags"] == ["graph", "manual"]
    assert created["user_comment"] == "Created from graph UI."
    assert created["trust_status"] == "confirmed"
    assert created["origin"] == "user"
    assert created["review_status"] == "accepted"

    patch_response = client.patch(
        f"/api/nodes/{created['id']}",
        json={
            "content": "Manual graph nodes can be edited.",
            "node_type": "conclusion",
            "title": "Edited node",
            "tags": ["edited"],
            "user_comment": "Updated comment.",
        },
    )

    assert patch_response.status_code == 200
    updated = patch_response.json()
    assert updated["content"] == "Manual graph nodes can be edited."
    assert updated["node_type"] == "conclusion"
    assert updated["title"] == "Edited node"
    assert updated["tags"] == ["edited"]
    assert updated["user_comment"] == "Updated comment."

    repo = GraphRepository(storage_path=str(storage_path))
    node = repo.get_node(created["id"])
    assert node is not None
    assert node.node_type == NodeType.CONCLUSION
    assert node.tags == ["edited"]


def test_api_create_and_update_manual_edge(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_manual_edge_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    _reset_route_state()

    repo = GraphRepository(storage_path=str(storage_path))
    source = Node(content="Source idea", node_type=NodeType.IDEA)
    target = Node(content="Target conclusion", node_type=NodeType.CONCLUSION)
    third = Node(content="Third fact", node_type=NodeType.FACT)
    repo.add_node(source)
    repo.add_node(target)
    repo.add_node(third)
    repo.save()

    client = TestClient(routes.app)
    create_response = client.post(
        "/api/edges",
        json={
            "source_id": source.id,
            "target_id": target.id,
            "edge_type": "derived_from",
            "weight": 0.75,
            "user_comment": "Manual reasoning link.",
            "trust_status": "suggested",
            "origin": "agent",
            "review_status": "pending",
            "metadata": {"entry_mode": "test"},
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["edge_type"] == "derived_from"
    assert created["weight"] == 0.75
    assert created["user_comment"] == "Manual reasoning link."
    assert created["trust_status"] == "confirmed"
    assert created["origin"] == "user"
    assert created["review_status"] == "accepted"

    patch_response = client.patch(
        f"/api/edges/{created['id']}",
        json={
            "target_id": third.id,
            "edge_type": "contradicts",
            "weight": 0.4,
            "user_comment": "Updated edge comment.",
        },
    )

    assert patch_response.status_code == 200
    updated = patch_response.json()
    assert updated["target_id"] == third.id
    assert updated["edge_type"] == "contradicts"
    assert updated["weight"] == 0.4
    assert updated["user_comment"] == "Updated edge comment."

    reloaded = GraphRepository(storage_path=str(storage_path))
    edge = reloaded.get_edge(created["id"])
    assert edge is not None
    assert edge.target_id == third.id
    assert edge.edge_type.value == "contradicts"


def test_api_edges_can_filter_by_layer_and_type(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_edge_layers_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    _reset_route_state()

    repo = GraphRepository(storage_path=str(storage_path))
    first = Node(content="First", node_type=NodeType.IDEA)
    second = Node(content="Second", node_type=NodeType.FACT)
    third = Node(content="Third", node_type=NodeType.CONCLUSION)
    for node in (first, second, third):
        repo.add_node(node)
    manual = Edge(source_id=first.id, target_id=second.id, edge_type=EdgeType.USED_IN)
    service = Edge(
        source_id=first.id,
        target_id=third.id,
        edge_type=EdgeType.USED_IN,
        edge_layer=EdgeLayer.SERVICE,
    )
    suggested = Edge(
        source_id=second.id,
        target_id=third.id,
        edge_type=EdgeType.CONTRADICTS,
        edge_layer=EdgeLayer.SUGGESTED,
    )
    for edge in (manual, service, suggested):
        repo.add_edge(edge)
    repo.save()

    client = TestClient(routes.app)
    service_response = client.get("/api/edges?edge_layer=service")
    suggested_contradictions = client.get("/api/edges?edge_layer=suggested&edge_type=contradicts")
    invalid_response = client.get("/api/edges?edge_layer=automatic")

    assert service_response.status_code == 200
    assert service_response.json()["total"] == 1
    assert service_response.json()["edges"][0]["edge_layer"] == "service"
    assert suggested_contradictions.status_code == 200
    assert suggested_contradictions.json()["total"] == 1
    assert suggested_contradictions.json()["edges"][0]["edge_type"] == "contradicts"
    assert invalid_response.status_code == 400
    assert invalid_response.json()["detail"] == "Invalid edge_layer: automatic"


def test_reader_manual_fragments_keep_defaults_and_tags(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_reader_tags_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    _reset_route_state()

    client = TestClient(routes.app)
    quote_response = client.post(
        "/api/manual-fragments",
        json={
            "text": "Selected quote text.",
            "source_type": "reader",
            "tags": ["quote", "reader", "quote"],
        },
    )
    idea_response = client.post(
        "/api/manual-fragments",
        json={
            "text": "My thought about the quote.",
            "source_text": "Selected quote text.",
            "source_type": "reader",
            "tags": ["idea", "reader"],
        },
    )

    assert quote_response.status_code == 200
    assert idea_response.status_code == 200
    quote_payload = quote_response.json()
    idea_payload = idea_response.json()
    assert quote_payload["node_type"] == "quote"
    assert idea_payload["node_type"] == "idea"

    repo = GraphRepository(storage_path=str(storage_path))
    quote = repo.get_node(quote_payload["node_id"])
    idea = repo.get_node(idea_payload["node_id"])
    assert quote is not None
    assert idea is not None
    assert quote.tags == ["quote", "reader"]
    assert idea.tags == ["idea", "reader"]
    assert quote.metadata["tags"] == ["quote", "reader"]
    assert idea.metadata["tags"] == ["idea", "reader"]


def test_legacy_node_types_are_rejected_and_mvp_edge_type_is_accepted(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_legacy_rejected_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    _reset_route_state()

    repo = GraphRepository(storage_path=str(storage_path))
    source = Node(content="A", node_type=NodeType.IDEA)
    target = Node(content="B", node_type=NodeType.FACT)
    repo.add_node(source)
    repo.add_node(target)
    repo.save()

    client = TestClient(routes.app)
    node_response = client.post(
        "/api/nodes",
        json={"content": "Legacy node", "node_type": "excerpt"},
    )
    manual_response = client.post(
        "/api/manual-fragments",
        json={"text": "Legacy fragment", "node_type": "thesis"},
    )
    edge_response = client.post(
        "/api/edges",
        json={
            "source_id": source.id,
            "target_id": target.id,
            "edge_type": "used_in",
        },
    )

    assert node_response.status_code == 400
    assert manual_response.status_code == 400
    assert edge_response.status_code == 200
    assert edge_response.json()["edge_type"] == "used_in"
    assert edge_response.json()["edge_layer"] == "manual"


def test_api_suggestions_generate_accept_and_reject(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_suggestions_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    _reset_route_state()

    repo = GraphRepository(storage_path=str(storage_path))
    node = Node(content="Python automation scripts improve repeatable workflows.", node_type=NodeType.IDEA)
    repo.add_node(node)
    repo.save()

    client = TestClient(routes.app)
    generate_response = client.post(f"/api/nodes/{node.id}/suggestions")
    assert generate_response.status_code == 200
    generated = generate_response.json()["suggestions"]
    suggestion_types = {item["suggestion_type"] for item in generated}
    assert "node_title" in suggestion_types
    assert "tag" in suggestion_types

    list_response = client.get("/api/suggestions?review_status=pending")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == len(generated)

    title_suggestion = next(item for item in generated if item["suggestion_type"] == "node_title")
    accept_response = client.post(
        f"/api/suggestions/{title_suggestion['id']}/accept",
        json={"payload": {"title": "Automation note"}},
    )
    assert accept_response.status_code == 200
    assert accept_response.json()["review_status"] == "accepted"
    assert accept_response.json()["effects"] == [f"node_title:{node.id}"]

    repo = GraphRepository(storage_path=str(storage_path))
    assert repo.get_node(node.id).title == "Automation note"

    tag_suggestion = next(item for item in generated if item["suggestion_type"] == "tag")
    reject_response = client.post(
        f"/api/suggestions/{tag_suggestion['id']}/reject",
        json={"note": "Not my vocabulary"},
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["review_status"] == "rejected"
    assert reject_response.json()["payload"]["rejection_note"] == "Not my vocabulary"

    repo = GraphRepository(storage_path=str(storage_path))
    updated_node = repo.get_node(node.id)
    assert updated_node.metadata["suggestion_feedback_counts"]["reject:tag"] == 1
    rejected_tag = tag_suggestion["payload"]["tag"]

    regenerate_response = client.post(f"/api/nodes/{node.id}/suggestions")
    assert regenerate_response.status_code == 200
    regenerated_tags = [
        item["payload"]["tag"]
        for item in regenerate_response.json()["suggestions"]
        if item["suggestion_type"] == "tag"
    ]
    assert rejected_tag not in regenerated_tags


def test_api_accept_manual_edge_suggestion_creates_user_edge(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_edge_suggestion_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    _reset_route_state()

    repo = GraphRepository(storage_path=str(storage_path))
    source = Node(content="Python automation scripts improve repeatable data workflows.", node_type=NodeType.IDEA)
    target = Node(content="Python automation scripts improve reporting workflows.", node_type=NodeType.FACT)
    repo.add_node(source)
    repo.add_node(target)
    repo.save()

    client = TestClient(routes.app)
    generate_response = client.post(f"/api/nodes/{source.id}/suggestions")
    assert generate_response.status_code == 200
    manual_edge = next(
        item for item in generate_response.json()["suggestions"]
        if item["suggestion_type"] == "manual_edge"
    )

    accept_response = client.post(f"/api/suggestions/{manual_edge['id']}/accept", json={})
    assert accept_response.status_code == 200
    assert accept_response.json()["review_status"] == "accepted"
    assert accept_response.json()["effects"][0].startswith("manual_edge:")

    repo = GraphRepository(storage_path=str(storage_path))
    edges = repo.get_all_edges()
    assert len(edges) == 1
    assert edges[0].edge_type == EdgeType.USED_IN
    assert edges[0].origin.value == "user"
    assert edges[0].trust_status.value == "confirmed"
    assert edges[0].metadata["suggested_by"] == "llm"


def test_cli_add_stats_search_and_clear(monkeypatch, tmp_path, capsys):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "cli_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))

    assert cli.main(["add", "Python is a programming language. It supports automation."]) == 0
    add_output = capsys.readouterr().out
    assert "Nodes created:" in add_output

    assert cli.main(["stats"]) == 0
    stats_output = capsys.readouterr().out
    assert "Nodes:" in stats_output

    assert cli.main(["search", "Python"]) == 0
    search_output = capsys.readouterr().out
    assert "No nodes found." in search_output

    assert cli.main(["clear"]) == 0
    assert not storage_path.with_suffix(".graph.json").exists()
    assert not storage_path.with_suffix(".gexf").exists()
    assert not storage_path.with_suffix(".fragments.json").exists()


def test_cli_add_manual_stores_quote(monkeypatch, tmp_path, capsys):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "cli_manual_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))

    assert cli.main([
        "add-manual",
        "Manual graph excerpt.",
        "--source-url",
        "local:manual.txt",
        "--document-title",
        "manual.txt",
    ]) == 0
    output = capsys.readouterr().out
    assert "Added manual fragment:" in output
    assert "Node created:" in output

    repo = GraphRepository(storage_path=str(storage_path))
    nodes = repo.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0].node_type == NodeType.QUOTE
    assert nodes[0].content == "Manual graph excerpt."


def test_cli_add_manual_stores_thought_source(monkeypatch, tmp_path, capsys):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "cli_manual_thought_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))

    assert cli.main([
        "add-manual",
        "Manual graph thought.",
        "--source-text",
        "Manual source excerpt.",
    ]) == 0
    capsys.readouterr()

    repo = GraphRepository(storage_path=str(storage_path))
    nodes = repo.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0].node_type == NodeType.IDEA
    assert nodes[0].content == "Manual graph thought."
    assert nodes[0].source_text == "Manual source excerpt."


def test_cli_add_stdin_interactive_finishes_on_enter(monkeypatch, tmp_path, capsys):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "cli_stdin_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    monkeypatch.setattr(cli.sys, "stdin", _InteractiveStdin("Interactive stdin knowledge.\nSecond line.\n"))

    assert cli.main(["add", "--stdin"]) == 0
    output = capsys.readouterr().out
    assert "Added fragment:" in output

    repo = GraphRepository(storage_path=str(storage_path))
    fragments = repo.get_all_fragments()
    assert len(fragments) == 1
    assert fragments[0].content == "Interactive stdin knowledge."


def test_cli_add_stdin_pipe_reads_full_stream(monkeypatch, tmp_path, capsys):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "cli_pipe_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("First line.\nSecond line.\n"))

    assert cli.main(["add", "--stdin"]) == 0
    capsys.readouterr()

    repo = GraphRepository(storage_path=str(storage_path))
    fragments = repo.get_all_fragments()
    assert len(fragments) == 1
    assert fragments[0].content == "First line.\nSecond line."


def test_cli_add_manual_stdin_interactive_finishes_on_enter(monkeypatch, tmp_path, capsys):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "cli_manual_stdin_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    monkeypatch.setattr(cli.sys, "stdin", _InteractiveStdin("Manual stdin excerpt.\nSecond line.\n"))

    assert cli.main(["add-manual", "--stdin"]) == 0
    capsys.readouterr()

    repo = GraphRepository(storage_path=str(storage_path))
    nodes = repo.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0].node_type == NodeType.QUOTE
    assert nodes[0].content == "Manual stdin excerpt."


def test_cli_analyze_and_digest(monkeypatch, tmp_path, capsys):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "cli_agent_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))

    repo = GraphRepository(storage_path=str(storage_path))
    node = Node(content="This old idea should return in a digest.", decay_rate=0.2)
    node.last_interacted = utc_now() - timedelta(days=30)
    repo.add_node(node)
    repo.save()

    assert cli.main(["analyze"]) == 0
    analyze_output = capsys.readouterr().out
    assert "reminder" in analyze_output

    assert cli.main(["digest"]) == 0
    digest_output = capsys.readouterr().out
    assert "Дайджест" in digest_output


def test_cli_add_file(monkeypatch, tmp_path, capsys):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "cli_source_graph"
    source_file = tmp_path / "source.txt"
    source_file.write_text("External file knowledge.", encoding="utf-8")
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))

    assert cli.main(["add", "--file", str(source_file)]) == 0
    output = capsys.readouterr().out
    assert "Added fragment:" in output

    repo = GraphRepository(storage_path=str(storage_path))
    fragments = repo.get_all_fragments()
    assert len(fragments) == 1
    assert fragments[0].source_type == "file"


def test_cli_add_file_allows_source_type_override(monkeypatch, tmp_path, capsys):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "cli_source_override_graph"
    source_file = tmp_path / "source.txt"
    source_file.write_text("External file knowledge.", encoding="utf-8")
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))

    assert cli.main(["add", "--file", str(source_file), "--source-type", "note"]) == 0
    capsys.readouterr()

    repo = GraphRepository(storage_path=str(storage_path))
    fragments = repo.get_all_fragments()
    assert len(fragments) == 1
    assert fragments[0].source_type == "note"


def test_cli_add_multiple_files(monkeypatch, tmp_path, capsys):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "cli_multi_source_graph"
    first_file = tmp_path / "first.txt"
    second_file = tmp_path / "second.txt"
    first_file.write_text("First external file knowledge.", encoding="utf-8")
    second_file.write_text("Second external file knowledge.", encoding="utf-8")
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))

    assert cli.main(["add", "--file", str(first_file), "--file", str(second_file)]) == 0
    output = capsys.readouterr().out
    assert "Added sources: 2" in output

    repo = GraphRepository(storage_path=str(storage_path))
    fragments = repo.get_all_fragments()
    assert len(fragments) == 2
    assert {fragment.source_type for fragment in fragments} == {"file"}


def test_api_inbox_feedback_and_personalization(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_feedback_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    routes._repository = None
    routes._llm_service = None
    routes._agent = None
    routes._personalization_service = None

    repo = GraphRepository(storage_path=str(storage_path))
    node = Node(content="Review old API knowledge.", metadata={"topic": "api knowledge"}, decay_rate=0.2)
    node.last_interacted = utc_now() - timedelta(days=30)
    repo.add_node(node)
    repo.save()
    insight = Insight(
        insight_type=InsightType.REMINDER,
        title="Refresh fading knowledge",
        description=node.content,
        node_ids=[node.id],
        score=0.7,
    )
    InsightStore(storage_path).save_digest(Digest(insights=[insight]))

    client = TestClient(routes.app)
    inbox_response = client.get("/api/inbox")
    assert inbox_response.status_code == 200
    assert inbox_response.json()[0]["insight"]["id"] == insight.id
    assert inbox_response.json()[0]["feedback"] is None

    feedback_response = client.post(
        f"/api/insights/{insight.id}/feedback",
        json={"action": "useful"},
    )
    assert feedback_response.status_code == 200
    assert feedback_response.json()["action"] == "useful"

    profile_response = client.get("/api/personalization")
    assert profile_response.status_code == 200
    assert profile_response.json()["positive_feedback"] == 1


def test_api_review_queue_combines_suggestions_insights_and_defer(monkeypatch, tmp_path):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "api_review_queue_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    routes._repository = None
    routes._llm_service = None
    routes._agent = None
    routes._personalization_service = None

    repo = GraphRepository(storage_path=str(storage_path))
    node = Node(content="Review queue node", node_type=NodeType.IDEA)
    repo.add_node(node)
    suggestion = AgentProposal(
        proposal_type=ProposalType.TAG,
        node_ids=[node.id],
        payload={"tag": "review"},
        score=0.8,
    )
    repo.add_proposal(suggestion)
    repo.save()
    insight = Insight(
        insight_type=InsightType.REMINDER,
        title="Revisit this node",
        description=node.content,
        node_ids=[node.id],
        score=0.6,
    )
    InsightStore(storage_path).save_digest(Digest(insights=[insight]))

    client = TestClient(routes.app)
    review_response = client.get("/api/review")
    assert review_response.status_code == 200
    items = review_response.json()["items"]
    assert {item["item_type"] for item in items} == {"suggestion", "insight"}
    assert all(item["open_graph_url"] == f"/graph?node_id={node.id}" for item in items)

    defer_suggestion = client.post(
        f"/api/review/suggestions/{suggestion.id}/defer",
        json={"note": "Later"},
    )
    defer_insight = client.post(
        f"/api/review/insights/{insight.id}/defer",
        json={"note": "Later"},
    )
    assert defer_suggestion.status_code == 200
    assert defer_suggestion.json()["effects"] == [f"suggestion_deferred:{suggestion.id}"]
    assert defer_insight.status_code == 200
    assert defer_insight.json()["action"] == "defer"

    pending_after_defer = client.get("/api/review")
    assert pending_after_defer.status_code == 200
    assert pending_after_defer.json()["items"] == []

    include_deferred = client.get("/api/review?include_deferred=true&include_reacted=true")
    assert include_deferred.status_code == 200
    statuses = {item["id"]: item["status"] for item in include_deferred.json()["items"]}
    assert statuses[suggestion.id] == "deferred"
    assert statuses[insight.id] == "defer"


def test_cli_inbox_react_and_interests(monkeypatch, tmp_path, capsys):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "cli_feedback_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))

    repo = GraphRepository(storage_path=str(storage_path))
    node = Node(content="CLI feedback should tune personalization.", metadata={"topic": "cli feedback"})
    repo.add_node(node)
    repo.save()
    insight = Insight(
        insight_type=InsightType.REMINDER,
        title="Refresh CLI feedback",
        description=node.content,
        node_ids=[node.id],
        score=0.5,
    )
    InsightStore(storage_path).save_digest(Digest(insights=[insight]))

    assert cli.main(["inbox"]) == 0
    inbox_output = capsys.readouterr().out
    assert insight.id in inbox_output
    assert "status=pending" in inbox_output

    assert cli.main(["react", insight.id, "useful"]) == 0
    react_output = capsys.readouterr().out
    assert "Recorded feedback: useful" in react_output

    assert cli.main(["interests"]) == 0
    interests_output = capsys.readouterr().out
    assert "Positive: 1" in interests_output
