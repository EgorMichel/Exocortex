"""
LLM-сервис для извлечения знаний из текста.

Использует LLM для:
- Извлечения сущностей (узлов графа)
- Извлечения связей между сущностями
- Определения типов узлов и связей
"""

import json
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field, ValidationError
import os

from app.core.models import Node, Edge, NodeType, EdgeType, KnowledgeFragment


class ExtractedEntity(BaseModel):
    """Сущность, извлечённая из текста."""
    name: str = Field(description="Название сущности")
    type: str = Field(description="Тип сущности: fact, concept, thesis, definition, question")
    description: str = Field(description="Описание или содержание сущности")
    confidence: float = Field(default=1.0, description="Уверенность в извлечении (0-1)")


class ExtractedRelation(BaseModel):
    """Связь между сущностями."""
    source: str = Field(description="Название исходной сущности")
    target: str = Field(description="Название целевой сущности")
    type: str = Field(description="Тип связи: related_to, contradicts, supports, example_of, part_of, derived_from, similar_to")
    description: str = Field(default="", description="Описание связи")
    confidence: float = Field(default=1.0, description="Уверенность в связи (0-1)")


class ExtractionResult(BaseModel):
    """Результат извлечения знаний из текста."""
    entities: List[ExtractedEntity] = Field(default_factory=list)
    relations: List[ExtractedRelation] = Field(default_factory=list)
    summary: str = Field(default="", description="Краткое содержание текста")


