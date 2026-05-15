#!/usr/bin/env python3
"""
Тесты для LLM пайплайна извлечения знаний.

Проверяет:
- Извлечение сущностей и связей через LLM
- Конвертацию в узлы и связи графа
- Сохранение в репозиторий
"""

import pytest
import asyncio
from app.llm.extraction import (
    LLMService,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    extract_and_store
)
from app.core.repository import GraphRepository
from app.core.models import KnowledgeFragment, NodeType, EdgeType


def _disable_llm_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("LLM_API_BASE", "")
    monkeypatch.setenv("OPENAI_API_BASE", "")


class TestLLMExtraction:
    """Тесты для LLM сервиса извлечения знаний."""

    def test_ollama_provider_uses_local_openai_compatible_client(self, monkeypatch):
        """Ollama works without a third-party API key."""
        monkeypatch.setenv("LLM_API_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "")

        service = LLMService(
            provider="ollama",
            model="llama3.1",
            base_url="http://127.0.0.1:11434",
        )

        assert service.provider == "ollama"
        assert service.api_key == "ollama"
        assert service.model == "llama3.1"
        assert service.base_url == "http://127.0.0.1:11434/v1"
        assert service.client is not None
    
    def test_extraction_without_llm_client_returns_empty_result(self, monkeypatch, capsys):
        """Without a configured LLM client, no algorithmic extraction is used."""
        _disable_llm_env(monkeypatch)
        service = LLMService(api_key=None)

        result = asyncio.run(service.extract_knowledge(
            "Python is a programming language. It supports automation."
        ))

        assert result == ExtractionResult()
        assert "no LLM client configured" in capsys.readouterr().out

    def test_extraction_prompt_requires_russian_human_readable_values(self):
        service = LLMService(api_key=None)

        prompt = service._get_extraction_prompt("Python is a programming language.")

        assert "must be written in Russian" in prompt
        assert "source text language" in prompt
        assert "Write all facts, names, descriptions, comments, and summaries in Russian" in prompt
        assert "idea|fact|quote|question|conclusion" in prompt
        assert "source" not in "idea|fact|quote|question|conclusion"
        assert "used_in|derived_from|contradicts" in prompt
        assert "Never create source entities" in prompt
        assert "related_to" not in prompt
        assert "supports" not in prompt
        assert "similar_to" not in prompt

    def test_extract_knowledge_system_message_requires_russian_output(self):
        class FakeCompletions:
            def __init__(self):
                self.last_messages = None

            async def create(self, **kwargs):
                self.last_messages = kwargs["messages"]

                class Message:
                    content = '{"entities": [], "relations": [], "summary": "Готово."}'

                class Choice:
                    message = Message()

                class Response:
                    choices = [Choice()]

                return Response()

        class FakeChat:
            def __init__(self):
                self.completions = FakeCompletions()

        class FakeClient:
            def __init__(self):
                self.chat = FakeChat()

        service = LLMService(api_key=None)
        service.client = FakeClient()

        result = asyncio.run(service.extract_knowledge("Python is a programming language."))

        system_message = service.client.chat.completions.last_messages[0]["content"]
        assert result.summary == "Готово."
        assert "valid JSON only" in system_message
        assert "must be in Russian" in system_message
        assert "source text language" in system_message
    
    def test_extraction_result_to_graph_elements(self):
        """Тест конвертации результата извлечения в элементы графа."""
        service = LLMService()
        
        # Создаём тестовый результат
        entities = [
            ExtractedEntity(
                name="Искусственный интеллект",
                type="fact",
                description="Область компьютерных наук, изучающая создание интеллектуальных систем"
            ),
            ExtractedEntity(
                name="Машинное обучение",
                type="idea",
                description="Подраздел искусственного интеллекта"
            )
        ]
        
        relations = [
            ExtractedRelation(
                source="Машинное обучение",
                target="Искусственный интеллект",
                type="derived_from",
                description="Мысль о машинном обучении следует из описания ИИ"
            )
        ]
        
        result = ExtractionResult(
            entities=entities,
            relations=relations,
            summary="Текст о взаимосвязи ИИ и машинного обучения"
        )
        
        fragment = KnowledgeFragment(
            content="Тестовый текст",
            source_type="test"
        )
        
        nodes, edges = service.extraction_result_to_graph_elements(result, fragment)
        
        assert len(nodes) == 2
        assert len(edges) == 1
        
        # Проверяем типы узлов
        assert nodes[0].node_type == NodeType.FACT
        assert nodes[1].node_type == NodeType.IDEA
        assert nodes[0].trust_status.value == "suggested"
        assert nodes[0].origin.value == "llm"
        assert nodes[0].review_status.value == "pending"
        
        # Проверяем тип связи
        assert edges[0].edge_type == EdgeType.DERIVED_FROM
        assert edges[0].trust_status.value == "suggested"
        assert edges[0].origin.value == "llm"
        assert edges[0].review_status.value == "pending"
        
        # Проверяем метаданные
        assert 'source' in nodes[0].metadata
        assert nodes[0].metadata['source'] == fragment.id

    def test_extraction_result_skips_automatic_source_nodes(self):
        """LLM/capture extraction cannot put provenance sources into knowledge nodes."""
        service = LLMService(api_key=None)
        fragment = KnowledgeFragment(content="Тестовый текст", source_type="test")
        result = ExtractionResult(
            entities=[
                ExtractedEntity(
                    name="Статья",
                    type="source",
                    description="Описание источника",
                ),
                ExtractedEntity(
                    name="Факт",
                    type="fact",
                    description="Извлечённый факт",
                ),
            ],
            relations=[
                ExtractedRelation(
                    source="Статья",
                    target="Факт",
                    type="used_in",
                )
            ],
        )

        nodes, edges = service.extraction_result_to_graph_elements(result, fragment)

        assert len(nodes) == 1
        assert nodes[0].node_type == NodeType.FACT
        assert edges == []

    def test_coerce_extraction_result_skips_malformed_items(self):
        """Некорректные элементы ответа LLM не ломают весь результат."""
        service = LLMService(api_key=None)

        result = service._coerce_extraction_result({
            "entities": [
                {"": ""},
                {
                    "name": "Python",
                    "type": "fact",
                    "description": "A programming language",
                    "confidence": 0.9,
                },
            ],
            "relations": [
                {"source": "Python"},
                {
                    "source": "Python",
                    "target": "Data analysis",
                    "type": "used_in",
                    "description": "Python is used for data analysis",
                    "confidence": 0.8,
                },
            ],
            "summary": "Python is useful.",
        })

        assert len(result.entities) == 1
        assert result.entities[0].name == "Python"
        assert len(result.relations) == 1
        assert result.summary == "Python is useful."

    def test_parse_json_response_from_code_fence(self):
        """JSON можно извлечь из ответа с обёрткой."""
        service = LLMService(api_key=None)

        result = service._parse_json_response('```json\n{"entities": [], "relations": [], "summary": "ok"}\n```')

        assert result["summary"] == "ok"

    def test_extract_knowledge_returns_empty_when_llm_content_is_none(self, capsys):
        """Empty content from an OpenAI-compatible API should return an empty result."""

        class FakeCompletions:
            async def create(self, **kwargs):
                class Message:
                    content = None

                class Choice:
                    message = Message()
                    finish_reason = "length"

                class Response:
                    choices = [Choice()]

                return Response()

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        service = LLMService(api_key=None)
        service.client = FakeClient()

        result = asyncio.run(service.extract_knowledge("Python is a programming language. It supports automation."))

        assert result == ExtractionResult()
        assert "finish_reason=length" in capsys.readouterr().out
    
    def test_extract_and_store_integration(self, tmp_path):
        """Интеграционный тест полного пайплайна извлечения и сохранения."""
        storage_file = tmp_path / "test_graph"
        repository = GraphRepository(storage_path=str(storage_file))

        class FakeLLMService(LLMService):
            async def extract_knowledge(self, text):
                return ExtractionResult(
                    entities=[
                        ExtractedEntity(
                            name="Python",
                            type="fact",
                            description="Python is a programming language",
                        )
                    ],
                    summary="Python is a programming language.",
                )
        
        text = """
        Python - это язык программирования высокого уровня.
        Он используется для веб-разработки и анализа данных.
        Python имеет динамическую типизацию.
        """
        
        fragment = asyncio.run(extract_and_store(
            text=text,
            repository=repository,
            source_type='test',
            source_url=None,
            llm_service=FakeLLMService(api_key=None),
        ))
        
        assert fragment is not None
        assert fragment.id is not None
        assert len(fragment.extracted_nodes) > 0
        
        # Проверяем, что узлы действительно добавлены в граф
        all_nodes = repository.get_all_nodes()
        assert len(all_nodes) >= len(fragment.extracted_nodes)
        
        # Проверяем статистику
        stats = repository.get_stats()
        assert stats['total_nodes'] > 0
        assert stats['total_fragments'] > 0

    def test_extract_and_store_without_llm_stores_fragment_only(self, monkeypatch, tmp_path):
        """No LLM client means the source fragment is saved without inferred nodes."""
        _disable_llm_env(monkeypatch)
        storage_file = tmp_path / "test_graph"
        repository = GraphRepository(storage_path=str(storage_file))

        fragment = asyncio.run(extract_and_store(
            text="Python is a programming language.",
            repository=repository,
            source_type='test',
            source_url=None,
            llm_service=LLMService(api_key=None),
        ))

        assert fragment.id is not None
        assert fragment.extracted_nodes == []
        assert fragment.llm_status == "skipped"
        assert fragment.warnings
        assert repository.get_all_nodes() == []
        assert repository.get_stats()['total_fragments'] == 1


class TestExtractionEdgeCases:
    """Тесты граничных случаев."""
    
    def test_empty_text(self, monkeypatch):
        """Тест обработки пустого текста."""
        _disable_llm_env(monkeypatch)
        service = LLMService(api_key=None)
        result = asyncio.run(service.extract_knowledge(""))
        
        assert isinstance(result, ExtractionResult)
        # Пустой или минимальный результат допустим
    
    def test_very_short_text(self, monkeypatch):
        """Тест обработки очень короткого текста."""
        _disable_llm_env(monkeypatch)
        service = LLMService(api_key=None)
        result = asyncio.run(service.extract_knowledge("Привет"))
        
        assert isinstance(result, ExtractionResult)
    
    def test_single_sentence(self, monkeypatch):
        """Тест обработки одного предложения."""
        _disable_llm_env(monkeypatch)
        service = LLMService(api_key=None)
        text = "Искусственный интеллект изменяет мир."
        result = asyncio.run(service.extract_knowledge(text))
        
        assert result == ExtractionResult()
    
    def test_long_text_truncation(self, monkeypatch):
        """Тест что длинный текст обрабатывается корректно."""
        _disable_llm_env(monkeypatch)
        service = LLMService(api_key=None)
        
        # Создаём длинный текст (100+ предложений)
        sentences = [f"Предложение номер {i} содержит важную информацию." for i in range(100)]
        text = " ".join(sentences)
        
        result = asyncio.run(service.extract_knowledge(text))
        
        assert result == ExtractionResult()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
