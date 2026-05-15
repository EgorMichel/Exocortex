"""
Модели данных для графа знаний Exocortex.

Основные сущности:
- Node: узел графа MVP 2
- Edge: ручная логическая связь между узлами
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
    IDEA = "idea"               # Собственная мысль пользователя
    FACT = "fact"               # Утверждение о мире
    QUOTE = "quote"             # Цитата или выделенный фрагмент
    QUESTION = "question"       # Открытый вопрос
    CONCLUSION = "conclusion"   # Вывод
    SOURCE = "source"           # Источник информации


class EdgeType(Enum):
    """Типы связей между узлами."""
    USED_IN = "used_in"             # Используется в
    DERIVED_FROM = "derived_from"   # Следует из / является следствием
    CONTRADICTS = "contradicts"     # Противоречит


class TrustStatus(Enum):
    """Статусы доверия для узлов и связей."""
    CONFIRMED = "confirmed"
    SUGGESTED = "suggested"
    AUTO_INFERRED = "auto_inferred"
    CONFLICT = "conflict"
    NEEDS_CLARIFICATION = "needs_clarification"


class Origin(Enum):
    """Источник появления узла или связи."""
    USER = "user"
    LLM = "llm"
    AGENT = "agent"
    SYSTEM = "system"


class ReviewStatus(Enum):
    """Статус пользовательской проверки."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EDITED = "edited"


PROVENANCE_FIELDS = (
    "source_id",
    "source_url",
    "document_title",
    "author",
    "published_at",
    "added_at",
    "source_type",
    "position",
    "offset_start",
    "offset_end",
    "source_text",
    "user_comment",
)