class LLMService:
    """
    Сервис для работы с LLM.
    
    Поддерживает:
    - OpenAI API
    - Локальные модели через Ollama (опционально)
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        """
        Инициализация LLM сервиса.
        
        Args:
            api_key: API ключ. Если None, берётся из LLM_API_KEY или OPENAI_API_KEY env.
            model: Название модели для использования
            base_url: OpenAI-compatible API base URL
        """
        self.provider = (provider or os.getenv("LLM_PROVIDER", "openai")).strip().lower()
        if self.provider == "local":
            self.provider = "ollama"

        if self.provider == "ollama":
            self.api_key = api_key or os.getenv("LLM_API_KEY") or "ollama"
            self.model = model or os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or "llama3.1"
            self.base_url = self._normalize_ollama_base_url(
                base_url
                or os.getenv("LLM_API_BASE")
                or os.getenv("OLLAMA_BASE_URL")
                or "http://localhost:11434"
            )
        else:
            self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
            self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
            self.base_url = base_url or os.getenv("LLM_API_BASE") or os.getenv("OPENAI_API_BASE")
        self.client = None
        
        if self.api_key:
            try:
                from openai import AsyncOpenAI

                client_kwargs = {"api_key": self.api_key}
                if self.base_url:
                    client_kwargs["base_url"] = self.base_url
                self.client = AsyncOpenAI(**client_kwargs)
            except ImportError:
                print("Warning: openai package not installed. LLM features will be limited.")

    def _normalize_ollama_base_url(self, base_url: str) -> str:
        """Return Ollama's OpenAI-compatible API base URL."""
        normalized = base_url.rstrip("/")
        if normalized.endswith("/v1"):
            return normalized
        return f"{normalized}/v1"
    
    def _get_extraction_prompt(self, text: str) -> str:
        """Создать промпт для извлечения сущностей и связей."""
        return f"""
You are a knowledge extraction assistant. Analyze the following text and extract:
1. Key entities (facts, concepts, theses, definitions, questions)
2. Relationships between these entities

Text to analyze:
{text}

Extract entities and relationships in JSON format with this exact structure:
{{
    "entities": [
        {{
            "name": "entity name",
            "type": "fact|concept|thesis|definition|question",
            "description": "detailed description of the entity",
            "confidence": 0.95
        }}
    ],
    "relations": [
        {{
            "source": "source entity name",
            "target": "target entity name",
            "type": "related_to|contradicts|supports|example_of|part_of|derived_from|similar_to",
            "description": "description of the relationship",
            "confidence": 0.9
        }}
    ],
    "summary": "brief summary of the text in 1-2 sentences"
}}

Rules:
- Extract only meaningful, standalone entities
- Use precise types for entities and relationships
- Don't create duplicate entities
- Only create relationships that are explicitly stated or strongly implied
- Set confidence based on how clear/certain the information is
- Return ONLY valid JSON, no additional text

Respond in JSON format only.
"""

    async def extract_knowledge(self, text: str) -> ExtractionResult:
        """
        Извлечь знания из текста с помощью LLM.
        
        Args:
            text: Текст для анализа
            
        Returns:
            ExtractionResult с извлечёнными сущностями и связями
        """
        if not self.client:
            # Fallback: простой эвристический парсинг без LLM
            return self._extract_knowledge_fallback(text)
        
        try:
            prompt = self._get_extraction_prompt(text)
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a knowledge extraction assistant. Always respond with valid JSON only. Respond in the language in which you received the information."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=8000,
                response_format={"type": "json_object"}
            )
            
            choice = response.choices[0]
            result_text = choice.message.content
            if not isinstance(result_text, str) or not result_text.strip():
                finish_reason = getattr(choice, "finish_reason", None) or "unknown"
                raise ValueError(
                    "LLM response did not contain text content "
                    f"(finish_reason={finish_reason})"
                )
            result_text = result_text.strip()
            
            # Парсим JSON ответ
            result_data = self._parse_json_response(result_text)
            result = self._coerce_extraction_result(result_data)
            if not result.entities and not result.summary:
                return self._extract_knowledge_fallback(text)
            return result
            
        except Exception as e:
            print(f"Error during LLM extraction: {e}")
            # Fallback к эвристическому методу
            return self._extract_knowledge_fallback(text)

    def _parse_json_response(self, result_text: str) -> Dict[str, Any]:
        """Parse JSON, including responses wrapped in prose or code fences."""
        try:
            return json.loads(result_text)
        except json.JSONDecodeError:
            start = result_text.find("{")
            end = result_text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            return json.loads(result_text[start:end + 1])

    def _coerce_extraction_result(self, result_data: Dict[str, Any]) -> ExtractionResult:
        """Build an extraction result while skipping malformed LLM items."""
        if not isinstance(result_data, dict):
            return ExtractionResult()

        entities = []
        for item in result_data.get("entities", []):
            if not isinstance(item, dict):
                continue
            try:
                entities.append(ExtractedEntity(**item))
            except ValidationError:
                continue

        relations = []
        for item in result_data.get("relations", []):
            if not isinstance(item, dict):
                continue
            try:
                relations.append(ExtractedRelation(**item))
            except ValidationError:
                continue

        summary = result_data.get("summary", "")
        if not isinstance(summary, str):
            summary = ""

        return ExtractionResult(
            entities=entities,
            relations=relations,
            summary=summary,
        )
    
    def _extract_knowledge_fallback(self, text: str) -> ExtractionResult:
        """
        Эвристическое извлечение без LLM (fallback).
        
        Использует простые правила для извлечения базовой структуры.
        """
        # Разбиваем текст на предложения
        sentences = [s.strip() for s in text.replace('\n', '.').split('.') if s.strip()]
        
        entities = []
        relations = []
        
        # Простое эвристическое извлечение
        for i, sentence in enumerate(sentences[:10]):  # Ограничиваем первыми 10 предложениями
            if len(sentence) > 20:  # Пропускаем очень короткие
                # Определяем тип по ключевым словам
                node_type = "fact"
                if any(word in sentence.lower() for word in ["это", "является", "представляет"]):
                    node_type = "definition"
                elif any(word in sentence.lower() for word in ["должен", "следует", "важно"]):
                    node_type = "thesis"
                elif "?" in sentence:
                    node_type = "question"
                elif any(word in sentence.lower() for word in ["концепция", "идея", "принцип"]):
                    node_type = "concept"
                
                # Создаём сущность
                entity_name = sentence[:50] + "..." if len(sentence) > 50 else sentence
                entities.append(ExtractedEntity(
                    name=entity_name,
                    type=node_type,
                    description=sentence,
                    confidence=0.7
                ))
                
                # Создаём связи между последовательными предложениями
                if i > 0:
                    prev_name = sentences[i-1][:50] + "..." if len(sentences[i-1]) > 50 else sentences[i-1]
                    relations.append(ExtractedRelation(
                        source=prev_name,
                        target=entity_name,
                        type="related_to",
                        description="Последовательное упоминание",
                        confidence=0.5
                    ))
        
        summary = text[:200] + "..." if len(text) > 200 else text
        
        return ExtractionResult(
            entities=entities,
            relations=relations,
            summary=summary
        )
    
    def extraction_result_to_graph_elements(
        self, 
        result: ExtractionResult,
        fragment: KnowledgeFragment
    ) -> Tuple[List[Node], List[Edge]]:
        """
        Конвертировать результат извлечения в узлы и связи графа.
        
        Args:
            result: Результат извлечения
            fragment: Исходный фрагмент знания
            
        Returns:
            Кортеж (список узлов, список связей)
        """
        nodes = []
        edges = []
        
        # Словарь для маппинга имён сущностей на их ID
        entity_name_to_id: Dict[str, str] = {}
        
        # Создаём узлы
        for entity in result.entities:
            node_type = NodeType(entity.type) if entity.type in [t.value for t in NodeType] else NodeType.FACT
            
            node = Node(
                content=entity.description,
                node_type=node_type,
                metadata={
                    'source': fragment.id,
                    'source_type': fragment.source_type,
                    'original_name': entity.name,
                    'extraction_confidence': entity.confidence
                }
            )
            
            entity_name_to_id[entity.name] = node.id
            nodes.append(node)
        
        # Создаём связи
        for relation in result.relations:
            source_id = entity_name_to_id.get(relation.source)
            target_id = entity_name_to_id.get(relation.target)
            
            # Пропускаем связи, если сущности не найдены
            if not source_id or not target_id:
                continue
            
            edge_type = EdgeType(relation.type) if relation.type in [t.value for t in EdgeType] else EdgeType.RELATED_TO
            
            edge = Edge(
                source_id=source_id,
                target_id=target_id,
                edge_type=edge_type,
                weight=relation.confidence,
                metadata={
                    'description': relation.description,
                    'source_fragment': fragment.id
                }
            )
            
            edges.append(edge)
        
        return nodes, edges


