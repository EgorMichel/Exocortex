from fastapi.testclient import TestClient

from app import cli
from app.api import routes
from app.config import load_settings
from app.core.models import Node
from app.core.repository import GraphRepository


def _force_fallback_llm(monkeypatch):
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

    settings = load_settings()

    assert settings.storage_path == str(storage_path)
    assert settings.llm_provider == "openai"
    assert settings.llm_api_key == "test-key"
    assert settings.llm_model == "test-model"
    assert settings.llm_api_base == "https://example.test/v1"


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

    settings = load_settings()

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


def test_api_add_knowledge_uses_configured_storage(monkeypatch, tmp_path):
    _force_fallback_llm(monkeypatch)
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
    assert payload["nodes_created"] > 0
    assert storage_path.with_suffix(".gexf").exists()


def test_cli_add_stats_search_and_clear(monkeypatch, tmp_path, capsys):
    _force_fallback_llm(monkeypatch)
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
    assert "Python" in search_output

    assert cli.main(["clear"]) == 0
    assert not storage_path.with_suffix(".gexf").exists()
    assert not storage_path.with_suffix(".fragments.json").exists()
