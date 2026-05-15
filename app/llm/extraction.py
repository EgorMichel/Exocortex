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

from app.core.models import (
    Edge,
    EdgeLayer,
    EdgeType,
    KnowledgeFragment,
    Node,
    NodeType,
    Origin,
    ReviewStatus,
    TrustStatus,
    coerce_edge_type,
)


class ExtractedEntity(BaseModel):
    """Сущность, извлечённая из текста."""
    name: str = Field(description="Название сущности")
    type: str = Field(description="Тип сущности: idea, fact, quote, question, conclusion")
    description: str = Field(description="Описание или содержание сущности")
    confidence: float = Field(default=1.0, description="Уверенность в извлечении (0-1)")


class ExtractedRelation(BaseModel):
    """Связь между сущностями."""
    source: str = Field(description="Название исходной сущности")
    target: str = Field(description="Название целевой сущности")
    type: str = Field(description="Тип связи: used_in, derived_from, contradicts")
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
        provider_value = provider or os.getenv("LLM_PROVIDER") or "openai"
        self.provider: str = provider_value.strip().lower()
        if self.provider == "local":
            self.provider = "ollama"

        if self.provider == "ollama":
            self.api_key: Optional[str] = api_key or os.getenv("LLM_API_KEY") or "ollama"
            self.model: str = model or os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or "llama3.1"
            self.base_url: Optional[str] = self._normalize_ollama_base_url(
                base_url
                or os.getenv("LLM_API_BASE")
                or os.getenv("OLLAMA_BASE_URL")
                or "http://localhost:11434"
            )
        else:
            self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
            self.model = model or os.getenv("LLM_MODEL") or "gpt-4o-mini"
            self.base_url = base_url or os.getenv("LLM_API_BASE") or os.getenv("OPENAI_API_BASE")
        self.client = None
        self.last_status = "skipped"
        self.last_warnings: list[str] = []
        self.last_errors: list[str] = []
        
        if self.api_key:
            try:
                from openai import AsyncOpenAI

                client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
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
1. Key knowledge entities (ideas, facts, quotes, questions, conclusions)
2. Explicit logical relationships between these entities

All human-readable JSON values must be written in Russian, regardless of the
source text language. This includes entity names, entity descriptions, relation
descriptions, and the summary. Translate or summarize source content into
Russian when necessary. Keep JSON keys and enum values exactly as specified.

Text to analyze:
{text}

Extract entities and relationships in JSON format with this exact structure:
{{
    "entities": [
        {{
            "name": "entity name",
            "type": "idea|fact|quote|question|conclusion",
            "description": "detailed description of the entity",
            "confidence": 0.95
        }}
    ],
    "relations": [
        {{
            "source": "source entity name",
            "target": "target entity name",
            "type": "used_in|derived_from|contradicts",
            "description": "description of the relationship",
            "confidence": 0.9
        }}
    ],
    "summary": "brief summary of the text in 1-2 sentences"
}}

Rules:
- Extract only meaningful, standalone entities
- Use only the listed node and relationship enum values
- Never create source entities; sources belong to provenance/context metadata, not to the knowledge graph
- Do not use generic relatedness, support, examples, clarification, or similarity as manual relationships
- Use used_in only when one entity is explicitly used in another entity, argument, conclusion, or context
- Use derived_from only when the source-target direction is clear: source follows from target
- Use contradicts only for actual contradictions
- Don't create duplicate entities
- Only create relationships that are explicitly stated or strongly implied
- Set confidence based on how clear/certain the information is
- Write all facts, names, descriptions, comments, and summaries in Russian
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
            print("LLM extraction skipped: no LLM client configured.")
            self.last_status = "skipped"
            self.last_warnings = ["LLM client is not configured."]
            self.last_errors = []
            return ExtractionResult()
        
        try:
            prompt = self._get_extraction_prompt(text)
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a knowledge extraction assistant. "
                            "Always respond with valid JSON only. "
                            "All human-readable JSON values must be in Russian, "
                            "regardless of the source text language."
                        ),
                    },
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
            self.last_status = "succeeded"
            self.last_warnings = []
            self.last_errors = []
            return result
            
        except Exception as e:
            print(f"Error during LLM extraction: {e}")
            self.last_status = "failed"
            self.last_warnings = []
            self.last_errors = [str(e)]
            return ExtractionResult()

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
            if entity.type == NodeType.SOURCE.value:
                continue
            knowledge_types = {
                NodeType.IDEA.value,
                NodeType.FACT.value,
                NodeType.QUOTE.value,
                NodeType.QUESTION.value,
                NodeType.CONCLUSION.value,
            }
            node_type = NodeType(entity.type) if entity.type in knowledge_types else NodeType.FACT
            
            node = Node(
                content=entity.description,
                node_type=node_type,
                metadata={
                    'source': fragment.id,
                    'source_type': fragment.source_type,
                    'original_name': entity.name,
                    'extraction_confidence': entity.confidence
                },
                trust_status=TrustStatus.SUGGESTED,
                origin=Origin.LLM,
                review_status=ReviewStatus.PENDING,
                title=entity.name,
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
            
            try:
                edge_type = coerce_edge_type(relation.type)
            except ValueError:
                continue
            
            edge = Edge(
                source_id=source_id,
                target_id=target_id,
                edge_type=edge_type,
                edge_layer=EdgeLayer.SUGGESTED,
                weight=relation.confidence,
                metadata={
                    'description': relation.description,
                    'source_fragment': fragment.id
                },
                trust_status=TrustStatus.SUGGESTED,
                origin=Origin.LLM,
                review_status=ReviewStatus.PENDING,
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
    fragment.llm_status = getattr(llm_service, "last_status", "skipped")
    fragment.warnings = list(getattr(llm_service, "last_warnings", []) or [])
    fragment.errors = list(getattr(llm_service, "last_errors", []) or [])
    
    # Конвертируем в узлы и связи
    nodes, edges = llm_service.extraction_result_to_graph_elements(extraction_result, fragment)
    if fragment.llm_status == "succeeded" and not nodes:
        fragment.warnings.append("LLM succeeded but produced no accepted knowledge nodes.")
    
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