# Convenience function
async def extract_and_store(
    text: str,
    repository,
    source_type: str = 'manual',
    source_url: Optional[str] = None,
    llm_service: Optional[LLMService] = None
) -> KnowledgeFragment:
    """
    Извлечь знания из текста и сохранить в граф.
    
    Args:
        text: Текст для обработки
        repository: GraphRepository для сохранения
        source_type: Тип источника
        source_url: URL источника (если есть)
        llm_service: LLM сервис (если None, создаётся новый)
        
    Returns:
        KnowledgeFragment с информацией о обработанном тексте
    """
    if llm_service is None:
        llm_service = LLMService()
    
    # Создаём фрагмент
    fragment = KnowledgeFragment(
        content=text,
        source_type=source_type,
        source_url=source_url
    )
    
    # Извлекаем знания
    extraction_result = await llm_service.extract_knowledge(text)
    
    # Конвертируем в узлы и связи
    nodes, edges = llm_service.extraction_result_to_graph_elements(extraction_result, fragment)
    
    # Сохраняем в граф
    for node in nodes:
        repository.add_node(node)
        fragment.extracted_nodes.append(node.id)
    
    for edge in edges:
        repository.add_edge(edge)
    
    # Сохраняем фрагмент
    repository.add_fragment(fragment)
    
    # Сохраняем граф на диск (если настроено)
    if repository.storage_path:
        repository.save()
    
    return fragment
