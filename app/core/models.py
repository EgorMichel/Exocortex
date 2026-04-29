"""
Модели данных для графа знаний Exocortex.

Основные сущности:
- Node: узел графа (факт, концепция, тезис)
- Edge: связь между узлами
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from enum import Enum
import uuid
import json


def utc_now() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


class NodeType(Enum):
    """Типы узлов графа знаний."""
    FACT = "fact"           # Конкретный факт
    CONCEPT = "concept"     # Абстрактная концепция
    THESIS = "thesis"       # Тезис/утверждение
    DEFINITION = "definition"  # Определение термина
    QUESTION = "question"   # Вопрос
    SOURCE = "source"       # Источник информации


class EdgeType(Enum):
    """Типы связей между узлами."""
    RELATED_TO = "related_to"       # Общая связь
    CONTRADICTS = "contradicts"     # Противоречит
    SUPPORTS = "supports"           # Подтверждает
    EXAMPLE_OF = "example_of"       # Является примером
    PART_OF = "part_of"             # Является частью
    DERIVED_FROM = "derived_from"   # Выведено из
    SIMILAR_TO = "similar_to"       # Похоже на


@dataclass
class Node:
    """
    Узел графа знаний.
    
    Атрибуты:
        id: Уникальный идентификатор узла
        node_type: Тип узла
        content: Основное содержание (текст)
        metadata: Дополнительные метаданные
        strength: Сила памяти (0-1), увеличивается при взаимодействии
        decay_rate: Скорость забывания (0-1 в день)
        last_interacted: Дата последнего взаимодействия
        created_at: Дата создания
        embeddings: Векторное представление (для семантического поиска)
    """
    content: str
    node_type: NodeType = NodeType.FACT
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)
    strength: float = 1.0
    decay_rate: float = 0.01  # 1% в день по умолчанию
    last_interacted: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)
    embeddings: Optional[list[float]] = None
    
    def __post_init__(self):
        if isinstance(self.node_type, str):
            self.node_type = NodeType(self.node_type)
        if not self.metadata.get('source'):
            self.metadata['source'] = 'manual'
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация узла в словарь."""
        return {
            'id': self.id,
            'node_type': self.node_type.value,
            'content': self.content,
            'metadata': json.dumps(self.metadata),  # Сериализуем dict как JSON string
            'strength': self.strength,
            'decay_rate': self.decay_rate,
            'last_interacted': self.last_interacted.isoformat(),
            'created_at': self.created_at.isoformat(),
            'embeddings': json.dumps(self.embeddings) if self.embeddings else '[]'  # None -> '[]'
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Node':
        """Десериализация узла из словаря."""
        data = data.copy()
        data['node_type'] = NodeType(data['node_type'])
        data['metadata'] = json.loads(data['metadata']) if isinstance(data.get('metadata'), str) else data['metadata']
        embeddings_data = data.get('embeddings')
        data['embeddings'] = json.loads(embeddings_data) if isinstance(embeddings_data, str) and embeddings_data != '[]' else None
        data['last_interacted'] = datetime.fromisoformat(data['last_interacted'])
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        return cls(**data)
    
    def interact(self):
        """Увеличить силу памяти при взаимодействии."""
        self.strength = min(1.0, self.strength + 0.1)
        self.last_interacted = utc_now()
    
    def calculate_current_strength(self) -> float:
        """
        Рассчитать текущую силу памяти с учётом забывания.
        
        Использует экспоненциальную модель забывания:
        strength(t) = initial_strength * e^(-decay_rate * t)
        где t - время в днях с последнего взаимодействия
        """
        days_since_interaction = (utc_now() - self.last_interacted).days
        if days_since_interaction <= 0:
            return self.strength
        
        decay_factor = 2.71828 ** (-self.decay_rate * days_since_interaction)
        return self.strength * decay_factor
    
    def is_forgotten(self, threshold: float = 0.3) -> bool:
        """Проверить, считается ли узел «забытым» (сила ниже порога)."""
        return self.calculate_current_strength() < threshold


@dataclass
class Edge:
    """
    Связь между узлами графа знаний.
    
    Атрибуты:
        id: Уникальный идентификатор связи
        source_id: ID исходного узла
        target_id: ID целевого узла
        edge_type: Тип связи
        weight: Вес связи (сила взаимосвязи)
        metadata: Дополнительные метаданные
        created_at: Дата создания
    """
    source_id: str
    target_id: str
    edge_type: EdgeType = EdgeType.RELATED_TO
    weight: float = 1.0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    
    def __post_init__(self):
        if isinstance(self.edge_type, str):
            self.edge_type = EdgeType(self.edge_type)
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация связи в словарь."""
        return {
            'id': self.id,
            'source_id': self.source_id,
            'target_id': self.target_id,
            'edge_type': self.edge_type.value,
            'weight': self.weight,
            'metadata': json.dumps(self.metadata),  # Сериализуем dict как JSON string
            'created_at': self.created_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Edge':
        """Десериализация связи из словаря."""
        data = data.copy()
        data['edge_type'] = EdgeType(data['edge_type'])
        data['metadata'] = json.loads(data['metadata']) if isinstance(data.get('metadata'), str) else data['metadata']
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        return cls(**data)


@dataclass
class KnowledgeFragment:
    """
    Исходный фрагмент знания (контекст).
    
    Используется для хранения полного текста источника,
    из которого были извлечены узлы и связи.
    
    Атрибуты:
        id: Уникальный идентификатор
        content: Полный текст фрагмента
        source_type: Тип источника (chat, article, note)
        source_url: URL источника (если есть)
        extracted_nodes: IDs узлов, извлечённых из этого фрагмента
        created_at: Дата добавления
    """
    content: str
    source_type: str = 'manual'
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_url: Optional[str] = None
    extracted_nodes: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация фрагмента в словарь."""
        return {
            'id': self.id,
            'content': self.content,
            'source_type': self.source_type,
            'source_url': self.source_url,
            'extracted_nodes': self.extracted_nodes,
            'created_at': self.created_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KnowledgeFragment':
        """Десериализация фрагмента из словаря."""
        data = data.copy()
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        return cls(**data)