@dataclass
class SourceProvenance:
    """Structured provenance attachment for a knowledge node."""
    source_id: Optional[str] = None
    source_url: Optional[str] = None
    document_title: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[str] = None
    added_at: Optional[str] = None
    source_type: Optional[str] = None
    position: Optional[str] = None
    offset_start: Optional[int] = None
    offset_end: Optional[int] = None
    source_text: Optional[str] = None
    user_comment: Optional[str] = None

    def __post_init__(self):
        self.source_id = self._clean_text(self.source_id)
        self.source_url = self._clean_text(self.source_url)
        self.document_title = self._clean_text(self.document_title)
        self.author = self._clean_text(self.author)
        self.published_at = self._clean_text(self.published_at)
        self.added_at = self._clean_text(self.added_at)
        self.source_type = self._clean_text(self.source_type)
        self.position = self._clean_text(self.position)
        self.source_text = self._clean_text(self.source_text)
        self.user_comment = self._clean_text(self.user_comment)
        self.offset_start = self._clean_int(self.offset_start)
        self.offset_end = self._clean_int(self.offset_end)
        if self.has_data() and not self.added_at:
            self.added_at = utc_now().isoformat()
        if self.has_data() and not self.source_id:
            self.source_id = self.build_source_id(
                source_url=self.source_url,
                document_title=self.document_title,
                source_type=self.source_type,
                source_text=self.source_text,
            )

    @staticmethod
    def _clean_text(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _clean_int(value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def build_source_id(
        source_url: Optional[str] = None,
        document_title: Optional[str] = None,
        source_type: Optional[str] = None,
        source_text: Optional[str] = None,
    ) -> str:
        """Build a stable non-graph source id for repeated captures."""
        parts = [
            SourceProvenance._clean_text(source_url),
            SourceProvenance._clean_text(document_title),
            SourceProvenance._clean_text(source_type),
        ]
        if not any(parts):
            parts.append(SourceProvenance._clean_text(source_text))
        key = "|".join(part or "" for part in parts) or "manual"
        return f"src_{uuid.uuid5(uuid.NAMESPACE_URL, key).hex}"

    @classmethod
    def from_metadata(
        cls,
        metadata: Optional[Dict[str, Any]] = None,
        source_text: Optional[str] = None,
    ) -> Optional["SourceProvenance"]:
        metadata = metadata or {}
        nested = metadata.get("provenance")
        if isinstance(nested, str):
            try:
                nested = json.loads(nested)
            except json.JSONDecodeError:
                nested = {}
        if not isinstance(nested, dict):
            nested = {}

        values: Dict[str, Any] = {}
        for field_name in PROVENANCE_FIELDS:
            if field_name in nested:
                values[field_name] = nested[field_name]
            elif field_name in metadata:
                values[field_name] = metadata[field_name]

        if values.get("offset_start") is None and metadata.get("source_offset_start") is not None:
            values["offset_start"] = metadata.get("source_offset_start")
        if values.get("offset_end") is None and metadata.get("source_offset_end") is not None:
            values["offset_end"] = metadata.get("source_offset_end")
        if values.get("user_comment") is None and metadata.get("source_user_comment") is not None:
            values["user_comment"] = metadata.get("source_user_comment")
        if values.get("source_text") is None and source_text:
            values["source_text"] = source_text

        provenance = cls(**values)
        return provenance if provenance.has_data() else None

    def has_data(self) -> bool:
        return any(
            getattr(self, field_name) is not None
            for field_name in PROVENANCE_FIELDS
            if field_name != "added_at"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in PROVENANCE_FIELDS
            if getattr(self, field_name) is not None
        }


@dataclass
class Node:
    """
    Узел графа знаний.
    
    Атрибуты:
        id: Уникальный идентификатор узла
        node_type: Тип узла
        content: Основное содержание (текст)
        source_text: Исходный текст/цитата, на котором основан узел
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
    source_text: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    provenance: Optional[SourceProvenance] = None
    trust_status: TrustStatus = TrustStatus.CONFIRMED
    origin: Origin = Origin.USER
    review_status: ReviewStatus = ReviewStatus.ACCEPTED
    user_comment: Optional[str] = None
    title: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    strength: float = 1.0
    decay_rate: float = 0.01  # 1% в день по умолчанию
    last_interacted: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)
    embeddings: Optional[list[float]] = None
    
    def __post_init__(self):
        if isinstance(self.provenance, dict):
            self.provenance = SourceProvenance(**self.provenance)
        if self.provenance is None:
            self.provenance = SourceProvenance.from_metadata(
                self.metadata,
                source_text=self.source_text,
            )
        elif self.source_text and not self.provenance.source_text:
            self.provenance.source_text = self.source_text
        if self.provenance and not self.source_text and self.provenance.source_text:
            self.source_text = self.provenance.source_text
        if self.trust_status == TrustStatus.CONFIRMED and self.metadata.get('trust_status'):
            self.trust_status = self.metadata['trust_status']
        if self.origin == Origin.USER and self.metadata.get('origin'):
            self.origin = self.metadata['origin']
        if self.review_status == ReviewStatus.ACCEPTED and self.metadata.get('review_status'):
            self.review_status = self.metadata['review_status']
        if self.user_comment is None and self.metadata.get('user_comment'):
            self.user_comment = self.metadata['user_comment']
        if self.title is None and self.metadata.get('title'):
            self.title = self.metadata['title']
        if not self.tags and self.metadata.get('tags'):
            self.tags = self.metadata['tags']
        if isinstance(self.node_type, str):
            self.node_type = NodeType(self.node_type)
        if isinstance(self.trust_status, str):
            self.trust_status = TrustStatus(self.trust_status)
        if isinstance(self.origin, str):
            self.origin = Origin(self.origin)
        if isinstance(self.review_status, str):
            self.review_status = ReviewStatus(self.review_status)
        if isinstance(self.tags, str):
            self.tags = [self.tags]
        self.tags = [str(tag) for tag in self.tags]
        self._sync_standard_metadata()

    def _sync_standard_metadata(self) -> None:
        """Keep standard MVP 2 metadata keys available for older callers."""
        self.metadata.setdefault('source', 'manual')
        if self.provenance:
            if self.source_text:
                self.provenance.source_text = self.source_text
            elif self.provenance.source_text:
                self.source_text = self.provenance.source_text
            provenance_data = self.provenance.to_dict()
            if provenance_data:
                self.metadata['provenance'] = provenance_data
                for key, value in provenance_data.items():
                    self.metadata[key] = value
        self.metadata['trust_status'] = self.trust_status.value
        self.metadata['origin'] = self.origin.value
        self.metadata['review_status'] = self.review_status.value
        self.metadata['user_comment'] = self.user_comment
        self.metadata['title'] = self.title
        self.metadata['tags'] = self.tags
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация узла в словарь."""
        self._sync_standard_metadata()
        return {
            'id': self.id,
            'node_type': self.node_type.value,
            'content': self.content,
            'source_text': self.source_text or '',
            'metadata': json.dumps(self.metadata),  # Сериализуем dict как JSON string
            'trust_status': self.trust_status.value,
            'origin': self.origin.value,
            'review_status': self.review_status.value,
            'user_comment': self.user_comment or '',
            'title': self.title or '',
            'tags': json.dumps(self.tags),
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
        # Удаляем служебные атрибуты NetworkX, которые не являются частью модели Node
        data.pop('label', None)

        data['source_text'] = data.get('source_text') or None
        data['node_type'] = NodeType(data['node_type'])
        data['metadata'] = json.loads(data['metadata']) if isinstance(data.get('metadata'), str) else data.get('metadata', {})
        provenance_data = data.get('provenance')
        if isinstance(provenance_data, str):
            provenance_data = json.loads(provenance_data) if provenance_data else None
        data['provenance'] = (
            SourceProvenance(**provenance_data)
            if isinstance(provenance_data, dict)
            else SourceProvenance.from_metadata(data['metadata'], source_text=data.get('source_text'))
        )
        data['trust_status'] = TrustStatus(data.get('trust_status') or data['metadata'].get('trust_status') or TrustStatus.CONFIRMED.value)
        data['origin'] = Origin(data.get('origin') or data['metadata'].get('origin') or Origin.USER.value)
        data['review_status'] = ReviewStatus(data.get('review_status') or data['metadata'].get('review_status') or ReviewStatus.ACCEPTED.value)
        data['user_comment'] = data.get('user_comment') or data['metadata'].get('user_comment') or None
        data['title'] = data.get('title') or data['metadata'].get('title') or None
        tags_data = data.get('tags', data['metadata'].get('tags', []))
        if isinstance(tags_data, str):
            tags_data = json.loads(tags_data) if tags_data else []
        data['tags'] = tags_data if isinstance(tags_data, list) else []
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
    edge_type: EdgeType = EdgeType.USED_IN
    weight: float = 1.0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)
    trust_status: TrustStatus = TrustStatus.CONFIRMED
    origin: Origin = Origin.USER
    review_status: ReviewStatus = ReviewStatus.ACCEPTED
    user_comment: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
    
    def __post_init__(self):
        if self.trust_status == TrustStatus.CONFIRMED and self.metadata.get('trust_status'):
            self.trust_status = self.metadata['trust_status']
        if self.origin == Origin.USER and self.metadata.get('origin'):
            self.origin = self.metadata['origin']
        if self.review_status == ReviewStatus.ACCEPTED and self.metadata.get('review_status'):
            self.review_status = self.metadata['review_status']
        if self.user_comment is None and self.metadata.get('user_comment'):
            self.user_comment = self.metadata['user_comment']
        if isinstance(self.edge_type, str):
            self.edge_type = EdgeType(self.edge_type)
        if isinstance(self.trust_status, str):
            self.trust_status = TrustStatus(self.trust_status)
        if isinstance(self.origin, str):
            self.origin = Origin(self.origin)
        if isinstance(self.review_status, str):
            self.review_status = ReviewStatus(self.review_status)
        self._sync_standard_metadata()

    def _sync_standard_metadata(self) -> None:
        """Keep standard MVP 2 metadata keys available for older callers."""
        self.metadata['trust_status'] = self.trust_status.value
        self.metadata['origin'] = self.origin.value
        self.metadata['review_status'] = self.review_status.value
        self.metadata['user_comment'] = self.user_comment
    
    def to_dict(self) -> Dict[str, Any]:
        """Сериализация связи в словарь."""
        self._sync_standard_metadata()
        return {
            'id': self.id,
            'source_id': self.source_id,
            'target_id': self.target_id,
            'edge_type': self.edge_type.value,
            'weight': self.weight,
            'metadata': json.dumps(self.metadata),  # Сериализуем dict как JSON string
            'trust_status': self.trust_status.value,
            'origin': self.origin.value,
            'review_status': self.review_status.value,
            'user_comment': self.user_comment or '',
            'created_at': self.created_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Edge':
        """Десериализация связи из словаря."""
        data = data.copy()
        data['edge_type'] = EdgeType(data['edge_type'])
        data['metadata'] = json.loads(data['metadata']) if isinstance(data.get('metadata'), str) else data.get('metadata', {})
        data['trust_status'] = TrustStatus(data.get('trust_status') or data['metadata'].get('trust_status') or TrustStatus.CONFIRMED.value)
        data['origin'] = Origin(data.get('origin') or data['metadata'].get('origin') or Origin.USER.value)
        data['review_status'] = ReviewStatus(data.get('review_status') or data['metadata'].get('review_status') or ReviewStatus.ACCEPTED.value)
        data['user_comment'] = data.get('user_comment') or data['metadata'].get('user_comment') or None
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
