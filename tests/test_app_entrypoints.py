import io

from fastapi.testclient import TestClient
from datetime import timedelta

from app import cli
from app.agents.insights import Digest, Insight, InsightStore, InsightType
from app.api import routes
from app.config import load_settings
from app.core.models import Node, NodeType, utc_now
from app.core.repository import GraphRepository


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
    assert "Exocortex Inbox" in app_response.text
    assert "/api/inbox" in app_response.text
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
    assert "exocortex-theme" in reader_response.text
    assert ':root[data-theme="dark"]' in reader_response.text


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
    assert payload["node_type"] == "excerpt"

    repo = GraphRepository(storage_path=str(storage_path))
    node = repo.get_node(payload["node_id"])
    assert node is not None
    assert node.node_type == NodeType.EXCERPT
    assert node.content == "A manually selected excerpt should be stored verbatim."
    assert node.metadata["entry_mode"] == "manual_selection"
    assert node.metadata["document_title"] == "notes.md"
    assert repo.get_all_fragments()[0].extracted_nodes == [node.id]


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
    assert not storage_path.with_suffix(".gexf").exists()
    assert not storage_path.with_suffix(".fragments.json").exists()


def test_cli_add_manual_stores_excerpt(monkeypatch, tmp_path, capsys):
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
    assert nodes[0].node_type == NodeType.EXCERPT
    assert nodes[0].content == "Manual graph excerpt."


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
    assert nodes[0].node_type == NodeType.EXCERPT
    assert nodes[0].content == "Manual stdin excerpt."


def test_cli_analyze_and_digest(monkeypatch, tmp_path, capsys):
    _disable_llm(monkeypatch)
    storage_path = tmp_path / "cli_agent_graph"
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))

    repo = GraphRepository(storage_path=str(storage_path))
    node = Node(content="This old concept should return in a digest.", decay_rate=0.2)
    node.last_interacted = utc_now() - timedelta(days=30)
    repo.add_node(node)
    repo.save()

    assert cli.main(["analyze"]) == 0
    analyze_output = capsys.readouterr().out
    assert "reminder" in analyze_output

    assert cli.main(["digest"]) == 0
    digest_output = capsys.readouterr().out
    assert "Digest" in digest_output


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
