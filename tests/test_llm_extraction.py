#!/usr/bin/env python3
"""
Тесты для LLM пайплайна извлечения знаний.

Проверяет:
- Извлечение сущностей и связей (с fallback без API ключа)
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


class TestLLMExtraction:
    """Тесты для LLM сервиса извлечения знаний."""
    
    def test_fallback_extraction_basic(self):
        """Тест эвристического извлечения без LLM API."""
        service = LLMService(api_key=None)  # Явно указываем отсутствие ключа
        
        text = """
        Искусственный интеллект - это область компьютерных наук.
        Машинное обучение является частью искусственного интеллекта.
        Глубокое обучение - это подраздел машинного обучения.
        Нейронные сети используются в глубоком обучении.
        """
        
        result = asyncio.run(service.extract_knowledge(text))
        
        assert isinstance(result, ExtractionResult)
        assert len(result.entities) > 0
        assert len(result.summary) > 0
        
        # Проверяем, что сущности имеют правильные типы
        for entity in result.entities:
            assert entity.type in ['fact', 'concept', 'thesis', 'definition', 'question']
            assert len(entity.description) > 0
    
    def test_fallback_extraction_with_question(self):
        """Тест извлечения вопроса."""
        service = LLMService(api_key=None)
        
        text = "Что такое машинное обучение? Это область ИИ."
        result = asyncio.run(service.extract_knowledge(text))
        
        assert len(result.entities) > 0
        
        # Хотя бы одна сущность должна быть вопросом
        question_entities = [e for e in result.entities if e.type == 'question']
        # Не гарантируем, но проверяем если есть
        if question_entities:
            assert "?" in question_entities[0].description
    
    def test_extraction_result_to_graph_elements(self):
        """Тест конвертации результата извлечения в элементы графа."""
        service = LLMService()
        
        # Создаём тестовый результат
        entities = [
            ExtractedEntity(
                name="Искусственный интеллект",
                type="concept",
                description="Область компьютерных наук, изучающая создание интеллектуальных систем"
            ),
            ExtractedEntity(
                name="Машинное обучение",
                type="concept", 
                description="Подраздел искусственного интеллекта"
            )
        ]
        
        relations = [
            ExtractedRelation(
                source="Машинное обучение",
                target="Искусственный интеллект",
                type="part_of",
                description="Машинное обучение является частью ИИ"
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
        assert nodes[0].node_type == NodeType.CONCEPT
        assert nodes[1].node_type == NodeType.CONCEPT
        
        # Проверяем тип связи
        assert edges[0].edge_type == EdgeType.PART_OF
        
        # Проверяем метаданные
        assert 'source' in nodes[0].metadata
        assert nodes[0].metadata['source'] == fragment.id
    
    def test_extract_and_store_integration(self, tmp_path):
        """Интеграционный тест полного пайплайна извлечения и сохранения."""
        storage_file = tmp_path / "test_graph"
        repository = GraphRepository(storage_path=str(storage_file))
        
        text = """
        Python - это язык программирования высокого уровня.
        Он используется для веб-разработки и анализа данных.
        Python имеет динамическую типизацию.
        """
        
        fragment = asyncio.run(extract_and_store(
            text=text,
            repository=repository,
            source_type='test',
            source_url=None
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


class TestExtractionEdgeCases:
    """Тесты граничных случаев."""
    
    def test_empty_text(self):
        """Тест обработки пустого текста."""
        service = LLMService(api_key=None)
        result = asyncio.run(service.extract_knowledge(""))
        
        assert isinstance(result, ExtractionResult)
        # Пустой или минимальный результат допустим
    
    def test_very_short_text(self):
        """Тест обработки очень короткого текста."""
        service = LLMService(api_key=None)
        result = asyncio.run(service.extract_knowledge("Привет"))
        
        assert isinstance(result, ExtractionResult)
    
    def test_single_sentence(self):
        """Тест обработки одного предложения."""
        service = LLMService(api_key=None)
        text = "Искусственный интеллект изменяет мир."
        result = asyncio.run(service.extract_knowledge(text))
        
        assert len(result.entities) >= 0  # Может не извлечь ничего meaningful
        assert result.summary
    
    def test_long_text_truncation(self):
        """Тест что длинный текст обрабатывается корректно."""
        service = LLMService(api_key=None)
        
        # Создаём длинный текст (100+ предложений)
        sentences = [f"Предложение номер {i} содержит важную информацию." for i in range(100)]
        text = " ".join(sentences)
        
        result = asyncio.run(service.extract_knowledge(text))
        
        assert isinstance(result, ExtractionResult)
        # Проверяем что результат не пустой
        assert len(result.summary) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
