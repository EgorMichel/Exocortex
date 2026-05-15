"""
REST API для Exocortex.

Предоставляет endpoints для:
- Добавления знаний (текст, заметки)
- Просмотра графа знаний
- Получения статистики
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.agents.insights import Digest, Insight
from app.agents.proactive import AgentSettings, ProactiveAgent
from app.agents.scheduler import build_agent_scheduler
from app.config import load_settings
from app.core.models import (
    AgentProposal,
    Edge,
    EdgeLayer,
    EdgeType,
    KnowledgeFragment,
    Node,
    NodeType,
    Origin,
    ProposalType,
    ReviewStatus,
    SourceProvenance,
    TrustStatus,
    utc_now,
)
from app.core.repository import GraphRepository
from app.llm.extraction import LLMService, SuggestionResult
from app.services.external_sources import ExternalSourceIngestor
from app.services.manual_capture import store_manual_fragment
from app.services.personalization import InboxItem, InsightFeedback, PersonalizationService


# === Pydantic модели для API ===

class AddKnowledgeRequest(BaseModel):
    """Запрос на добавление знания."""
    text: str = Field(..., description="Текст для обработки", min_length=1)
    source_type: str = Field(default='manual', description="Тип источника: manual, chat, article")
    source_url: Optional[str] = Field(default=None, description="URL источника")


class AddKnowledgeResponse(BaseModel):
    """Ответ после добавления знания."""
    fragment_id: str
    nodes_created: int
    edges_created: int
    summary: str
    suggestions_created: int = 0
    llm_status: str = "skipped"
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class IngestSourceRequest(BaseModel):
    """Запрос на импорт внешнего текстового источника."""
    text: Optional[str] = Field(default=None, description="Текст для импорта")
    url: Optional[str] = Field(default=None, description="URL текстового источника")
    source_type: str = Field(default="external", description="Тип источника")


class ManualFragmentRequest(BaseModel):
    """Запрос на ручное сохранение выделенного фрагмента."""
    text: str = Field(..., description="Выделенный текст", min_length=1)
    source_text: Optional[str] = Field(default=None, description="Исходный текст или цитата")
    node_type: Optional[str] = Field(default=None, description="Тип создаваемого узла")
    tags: List[str] = Field(default_factory=list, description="Пользовательские теги")
    source_type: str = Field(default="manual_selection", description="Тип источника")
    source_id: Optional[str] = Field(default=None, description="Стабильный ID provenance-источника")
    source_url: Optional[str] = Field(default=None, description="URL или путь источника")
    document_title: Optional[str] = Field(default=None, description="Название документа")
    author: Optional[str] = Field(default=None, description="Автор источника")
    published_at: Optional[str] = Field(default=None, description="Дата публикации источника")
    added_at: Optional[str] = Field(default=None, description="Дата добавления источника")
    position: Optional[str] = Field(default=None, description="Позиция в источнике")
    offset_start: Optional[int] = Field(default=None, description="Начальное смещение в источнике")
    offset_end: Optional[int] = Field(default=None, description="Конечное смещение в источнике")
    source_user_comment: Optional[str] = Field(default=None, description="Комментарий к provenance-источнику")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные выделения")


class ManualFragmentResponse(BaseModel):
    """Ответ после ручного сохранения фрагмента."""
    fragment_id: str
    node_id: str
    node_type: str
    nodes_created: int
    edges_created: int
    summary: str


class NodeCreateRequest(BaseModel):
    """Запрос на ручное создание узла."""
    content: str = Field(..., min_length=1)
    node_type: str = Field(...)
    source_text: Optional[str] = None
    title: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    user_comment: Optional[str] = None
    provenance: Optional["SourceProvenanceRequest"] = None
    trust_status: Optional[str] = None
    origin: Optional[str] = None
    review_status: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NodePatchRequest(BaseModel):
    """Запрос на ручное редактирование узла."""
    content: Optional[str] = None
    node_type: Optional[str] = None
    source_text: Optional[str] = None
    title: Optional[str] = None
    tags: Optional[List[str]] = None
    user_comment: Optional[str] = None
    provenance: Optional["SourceProvenanceRequest"] = None
    trust_status: Optional[str] = None
    origin: Optional[str] = None
    review_status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class EdgeCreateRequest(BaseModel):
    """Запрос на ручное создание связи."""
    source_id: str = Field(..., min_length=1)
    target_id: str = Field(..., min_length=1)
    edge_type: str = Field(...)
    edge_layer: Optional[str] = None
    weight: float = Field(default=1.0)
    user_comment: Optional[str] = None
    trust_status: Optional[str] = None
    origin: Optional[str] = None
    review_status: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EdgePatchRequest(BaseModel):
    """Запрос на ручное редактирование связи."""
    source_id: Optional[str] = None
    target_id: Optional[str] = None
    edge_type: Optional[str] = None
    edge_layer: Optional[str] = None
    weight: Optional[float] = None
    user_comment: Optional[str] = None
    trust_status: Optional[str] = None
    origin: Optional[str] = None
    review_status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SourceProvenanceRequest(BaseModel):
    """Структурированная provenance-привязка knowledge-узла."""
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


try:
    NodeCreateRequest.model_rebuild()
    NodePatchRequest.model_rebuild()
except AttributeError:
    NodeCreateRequest.update_forward_refs(SourceProvenanceRequest=SourceProvenanceRequest)
    NodePatchRequest.update_forward_refs(SourceProvenanceRequest=SourceProvenanceRequest)


class NodeResponse(BaseModel):
    """Представление узла в API."""
    id: str
    node_type: str
    content: str
    source_text: Optional[str] = None
    strength: float
    created_at: str
    metadata: Dict[str, Any]
    trust_status: str
    origin: str
    review_status: str
    user_comment: Optional[str] = None
    title: Optional[str] = None
    tags: List[str]
    provenance: Optional[Dict[str, Any]] = None
    source_id: Optional[str] = None
    source_url: Optional[str] = None
    document_title: Optional[str] = None


class EdgeResponse(BaseModel):
    """Представление связи в API."""
    id: str
    source_id: str
    target_id: str
    edge_type: str
    edge_layer: str
    weight: float
    metadata: Dict[str, Any]
    trust_status: str
    origin: str
    review_status: str
    user_comment: Optional[str] = None


class GraphStatsResponse(BaseModel):
    """Статистика графа."""
    schema_version: int = 1
    total_nodes: int
    total_edges: int
    total_fragments: int
    total_proposals: int = 0
    node_types: Dict[str, int]
    edge_types: Dict[str, int]
    edge_layers: Dict[str, int] = Field(default_factory=dict)
    avg_node_strength: float
    forgotten_nodes_count: int


class NodeListResponse(BaseModel):
    """Список узлов."""
    nodes: List[NodeResponse]
    total: int


class EdgeListResponse(BaseModel):
    """Список связей."""
    edges: List[EdgeResponse]
    total: int


class InsightResponse(BaseModel):
    """Представление инсайта в API."""
    id: str
    insight_type: str
    title: str
    description: str
    node_ids: List[str]
    edge_ids: List[str]
    score: float
    metadata: Dict[str, Any]
    created_at: str


class DigestResponse(BaseModel):
    """Дайджест проактивного агента."""
    id: str
    created_at: str
    insights: List[InsightResponse]


class InsightFeedbackRequest(BaseModel):
    """Реакция пользователя на инсайт."""
    action: str = Field(..., description="Действие: confirm, reject, useful, ignore, etc.")
    note: Optional[str] = Field(default=None, description="Необязательное уточнение")
    edge_type: Optional[str] = Field(default=None, description="Тип связи для confirm/refine hidden connection")


class InsightFeedbackResponse(BaseModel):
    """Сохранённая реакция пользователя."""
    id: str
    insight_id: str
    insight_type: str
    action: str
    node_ids: List[str]
    edge_ids: List[str]
    note: Optional[str]
    effects: List[str]
    created_at: str


class InboxItemResponse(BaseModel):
    """Элемент inbox: инсайт и последняя реакция, если она есть."""
    insight: InsightResponse
    feedback: Optional[InsightFeedbackResponse] = None


class InterestProfileResponse(BaseModel):
    """Базовая модель интересов пользователя."""
    total_feedback: int
    positive_feedback: int
    negative_feedback: int
    action_counts: Dict[str, int]
    top_topics: List[Dict[str, Any]]
    node_interactions: Dict[str, int]
    message_style: str


class SuggestionResponse(BaseModel):
    """Reviewable предложение LLM/агента."""
    id: str
    suggestion_type: str
    proposal_type: str
    node_ids: List[str]
    edge_ids: List[str]
    payload: Dict[str, Any]
    score: float
    origin: str
    review_status: str
    effects: List[str] = Field(default_factory=list)
    created_at: str


class SuggestionGenerateResponse(BaseModel):
    """Ответ генерации предложений для узла."""
    node_id: str
    suggestions_generated: int
    suggestions: List[SuggestionResponse]


class SuggestionListResponse(BaseModel):
    """Список reviewable предложений."""
    suggestions: List[SuggestionResponse]
    total: int


class SuggestionDecisionRequest(BaseModel):
    """Действие пользователя над предложением."""
    note: Optional[str] = Field(default=None, description="Комментарий пользователя")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Отредактированные значения перед accept")


class ReviewItemResponse(BaseModel):
    """Единый элемент очереди Review: suggestion или insight."""
    id: str
    item_type: str
    review_kind: str
    title: str
    description: str
    node_ids: List[str]
    edge_ids: List[str]
    payload: Dict[str, Any] = Field(default_factory=dict)
    score: float
    origin: str
    status: str
    feedback: Optional[InsightFeedbackResponse] = None
    open_graph_url: Optional[str] = None
    created_at: str


class ReviewListResponse(BaseModel):
    """Единая очередь review items."""
    items: List[ReviewItemResponse]
    total: int


# === Lifecycle ===

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and persist repository around application lifetime."""
    repository = get_repository()
    settings = load_settings()
    scheduler = None
    if settings.agent_enabled:
        scheduler = build_agent_scheduler(
            repository=repository,
            llm_service=get_llm_service(),
            interval_minutes=settings.agent_interval_minutes,
            agent_settings=AgentSettings(
                digest_limit=settings.agent_digest_limit,
                forgotten_threshold=settings.agent_forgotten_threshold,
                contradiction_batch_size=settings.agent_contradiction_batch_size,
            ),
        )
        scheduler.start()
        print("Proactive agent scheduler started.")
    print(f"Exocortex started. Graph loaded with {len(repository.get_all_nodes())} nodes.")
    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)
        repository = get_repository()
        if repository.storage_path:
            repository.save()
            print("Graph saved to disk.")


# === Создание приложения FastAPI ===

app = FastAPI(
    title="Exocortex API",
    description="API для системы управления персональными знаниями",
    version="0.1.0",
    lifespan=lifespan,
)

WEB_UI_PATH = Path(__file__).resolve().parent.parent / "web" / "inbox.html"
WEB_READER_PATH = Path(__file__).resolve().parent.parent / "web" / "reader.html"
WEB_GRAPH_PATH = Path(__file__).resolve().parent.parent / "web" / "graph.html"

# Глобальный репозиторий (в будущем можно вынести в dependency injection)
_repository: Optional[GraphRepository] = None
_llm_service: Optional[LLMService] = None
_agent: Optional[ProactiveAgent] = None
_personalization_service: Optional[PersonalizationService] = None


def get_repository() -> GraphRepository:
    """Получить или создать репозиторий."""
    global _repository
    if _repository is None:
        settings = load_settings()
        _repository = GraphRepository(storage_path=settings.storage_path)
    return _repository


def get_llm_service() -> LLMService:
    """Получить или создать LLM сервис."""
    global _llm_service
    if _llm_service is None:
        settings = load_settings()
        _llm_service = LLMService(
            provider=settings.llm_provider,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_api_base,
        )
    return _llm_service


def get_agent() -> ProactiveAgent:
    """Получить или создать проактивного агента."""
    global _agent
    if _agent is None:
        settings = load_settings()
        _agent = ProactiveAgent(
            repository=get_repository(),
            llm_service=get_llm_service(),
            settings=AgentSettings(
                digest_limit=settings.agent_digest_limit,
                forgotten_threshold=settings.agent_forgotten_threshold,
                contradiction_batch_size=settings.agent_contradiction_batch_size,
            ),
        )
    return _agent


def get_personalization_service() -> PersonalizationService:
    """Получить или создать сервис персонализации."""
    global _personalization_service
    if _personalization_service is None:
        _personalization_service = PersonalizationService(
            repository=get_repository(),
            insight_store=get_agent().insight_store,
        )
    return _personalization_service


def _insight_response(insight: Insight) -> InsightResponse:
    return InsightResponse(
        id=insight.id,
        insight_type=insight.insight_type.value,
        title=insight.title,
        description=insight.description,
        node_ids=insight.node_ids,
        edge_ids=insight.edge_ids,
        score=insight.score,
        metadata=insight.metadata,
        created_at=insight.created_at.isoformat(),
    )


def _digest_response(digest: Digest) -> DigestResponse:
    return DigestResponse(
        id=digest.id,
        created_at=digest.created_at.isoformat(),
        insights=[_insight_response(insight) for insight in digest.insights],
    )


def _feedback_response(feedback: InsightFeedback) -> InsightFeedbackResponse:
    return InsightFeedbackResponse(
        id=feedback.id,
        insight_id=feedback.insight_id,
        insight_type=feedback.insight_type.value,
        action=feedback.action.value,
        node_ids=feedback.node_ids,
        edge_ids=feedback.edge_ids,
        note=feedback.note,
        effects=feedback.effects,
        created_at=feedback.created_at.isoformat(),
    )


def _inbox_item_response(item: InboxItem) -> InboxItemResponse:
    return InboxItemResponse(
        insight=_insight_response(item.insight),
        feedback=_feedback_response(item.feedback) if item.feedback else None,
    )


def _suggestion_type(proposal: AgentProposal) -> str:
    mapping = {
        ProposalType.PROPOSED_EDGE: ProposalType.MANUAL_EDGE.value,
        ProposalType.PROPOSED_TAG: ProposalType.TAG.value,
        ProposalType.POSSIBLE_DUPLICATE: ProposalType.DUPLICATE.value,
        ProposalType.POSSIBLE_CONTRADICTION: ProposalType.CONTRADICTION.value,
    }
    return mapping.get(proposal.proposal_type, proposal.proposal_type.value)


def _suggestion_response(proposal: AgentProposal, effects: Optional[List[str]] = None) -> SuggestionResponse:
    return SuggestionResponse(
        id=proposal.id,
        suggestion_type=_suggestion_type(proposal),
        proposal_type=proposal.proposal_type.value,
        node_ids=proposal.node_ids,
        edge_ids=proposal.edge_ids,
        payload=proposal.payload,
        score=proposal.score,
        origin=proposal.origin.value,
        review_status=proposal.review_status.value,
        effects=effects or [],
        created_at=proposal.created_at.isoformat(),
    )


def _open_graph_url(node_ids: List[str]) -> Optional[str]:
    return f"/graph?node_id={node_ids[0]}" if node_ids else None


def _is_deferred_suggestion(proposal: AgentProposal) -> bool:
    return bool(proposal.payload.get("review_deferred"))


def _suggestion_review_title(proposal: AgentProposal) -> str:
    payload = proposal.payload
    suggestion_type = _suggestion_type(proposal)
    if suggestion_type == ProposalType.NODE_TITLE.value:
        return f"Title: {payload.get('title') or 'untitled'}"
    if suggestion_type == ProposalType.NODE_TYPE.value:
        content = str(payload.get("content") or "").strip()
        if content:
            return f"Create {payload.get('node_type') or 'node'}: {_short_title(content)}"
        return f"Type: {payload.get('node_type') or 'node'}"
    if suggestion_type == ProposalType.TAG.value:
        return f"Tag: #{payload.get('tag') or ''}"
    if suggestion_type in {ProposalType.MANUAL_EDGE.value, ProposalType.CONTRADICTION.value}:
        return f"{payload.get('edge_type') or 'edge'} link"
    if suggestion_type == ProposalType.SIMILAR_NODE.value:
        return "Similar node"
    if suggestion_type == ProposalType.DUPLICATE.value:
        return "Possible duplicate"
    return suggestion_type


def _suggestion_review_description(repository: GraphRepository, proposal: AgentProposal) -> str:
    payload = proposal.payload
    labels = []
    for node_id in proposal.node_ids[:2]:
        node = repository.get_node(node_id)
        if node:
            labels.append(_node_label(node))
    details = str(
        payload.get("reason")
        or payload.get("source")
        or payload.get("current_node_type")
        or payload.get("similar_title")
        or payload.get("duplicate_title")
        or ""
    ).strip()
    parts = [part for part in [" -> ".join(labels), details] if part]
    return " | ".join(parts) or "Review this suggestion before it changes the graph."


def _review_item_from_suggestion(repository: GraphRepository, proposal: AgentProposal) -> ReviewItemResponse:
    status = "deferred" if proposal.review_status == ReviewStatus.PENDING and _is_deferred_suggestion(proposal) else proposal.review_status.value
    return ReviewItemResponse(
        id=proposal.id,
        item_type="suggestion",
        review_kind=_suggestion_type(proposal),
        title=_suggestion_review_title(proposal),
        description=_suggestion_review_description(repository, proposal),
        node_ids=proposal.node_ids,
        edge_ids=proposal.edge_ids,
        payload=proposal.payload,
        score=proposal.score,
        origin=proposal.origin.value,
        status=status,
        feedback=None,
        open_graph_url=_open_graph_url(proposal.node_ids),
        created_at=proposal.created_at.isoformat(),
    )


def _review_item_from_inbox_item(item: InboxItem) -> ReviewItemResponse:
    insight = item.insight
    status = item.feedback.action.value if item.feedback else "pending"
    return ReviewItemResponse(
        id=insight.id,
        item_type="insight",
        review_kind=insight.insight_type.value,
        title=insight.title,
        description=insight.description,
        node_ids=insight.node_ids,
        edge_ids=insight.edge_ids,
        payload=insight.metadata,
        score=insight.score,
        origin="agent",
        status=status,
        feedback=_feedback_response(item.feedback) if item.feedback else None,
        open_graph_url=_open_graph_url(insight.node_ids),
        created_at=insight.created_at.isoformat(),
    )


def _node_label(node: Node) -> str:
    return node.title or node.content[:80]


def _content_terms(text: str) -> list[str]:
    punctuation = ".,!?;:()[]{}<>\"'`«»“”‘’\n\t\r"
    stopwords = {
        "and", "the", "for", "with", "that", "this", "from", "into", "about",
        "как", "что", "это", "для", "или", "при", "над", "под", "без", "его",
        "она", "они", "если", "когда", "потому", "через", "между",
    }
    terms: list[str] = []
    for raw in text.lower().split():
        term = raw.strip(punctuation)
        if len(term) >= 4 and term not in stopwords and not term.isdigit():
            terms.append(term)
    return terms


def _term_overlap(left: Node, right: Node) -> float:
    left_terms = set(_content_terms(f"{left.title or ''} {left.content} {left.source_text or ''}"))
    right_terms = set(_content_terms(f"{right.title or ''} {right.content} {right.source_text or ''}"))
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _short_title(content: str) -> str:
    words = content.strip().split()
    title = " ".join(words[:8]).strip(" .,:;")
    if len(words) > 8:
        title = f"{title}..."
    return title or "Untitled"


def _suggested_node_type(node: Node) -> Optional[NodeType]:
    text = node.content.strip().lower()
    if "?" in text and node.node_type != NodeType.QUESTION:
        return NodeType.QUESTION
    if text.startswith(("\"", "'", "«", "“")) and node.node_type != NodeType.QUOTE:
        return NodeType.QUOTE
    conclusion_markers = ("therefore", "thus", "следовательно", "итак", "значит", "вывод")
    if any(marker in text for marker in conclusion_markers) and node.node_type != NodeType.CONCLUSION:
        return NodeType.CONCLUSION
    return None


def _is_contradiction_candidate(left: Node, right: Node, overlap: float) -> bool:
    if overlap < 0.2:
        return False
    left_text = left.content.lower()
    right_text = right.content.lower()
    negative_markers = (" not ", "n't", "не ", "нет ", "never", "никогда")
    left_negative = any(marker in f" {left_text} " for marker in negative_markers)
    right_negative = any(marker in f" {right_text} " for marker in negative_markers)
    return left_negative != right_negative


def _proposal_key(proposal_type: ProposalType, node_ids: List[str], payload: Dict[str, Any]) -> tuple[Any, ...]:
    stable_payload = tuple(sorted((key, str(value)) for key, value in payload.items()))
    return (proposal_type.value, tuple(node_ids), stable_payload)


def _existing_suggestion_keys(repository: GraphRepository) -> set[tuple[Any, ...]]:
    return {
        _proposal_key(proposal.proposal_type, proposal.node_ids, proposal.payload)
        for proposal in repository.get_all_proposals()
        if proposal.review_status == ReviewStatus.PENDING
    }


def _is_rejected_by_feedback(node: Node, suggestion_type: ProposalType, payload: Dict[str, Any]) -> bool:
    """Use stored rejection feedback as a light personalization signal."""
    feedback_items = node.metadata.get("suggestion_feedback")
    if not isinstance(feedback_items, list):
        return False

    tag = str(payload.get("tag") or "").strip().lower()
    edge_type = str(payload.get("edge_type") or "").strip().lower()
    target_id = str(payload.get("target_id") or payload.get("similar_node_id") or "").strip()
    for item in feedback_items:
        if not isinstance(item, dict) or item.get("action") != "reject":
            continue
        if item.get("suggestion_type") != suggestion_type.value:
            continue
        raw_payload = item.get("payload")
        rejected_payload: Dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
        if tag and str(rejected_payload.get("tag") or "").strip().lower() == tag:
            return True
        if edge_type and str(rejected_payload.get("edge_type") or "").strip().lower() == edge_type:
            return True
        if target_id and target_id in {
            str(rejected_payload.get("target_id") or ""),
            str(rejected_payload.get("similar_node_id") or ""),
            str(rejected_payload.get("duplicate_node_id") or ""),
        }:
            return True
    return False


def _build_node_suggestions(repository: GraphRepository, node: Node) -> list[AgentProposal]:
    existing_keys = _existing_suggestion_keys(repository)
    suggestions: list[AgentProposal] = []

    def add(proposal_type: ProposalType, node_ids: List[str], payload: Dict[str, Any], score: float) -> None:
        if _is_rejected_by_feedback(node, proposal_type, payload):
            return
        key = _proposal_key(proposal_type, node_ids, payload)
        if key in existing_keys:
            return
        suggestions.append(AgentProposal(
            proposal_type=proposal_type,
            node_ids=node_ids,
            payload=payload,
            score=score,
            origin=Origin.LLM,
            review_status=ReviewStatus.PENDING,
        ))
        existing_keys.add(key)

    if not node.title:
        add(
            ProposalType.NODE_TITLE,
            [node.id],
            {"title": _short_title(node.content), "source": "node_suggestions"},
            0.7,
        )

    suggested_type = _suggested_node_type(node)
    if suggested_type:
        add(
            ProposalType.NODE_TYPE,
            [node.id],
            {"node_type": suggested_type.value, "current_node_type": node.node_type.value},
            0.65,
        )

    for tag in _content_terms(node.content)[:3]:
        if tag not in node.tags:
            add(ProposalType.TAG, [node.id], {"tag": tag}, 0.45)

    for other in repository.get_all_nodes():
        if other.id == node.id:
            continue
        overlap = _term_overlap(node, other)
        if node.content.strip().lower() == other.content.strip().lower() or overlap >= 0.85:
            add(
                ProposalType.DUPLICATE,
                [node.id, other.id],
                {"duplicate_node_id": other.id, "duplicate_title": _node_label(other), "overlap": overlap},
                max(0.9, overlap),
            )
        elif overlap >= 0.25:
            add(
                ProposalType.SIMILAR_NODE,
                [node.id, other.id],
                {"similar_node_id": other.id, "similar_title": _node_label(other), "overlap": overlap},
                overlap,
            )
            add(
                ProposalType.MANUAL_EDGE,
                [node.id, other.id],
                {
                    "source_id": node.id,
                    "target_id": other.id,
                    "edge_type": EdgeType.USED_IN.value,
                    "reason": "similar_node",
                    "suggested_by": "llm",
                },
                overlap,
            )
        if _is_contradiction_candidate(node, other, overlap):
            add(
                ProposalType.CONTRADICTION,
                [node.id, other.id],
                {
                    "source_id": node.id,
                    "target_id": other.id,
                    "edge_type": EdgeType.CONTRADICTS.value,
                    "reason": "opposite_negation_marker",
                    "suggested_by": "llm",
                },
                max(0.7, overlap),
            )

    return suggestions


def _related_nodes_for_suggestions(repository: GraphRepository, node: Node, limit: int = 8) -> list[Node]:
    candidates = [item for item in repository.get_all_nodes() if item.id != node.id]
    candidates.sort(key=lambda item: _term_overlap(node, item), reverse=True)
    return candidates[:limit]


def _suggestions_from_llm_result(
    repository: GraphRepository,
    anchor_node: Optional[Node],
    result: SuggestionResult,
    existing_keys: Optional[set[tuple[Any, ...]]] = None,
) -> list[AgentProposal]:
    """Normalize LLM suggestion JSON into persisted AgentProposal objects."""
    existing_keys = existing_keys or _existing_suggestion_keys(repository)
    suggestions: list[AgentProposal] = []

    for item in result.suggestions:
        try:
            proposal_type = ProposalType(item.type)
        except ValueError:
            continue

        payload = dict(item.payload)
        node_ids = [str(node_id) for node_id in item.node_ids if repository.get_node(str(node_id))]
        if anchor_node and proposal_type in {ProposalType.NODE_TITLE, ProposalType.NODE_TYPE, ProposalType.TAG}:
            node_ids = [anchor_node.id]
        elif anchor_node and proposal_type in {
            ProposalType.SIMILAR_NODE,
            ProposalType.MANUAL_EDGE,
            ProposalType.DUPLICATE,
            ProposalType.CONTRADICTION,
        }:
            source_id = str(payload.get("source_id") or anchor_node.id)
            target_id = str(
                payload.get("target_id")
                or payload.get("similar_node_id")
                or payload.get("duplicate_node_id")
                or (node_ids[0] if node_ids else "")
            )
            if not repository.get_node(source_id) or not repository.get_node(target_id):
                continue
            if source_id == target_id:
                continue
            node_ids = [source_id, target_id]
            payload.setdefault("source_id", source_id)
            payload.setdefault("target_id", target_id)
            if proposal_type == ProposalType.SIMILAR_NODE:
                payload.setdefault("similar_node_id", target_id)
            if proposal_type == ProposalType.DUPLICATE:
                payload.setdefault("duplicate_node_id", target_id)
            if proposal_type == ProposalType.CONTRADICTION:
                payload["edge_type"] = EdgeType.CONTRADICTS.value
            if proposal_type in {ProposalType.MANUAL_EDGE, ProposalType.CONTRADICTION}:
                try:
                    payload["edge_type"] = EdgeType(str(payload.get("edge_type") or EdgeType.USED_IN.value)).value
                except ValueError:
                    continue
                payload.setdefault("suggested_by", "llm")

        if anchor_node and _is_rejected_by_feedback(anchor_node, proposal_type, payload):
            continue
        key = _proposal_key(proposal_type, node_ids, payload)
        if key in existing_keys:
            continue
        suggestions.append(AgentProposal(
            proposal_type=proposal_type,
            node_ids=node_ids,
            payload=payload,
            score=max(0.0, min(1.0, item.score)),
            origin=Origin.LLM,
            review_status=ReviewStatus.PENDING,
        ))
        existing_keys.add(key)

    return suggestions


async def _build_node_suggestions_with_llm(repository: GraphRepository, node: Node) -> list[AgentProposal]:
    related_nodes = _related_nodes_for_suggestions(repository, node)
    llm_result = await get_llm_service().suggest_for_node(node, related_nodes=related_nodes)
    existing_keys = _existing_suggestion_keys(repository)
    suggestions = _suggestions_from_llm_result(repository, node, llm_result, existing_keys=existing_keys)
    existing_keys.update(_proposal_key(item.proposal_type, item.node_ids, item.payload) for item in suggestions)
    heuristic_suggestions = _build_node_suggestions(repository, node)
    for suggestion in heuristic_suggestions:
        key = _proposal_key(suggestion.proposal_type, suggestion.node_ids, suggestion.payload)
        if key not in existing_keys:
            suggestions.append(suggestion)
            existing_keys.add(key)
    return suggestions


async def _build_knowledge_suggestions(
    repository: GraphRepository,
    fragment: KnowledgeFragment,
    llm_service: LLMService,
) -> list[AgentProposal]:
    """Create reviewable suggestions from raw /api/knowledge text without graph writes."""
    llm_result = await llm_service.suggest_for_text(
        fragment.content,
        source_type=fragment.source_type,
        source_url=fragment.source_url,
    )
    suggestions: list[AgentProposal] = []
    existing_keys = _existing_suggestion_keys(repository)
    for item in llm_result.suggestions:
        if item.type != ProposalType.NODE_TYPE.value:
            continue
        payload = dict(item.payload)
        content = str(payload.get("content") or "").strip()
        if not content:
            continue
        try:
            node_type = NodeType(str(payload.get("node_type") or NodeType.FACT.value))
        except ValueError:
            continue
        tags = payload.get("tags")
        payload.update({
            "content": content,
            "node_type": node_type.value,
            "title": str(payload.get("title") or _short_title(content)).strip(),
            "tags": _clean_tags(tags if isinstance(tags, list) else []),
            "source_text": str(payload.get("source_text") or fragment.content).strip(),
            "source_type": fragment.source_type,
            "source_url": fragment.source_url,
            "source_fragment": fragment.id,
            "suggested_by": "llm",
        })
        key = _proposal_key(ProposalType.NODE_TYPE, [], payload)
        if key in existing_keys:
            continue
        suggestions.append(AgentProposal(
            proposal_type=ProposalType.NODE_TYPE,
            node_ids=[],
            payload=payload,
            score=max(0.0, min(1.0, item.score)),
            origin=Origin.LLM,
            review_status=ReviewStatus.PENDING,
        ))
        existing_keys.add(key)
    return suggestions


def _accept_suggestion(repository: GraphRepository, proposal: AgentProposal, edited_payload: Dict[str, Any]) -> list[str]:
    payload = dict(proposal.payload)
    payload.update({key: value for key, value in edited_payload.items() if value is not None})
    proposal.payload = payload
    effects: list[str] = []
    suggestion_type = _suggestion_type(proposal)

    if suggestion_type == ProposalType.NODE_TITLE.value:
        node = repository.get_node(proposal.node_ids[0]) if proposal.node_ids else None
        if not node:
            raise ValueError("Suggestion node not found")
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValueError("Accepted title suggestion requires payload.title")
        node.title = title
        node.review_status = ReviewStatus.EDITED if edited_payload else ReviewStatus.ACCEPTED
        repository.update_node(node)
        effects.append(f"node_title:{node.id}")

    elif suggestion_type == ProposalType.NODE_TYPE.value:
        node = repository.get_node(proposal.node_ids[0]) if proposal.node_ids else None
        node_type = NodeType(str(payload.get("node_type")))
        if node:
            node.node_type = node_type
            node.review_status = ReviewStatus.EDITED if edited_payload else ReviewStatus.ACCEPTED
            repository.update_node(node)
            effects.append(f"node_type:{node.id}")
        else:
            content = str(payload.get("content") or "").strip()
            if not content:
                raise ValueError("Accepted candidate node suggestion requires payload.content")
            tags = payload.get("tags")
            source_text = str(payload.get("source_text") or "").strip() or None
            new_node = Node(
                content=content,
                node_type=node_type,
                title=str(payload.get("title") or _short_title(content)).strip() or None,
                tags=_clean_tags(tags if isinstance(tags, list) else []),
                source_text=source_text,
                provenance=SourceProvenance(
                    source_url=payload.get("source_url"),
                    source_type=payload.get("source_type"),
                    source_text=source_text,
                ) if (payload.get("source_url") or payload.get("source_type") or source_text) else None,
                metadata={
                    "suggested_by": payload.get("suggested_by") or proposal.origin.value,
                    "suggestion_id": proposal.id,
                    "source_fragment": payload.get("source_fragment"),
                    "review_source": "suggestion_accept",
                },
                trust_status=TrustStatus.CONFIRMED,
                origin=Origin.USER,
                review_status=ReviewStatus.ACCEPTED,
                user_comment=str(payload.get("user_comment") or "").strip() or None,
            )
            repository.add_node(new_node)
            proposal.node_ids.append(new_node.id)
            effects.append(f"node_created:{new_node.id}")

    elif suggestion_type == ProposalType.TAG.value:
        node = repository.get_node(proposal.node_ids[0]) if proposal.node_ids else None
        if not node:
            raise ValueError("Suggestion node not found")
        tag = str(payload.get("tag") or "").strip()
        if not tag:
            raise ValueError("Accepted tag suggestion requires payload.tag")
        if tag not in node.tags:
            node.tags.append(tag)
        node._sync_standard_metadata()
        repository.update_node(node)
        effects.append(f"tag:{node.id}:{tag}")

    elif suggestion_type in {ProposalType.MANUAL_EDGE.value, ProposalType.CONTRADICTION.value}:
        source_id = str(payload.get("source_id") or (proposal.node_ids[0] if proposal.node_ids else ""))
        target_id = str(payload.get("target_id") or (proposal.node_ids[1] if len(proposal.node_ids) > 1 else ""))
        if not repository.get_node(source_id) or not repository.get_node(target_id):
            raise ValueError("Accepted edge suggestion requires existing source and target nodes")
        edge_type = EdgeType(str(payload.get("edge_type") or EdgeType.USED_IN.value))
        edge = Edge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            edge_layer=EdgeLayer.MANUAL,
            weight=float(payload.get("weight") or proposal.score or 1.0),
            metadata={
                "suggested_by": payload.get("suggested_by") or proposal.origin.value,
                "suggestion_id": proposal.id,
                "review_source": "suggestion_accept",
            },
            trust_status=TrustStatus.CONFIRMED,
            origin=Origin.USER,
            review_status=ReviewStatus.ACCEPTED,
            user_comment=str(payload.get("user_comment") or "").strip() or None,
        )
        repository.add_edge(edge)
        proposal.edge_ids.append(edge.id)
        effects.append(f"manual_edge:{edge.id}")

    proposal.review_status = ReviewStatus.ACCEPTED
    repository.update_proposal(proposal)
    return effects


def _record_suggestion_feedback(
    repository: GraphRepository,
    proposal: AgentProposal,
    action: str,
    note: Optional[str] = None,
) -> list[str]:
    """Persist lightweight suggestion feedback on related nodes for personalization."""
    effects: list[str] = []
    for node_id in proposal.node_ids:
        node = repository.get_node(node_id)
        if not node:
            continue
        feedback_items = node.metadata.get("suggestion_feedback")
        if not isinstance(feedback_items, list):
            feedback_items = []
        feedback_items.append({
            "suggestion_id": proposal.id,
            "suggestion_type": _suggestion_type(proposal),
            "action": action,
            "note": note,
            "payload": proposal.payload,
        })
        node.metadata["suggestion_feedback"] = feedback_items[-20:]
        counts = node.metadata.get("suggestion_feedback_counts")
        if not isinstance(counts, dict):
            counts = {}
        key = f"{action}:{_suggestion_type(proposal)}"
        counts[key] = int(counts.get(key, 0)) + 1
        node.metadata["suggestion_feedback_counts"] = counts
        repository.update_node(node)
        effects.append(f"suggestion_feedback:{node.id}:{action}")
    proposal.payload["feedback_recorded"] = True
    return effects


def _accept_suggestion_by_id(
    repository: GraphRepository,
    suggestion_id: str,
    request: SuggestionDecisionRequest,
) -> tuple[AgentProposal, list[str]]:
    proposal = repository.get_proposal(suggestion_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if proposal.review_status != ReviewStatus.PENDING:
        raise HTTPException(status_code=400, detail="Suggestion is already reviewed")
    try:
        effects = _accept_suggestion(repository, proposal, request.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _record_suggestion_feedback(repository, proposal, "accept", note=request.note)
    if request.note:
        proposal.payload["user_comment"] = request.note.strip()
        repository.update_proposal(proposal)
    if repository.storage_path:
        repository.save()
    return proposal, effects


def _reject_suggestion_by_id(
    repository: GraphRepository,
    suggestion_id: str,
    request: SuggestionDecisionRequest,
) -> tuple[AgentProposal, list[str]]:
    proposal = repository.get_proposal(suggestion_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if proposal.review_status != ReviewStatus.PENDING:
        raise HTTPException(status_code=400, detail="Suggestion is already reviewed")
    if request.note:
        proposal.payload["rejection_note"] = request.note.strip()
    if request.payload:
        proposal.payload["rejection_feedback"] = request.payload
    proposal.review_status = ReviewStatus.REJECTED
    effects = _record_suggestion_feedback(repository, proposal, "reject", note=request.note)
    repository.update_proposal(proposal)
    if repository.storage_path:
        repository.save()
    return proposal, [f"suggestion_rejected:{proposal.id}", *effects]


def _defer_suggestion_by_id(
    repository: GraphRepository,
    suggestion_id: str,
    request: SuggestionDecisionRequest,
) -> tuple[AgentProposal, list[str]]:
    proposal = repository.get_proposal(suggestion_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if proposal.review_status != ReviewStatus.PENDING:
        raise HTTPException(status_code=400, detail="Suggestion is already reviewed")
    proposal.payload["review_deferred"] = True
    proposal.payload["review_deferred_at"] = utc_now().isoformat()
    if request.note:
        proposal.payload["defer_note"] = request.note.strip()
    if request.payload:
        proposal.payload["defer_feedback"] = request.payload
    repository.update_proposal(proposal)
    if repository.storage_path:
        repository.save()
    return proposal, [f"suggestion_deferred:{proposal.id}"]


def _clean_tags(tags: Optional[List[str]]) -> List[str]:
    """Normalize user-entered tags while preserving their order."""
    cleaned: List[str] = []
    seen = set()
    for tag in tags or []:
        value = str(tag).strip()
        if value and value not in seen:
            cleaned.append(value)
            seen.add(value)
    return cleaned


def _request_fields_set(request: BaseModel) -> set[str]:
    fields: Any = getattr(request, "model_fields_set", None)
    if fields is None:
        fields = getattr(request, "__fields_set__", set())
    if fields is None:
        fields = set()
    return {str(field) for field in fields}


def _model_to_dict(model: BaseModel, exclude_unset: bool = False) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=exclude_unset)
    return model.dict(exclude_unset=exclude_unset)


def _provenance_from_request(request: Optional[SourceProvenanceRequest]) -> Optional[SourceProvenance]:
    if request is None:
        return None
    return SourceProvenance(**_model_to_dict(request))


def _apply_provenance_patch(node: Node, request: SourceProvenanceRequest) -> None:
    current = node.provenance or SourceProvenance.from_metadata(
        node.metadata,
        source_text=node.source_text,
    ) or SourceProvenance()
    for key, value in _model_to_dict(request, exclude_unset=True).items():
        setattr(current, key, value)
    node.provenance = SourceProvenance(**current.to_dict())
    node.source_text = node.provenance.source_text
    node._sync_standard_metadata()


def _node_response(node: Node) -> NodeResponse:
    node._sync_standard_metadata()
    provenance_data = node.provenance.to_dict() if node.provenance else None
    return NodeResponse(
        id=node.id,
        node_type=node.node_type.value,
        content=node.content,
        source_text=node.source_text,
        strength=node.strength,
        created_at=node.created_at.isoformat(),
        metadata=node.metadata,
        trust_status=node.trust_status.value,
        origin=node.origin.value,
        review_status=node.review_status.value,
        user_comment=node.user_comment,
        title=node.title,
        tags=node.tags,
        provenance=provenance_data,
        source_id=provenance_data.get("source_id") if provenance_data else None,
        source_url=provenance_data.get("source_url") if provenance_data else None,
        document_title=provenance_data.get("document_title") if provenance_data else None,
    )


def _edge_response(edge: Edge) -> EdgeResponse:
    return EdgeResponse(
        id=edge.id,
        source_id=edge.source_id,
        target_id=edge.target_id,
        edge_type=edge.edge_type.value,
        edge_layer=edge.edge_layer.value,
        weight=edge.weight,
        metadata=edge.metadata,
        trust_status=edge.trust_status.value,
        origin=edge.origin.value,
        review_status=edge.review_status.value,
        user_comment=edge.user_comment,
    )


# === Endpoints ===

@app.get("/")
async def root():
    """Корневой endpoint."""
    return {
        "message": "Welcome to Exocortex API",
        "version": "0.1.0",
        "docs": "/docs",
        "app": "/app",
        "reader": "/reader",
        "graph": "/graph",
    }


@app.get("/app", response_class=HTMLResponse)
async def web_app():
    """Serve the built-in web inbox."""
    if not WEB_UI_PATH.exists():
        raise HTTPException(status_code=404, detail="Web UI not found")
    return HTMLResponse(WEB_UI_PATH.read_text(encoding="utf-8"))


@app.get("/reader", response_class=HTMLResponse)
async def web_reader():
    """Serve the built-in manual capture reader."""
    if not WEB_READER_PATH.exists():
        raise HTTPException(status_code=404, detail="Reader UI not found")
    return HTMLResponse(WEB_READER_PATH.read_text(encoding="utf-8"))


@app.get("/graph", response_class=HTMLResponse)
async def web_graph():
    """Serve the built-in graph visualization."""
    if not WEB_GRAPH_PATH.exists():
        raise HTTPException(status_code=404, detail="Graph UI not found")
    return HTMLResponse(WEB_GRAPH_PATH.read_text(encoding="utf-8"))


@app.post("/api/knowledge", response_model=AddKnowledgeResponse)
async def add_knowledge(request: AddKnowledgeRequest):
    """
    Добавить исходный текст и создать reviewable LLM-предложения.

    Старый extraction-flow больше не пишет узлы и связи в граф напрямую:
    пользователь должен принять предложения, прежде чем они станут частью
    подтверждённого смыслового слоя.
    """
    repository = get_repository()
    llm_service = get_llm_service()
    
    try:
        fragment = KnowledgeFragment(
            content=request.text,
            source_type=request.source_type,
            source_url=request.source_url,
        )
        suggestions = await _build_knowledge_suggestions(repository, fragment, llm_service)
        fragment.llm_status = getattr(llm_service, "last_status", "skipped")
        fragment.warnings = list(getattr(llm_service, "last_warnings", []) or [])
        fragment.errors = list(getattr(llm_service, "last_errors", []) or [])
        if fragment.llm_status == "succeeded" and not suggestions:
            fragment.warnings.append("LLM succeeded but produced no accepted review suggestions.")

        repository.add_fragment(fragment)
        for suggestion in suggestions:
            repository.add_proposal(suggestion)
        if repository.storage_path:
            repository.save()
        
        return AddKnowledgeResponse(
            fragment_id=fragment.id,
            nodes_created=0,
            edges_created=0,
            summary=fragment.content[:200] + "..." if len(fragment.content) > 200 else fragment.content,
            suggestions_created=len(suggestions),
            llm_status=fragment.llm_status,
            warnings=fragment.warnings,
            errors=fragment.errors,
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing knowledge: {str(e)}")


@app.post("/api/sources", response_model=AddKnowledgeResponse)
async def ingest_source(request: IngestSourceRequest):
    """Импортировать внешний источник: прямой текст или текстовый URL."""
    if not request.text and not request.url:
        raise HTTPException(status_code=400, detail="Provide either text or url")

    repository = get_repository()
    ingestor = ExternalSourceIngestor(repository, llm_service=get_llm_service())
    try:
        if request.url:
            fragment = await ingestor.ingest_url(request.url, source_type=request.source_type)
        else:
            fragment = await ingestor.ingest_text(
                text=request.text or "",
                source_type=request.source_type,
            )
        return AddKnowledgeResponse(
            fragment_id=fragment.id,
            nodes_created=len(fragment.extracted_nodes),
            edges_created=len([
                edge for edge in repository.get_all_edges()
                if edge.metadata.get("source_fragment") == fragment.id
            ]),
            summary=fragment.content[:200] + "..." if len(fragment.content) > 200 else fragment.content,
            llm_status=fragment.llm_status,
            warnings=fragment.warnings,
            errors=fragment.errors,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error ingesting source: {str(exc)}")


@app.post("/api/manual-fragments", response_model=ManualFragmentResponse)
async def add_manual_fragment(request: ManualFragmentRequest):
    """Сохранить выделенный пользователем фрагмент без LLM-обработки."""
    try:
        has_source_text = bool(request.source_text and request.source_text.strip())
        node_type = NodeType(request.node_type) if request.node_type else (
            NodeType.IDEA if has_source_text else NodeType.QUOTE
        )
        if node_type == NodeType.SOURCE:
            raise ValueError("reader/capture cannot create source nodes")
        provenance_metadata = {
            "source_id": request.source_id,
            "author": request.author,
            "published_at": request.published_at,
            "added_at": request.added_at,
            "position": request.position,
            "offset_start": request.offset_start,
            "offset_end": request.offset_end,
            "source_user_comment": request.source_user_comment,
        }
        metadata = dict(request.metadata)
        metadata.update({key: value for key, value in provenance_metadata.items() if value is not None})
        fragment, node = store_manual_fragment(
            repository=get_repository(),
            text=request.text,
            source_type=request.source_type,
            source_url=request.source_url,
            document_title=request.document_title,
            source_text=request.source_text,
            node_type=node_type,
            tags=_clean_tags(request.tags),
            metadata=metadata,
        )
    except ValueError as exc:
        message = str(exc)
        if "is not a valid NodeType" in message:
            message = f"Invalid node_type: {request.node_type}"
        raise HTTPException(status_code=400, detail=message)

    return ManualFragmentResponse(
        fragment_id=fragment.id,
        node_id=node.id,
        node_type=node.node_type.value,
        nodes_created=1,
        edges_created=0,
        summary=node.content[:200] + "..." if len(node.content) > 200 else node.content,
    )


@app.post("/api/nodes", response_model=NodeResponse)
async def create_node(request: NodeCreateRequest):
    """Создать пользовательский узел графа вручную."""
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="content cannot be empty")

    try:
        node_type = NodeType(request.node_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid node_type: {request.node_type}")

    node = Node(
        content=content,
        node_type=node_type,
        source_text=request.source_text.strip() if request.source_text else None,
        metadata=dict(request.metadata),
        provenance=_provenance_from_request(request.provenance),
        trust_status=TrustStatus.CONFIRMED,
        origin=Origin.USER,
        review_status=ReviewStatus.ACCEPTED,
        user_comment=request.user_comment,
        title=request.title,
        tags=_clean_tags(request.tags),
    )

    repository = get_repository()
    repository.add_node(node)
    if repository.storage_path:
        repository.save()
    return _node_response(node)


@app.patch("/api/nodes/{node_id}", response_model=NodeResponse)
async def update_node(node_id: str, request: NodePatchRequest):
    """Отредактировать существующий узел графа."""
    repository = get_repository()
    node = repository.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    fields_set = _request_fields_set(request)

    if "content" in fields_set:
        content = (request.content or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="content cannot be empty")
        node.content = content
    if request.node_type is not None:
        try:
            node.node_type = NodeType(request.node_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid node_type: {request.node_type}")
    if "source_text" in fields_set:
        node.source_text = request.source_text.strip() if request.source_text else None
        if node.provenance:
            node.provenance.source_text = node.source_text
    if "title" in fields_set:
        node.title = request.title.strip() if request.title else None
    if "tags" in fields_set:
        node.tags = _clean_tags(request.tags)
    if "user_comment" in fields_set:
        node.user_comment = request.user_comment.strip() if request.user_comment else None
    if request.trust_status is not None:
        try:
            node.trust_status = TrustStatus(request.trust_status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid trust_status: {request.trust_status}")
    if request.origin is not None:
        try:
            node.origin = Origin(request.origin)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid origin: {request.origin}")
    if request.review_status is not None:
        try:
            node.review_status = ReviewStatus(request.review_status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid review_status: {request.review_status}")
    if request.metadata is not None:
        node.metadata = dict(request.metadata)
    if "provenance" in fields_set:
        if request.provenance is None:
            node.provenance = None
            node.source_text = None
            node.metadata.pop("provenance", None)
            for key in (
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
                "source_user_comment",
            ):
                node.metadata.pop(key, None)
        else:
            _apply_provenance_patch(node, request.provenance)

    if not repository.update_node(node):
        raise HTTPException(status_code=404, detail="Node not found")
    if repository.storage_path:
        repository.save()
    return _node_response(node)


@app.patch("/api/nodes/{node_id}/provenance", response_model=NodeResponse)
async def update_node_provenance(node_id: str, request: SourceProvenanceRequest):
    """Создать или обновить provenance-привязку существующего узла."""
    repository = get_repository()
    node = repository.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    _apply_provenance_patch(node, request)
    if not repository.update_node(node):
        raise HTTPException(status_code=404, detail="Node not found")
    if repository.storage_path:
        repository.save()
    return _node_response(node)


@app.post("/api/nodes/{node_id}/suggestions", response_model=SuggestionGenerateResponse)
async def generate_node_suggestions(node_id: str):
    """Сгенерировать reviewable предложения для существующего узла."""
    repository = get_repository()
    node = repository.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    suggestions = await _build_node_suggestions_with_llm(repository, node)
    for suggestion in suggestions:
        repository.add_proposal(suggestion)
    if suggestions and repository.storage_path:
        repository.save()
    return SuggestionGenerateResponse(
        node_id=node_id,
        suggestions_generated=len(suggestions),
        suggestions=[_suggestion_response(suggestion) for suggestion in suggestions],
    )


@app.get("/api/suggestions", response_model=SuggestionListResponse)
async def get_suggestions(review_status: Optional[str] = None, limit: int = 100):
    """Получить очередь предложений с опциональной фильтрацией по review_status."""
    repository = get_repository()
    try:
        status = ReviewStatus(review_status) if review_status else None
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid review_status: {review_status}")
    suggestions = repository.get_all_proposals(review_status=status)[:limit]
    return SuggestionListResponse(
        suggestions=[_suggestion_response(suggestion) for suggestion in suggestions],
        total=len(suggestions),
    )


@app.get("/api/review", response_model=ReviewListResponse)
async def get_review_queue(
    include_reacted: bool = False,
    include_deferred: bool = False,
    limit: int = 100,
):
    """Получить единую очередь review items из suggestions и agent insights."""
    repository = get_repository()
    review_items: List[ReviewItemResponse] = []

    for suggestion in repository.get_all_proposals():
        is_deferred = _is_deferred_suggestion(suggestion)
        is_pending = suggestion.review_status == ReviewStatus.PENDING
        if not include_reacted and not is_pending:
            continue
        if is_deferred and not include_deferred:
            continue
        review_items.append(_review_item_from_suggestion(repository, suggestion))

    inbox_items = get_personalization_service().list_inbox(
        include_reacted=True,
        limit=max(limit, 100),
    )
    for item in inbox_items:
        is_deferred = item.feedback is not None and item.feedback.action.value == "defer"
        if item.feedback and not include_reacted:
            continue
        if is_deferred and not include_deferred:
            continue
        review_items.append(_review_item_from_inbox_item(item))

    review_items.sort(key=lambda item: item.created_at, reverse=True)
    return ReviewListResponse(items=review_items[:limit], total=min(len(review_items), limit))


@app.post("/api/suggestions/{suggestion_id}/accept", response_model=SuggestionResponse)
async def accept_suggestion(suggestion_id: str, request: SuggestionDecisionRequest):
    """Принять предложение и применить его эффект к ручному графу, если он есть."""
    repository = get_repository()
    proposal, effects = _accept_suggestion_by_id(repository, suggestion_id, request)
    return _suggestion_response(proposal, effects=effects)


@app.post("/api/suggestions/{suggestion_id}/reject", response_model=SuggestionResponse)
async def reject_suggestion(suggestion_id: str, request: SuggestionDecisionRequest):
    """Отклонить предложение и сохранить feedback в payload."""
    repository = get_repository()
    proposal, effects = _reject_suggestion_by_id(repository, suggestion_id, request)
    return _suggestion_response(proposal, effects=effects)


@app.post("/api/suggestions/{suggestion_id}/defer", response_model=SuggestionResponse)
async def defer_suggestion(suggestion_id: str, request: SuggestionDecisionRequest):
    """Отложить предложение без применения и без окончательного reject."""
    repository = get_repository()
    proposal, effects = _defer_suggestion_by_id(repository, suggestion_id, request)
    return _suggestion_response(proposal, effects=effects)


@app.post("/api/review/suggestions/{suggestion_id}/accept", response_model=SuggestionResponse)
async def review_accept_suggestion(suggestion_id: str, request: SuggestionDecisionRequest):
    """Review alias для edit-and-accept suggestion."""
    repository = get_repository()
    proposal, effects = _accept_suggestion_by_id(repository, suggestion_id, request)
    return _suggestion_response(proposal, effects=effects)


@app.post("/api/review/suggestions/{suggestion_id}/reject", response_model=SuggestionResponse)
async def review_reject_suggestion(suggestion_id: str, request: SuggestionDecisionRequest):
    """Review alias для reject suggestion."""
    repository = get_repository()
    proposal, effects = _reject_suggestion_by_id(repository, suggestion_id, request)
    return _suggestion_response(proposal, effects=effects)


@app.post("/api/review/suggestions/{suggestion_id}/defer", response_model=SuggestionResponse)
async def review_defer_suggestion(suggestion_id: str, request: SuggestionDecisionRequest):
    """Review alias для defer suggestion."""
    repository = get_repository()
    proposal, effects = _defer_suggestion_by_id(repository, suggestion_id, request)
    return _suggestion_response(proposal, effects=effects)


@app.post("/api/edges", response_model=EdgeResponse)
async def create_edge(request: EdgeCreateRequest):
    """Создать пользовательскую смысловую связь вручную."""
    repository = get_repository()
    if not repository.get_node(request.source_id):
        raise HTTPException(status_code=404, detail="Source node not found")
    if not repository.get_node(request.target_id):
        raise HTTPException(status_code=404, detail="Target node not found")

    try:
        edge_type = EdgeType(request.edge_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid edge_type: {request.edge_type}")
    if request.edge_layer and request.edge_layer != EdgeLayer.MANUAL.value:
        raise HTTPException(status_code=400, detail="Manual edge endpoint only creates manual edges")

    edge = Edge(
        source_id=request.source_id,
        target_id=request.target_id,
        edge_type=edge_type,
        edge_layer=EdgeLayer.MANUAL,
        weight=request.weight,
        metadata=dict(request.metadata),
        trust_status=TrustStatus.CONFIRMED,
        origin=Origin.USER,
        review_status=ReviewStatus.ACCEPTED,
        user_comment=request.user_comment,
    )
    repository.add_edge(edge)
    if repository.storage_path:
        repository.save()
    return _edge_response(edge)


@app.patch("/api/edges/{edge_id}", response_model=EdgeResponse)
async def update_edge(edge_id: str, request: EdgePatchRequest):
    """Отредактировать существующую связь графа."""
    repository = get_repository()
    edge = repository.get_edge(edge_id)
    if not edge:
        raise HTTPException(status_code=404, detail="Edge not found")

    fields_set = _request_fields_set(request)

    if request.source_id is not None:
        if not repository.get_node(request.source_id):
            raise HTTPException(status_code=404, detail="Source node not found")
        edge.source_id = request.source_id
    if request.target_id is not None:
        if not repository.get_node(request.target_id):
            raise HTTPException(status_code=404, detail="Target node not found")
        edge.target_id = request.target_id
    if request.edge_type is not None:
        try:
            edge.edge_type = EdgeType(request.edge_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid edge_type: {request.edge_type}")
    if request.edge_layer is not None:
        try:
            edge.edge_layer = EdgeLayer(request.edge_layer)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid edge_layer: {request.edge_layer}")
    if request.weight is not None:
        edge.weight = request.weight
    if "user_comment" in fields_set:
        edge.user_comment = request.user_comment.strip() if request.user_comment else None
    if request.trust_status is not None:
        try:
            edge.trust_status = TrustStatus(request.trust_status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid trust_status: {request.trust_status}")
    if request.origin is not None:
        try:
            edge.origin = Origin(request.origin)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid origin: {request.origin}")
    if request.review_status is not None:
        try:
            edge.review_status = ReviewStatus(request.review_status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid review_status: {request.review_status}")
    if request.metadata is not None:
        edge.metadata = dict(request.metadata)

    if not repository.update_edge(edge):
        raise HTTPException(status_code=404, detail="Edge not found")
    if repository.storage_path:
        repository.save()
    return _edge_response(edge)


@app.get("/api/nodes", response_model=NodeListResponse)
async def get_nodes(
    node_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100
):
    """
    Получить список узлов.
    
    Поддерживает фильтрацию по типу и поиск по содержимому.
    """
    repository = get_repository()
    
    if search:
        nodes = repository.search_nodes(search)[:limit]
    elif node_type:
        try:
            from app.core.models import NodeType
            node_type_enum = NodeType(node_type)
            nodes = repository.get_nodes_by_type(node_type_enum)[:limit]
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid node_type: {node_type}")
    else:
        nodes = repository.get_all_nodes()[:limit]
    
    return NodeListResponse(
        nodes=[_node_response(n) for n in nodes],
        total=len(nodes)
    )


@app.get("/api/nodes/{node_id}", response_model=NodeResponse)
async def get_node(node_id: str):
    """Получить конкретный узел по ID."""
    repository = get_repository()
    node = repository.get_node(node_id)
    
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    return _node_response(node)


@app.get("/api/edges", response_model=EdgeListResponse)
async def get_edges(
    edge_type: Optional[str] = None,
    edge_layer: Optional[str] = None,
    limit: int = 100
):
    """
    Получить список связей.
    
    Поддерживает фильтрацию по типу связи и слою.
    """
    repository = get_repository()

    edge_type_enum = None
    if edge_type:
        try:
            edge_type_enum = EdgeType(edge_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid edge_type: {edge_type}")

    edge_layer_enum = None
    if edge_layer:
        try:
            edge_layer_enum = EdgeLayer(edge_layer)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid edge_layer: {edge_layer}")

    edges = repository.get_all_edges(edge_layer=edge_layer_enum)
    if edge_type_enum:
        edges = [edge for edge in edges if edge.edge_type == edge_type_enum]
    edges = edges[:limit]
    
    return EdgeListResponse(
        edges=[_edge_response(e) for e in edges],
        total=len(edges)
    )


@app.get("/api/nodes/{node_id}/neighbors", response_model=NodeListResponse)
async def get_node_neighbors(node_id: str, radius: int = 1):
    """Получить соседние узлы для данного узла."""
    repository = get_repository()
    
    if not repository.get_node(node_id):
        raise HTTPException(status_code=404, detail="Node not found")
    
    neighbors = repository.get_neighbors(node_id, radius=radius)
    
    return NodeListResponse(
        nodes=[_node_response(n) for n in neighbors],
        total=len(neighbors)
    )


@app.get("/api/stats", response_model=GraphStatsResponse)
async def get_stats():
    """Получить статистику графа знаний."""
    repository = get_repository()
    stats = repository.get_stats()
    return GraphStatsResponse(**stats)


@app.get("/api/fragments", response_model=List[Dict[str, Any]])
async def get_fragments(limit: int = 50):
    """Получить список исходных фрагментов знаний."""
    repository = get_repository()
    fragments = repository.get_all_fragments()[:limit]
    
    return [
        {
            'id': f.id,
            'content': f.content[:200] + "..." if len(f.content) > 200 else f.content,
            'source_type': f.source_type,
            'source_url': f.source_url,
            'extracted_nodes_count': len(f.extracted_nodes),
            'created_at': f.created_at.isoformat()
        }
        for f in fragments
    ]


@app.post("/api/agent/analyze", response_model=DigestResponse)
async def run_agent_analysis():
    """Запустить проактивный анализ графа и сохранить дайджест."""
    digest = await get_agent().analyze(save=True)
    return _digest_response(digest)


@app.get("/api/digest", response_model=DigestResponse)
async def get_latest_digest():
    """Получить последний сохранённый дайджест."""
    digest = get_agent().get_latest_digest()
    if digest is None:
        raise HTTPException(status_code=404, detail="Digest not found")
    return _digest_response(digest)


@app.get("/api/insights", response_model=List[InsightResponse])
async def get_latest_insights():
    """Получить инсайты из последнего сохранённого дайджеста."""
    digest = get_agent().get_latest_digest()
    if digest is None:
        return []
    return [_insight_response(insight) for insight in digest.insights]


@app.get("/api/inbox", response_model=List[InboxItemResponse])
async def get_inbox(include_reacted: bool = True, limit: int = 50):
    """Получить inbox инсайтов со статусом пользовательской реакции."""
    items = get_personalization_service().list_inbox(
        include_reacted=include_reacted,
        limit=limit,
    )
    return [_inbox_item_response(item) for item in items]


@app.post("/api/insights/{insight_id}/feedback", response_model=InsightFeedbackResponse)
async def react_to_insight(insight_id: str, request: InsightFeedbackRequest):
    """Сохранить реакцию пользователя на инсайт и обновить граф."""
    try:
        feedback = get_personalization_service().react_to_insight(
            insight_id=insight_id,
            action=request.action,
            note=request.note,
            edge_type=request.edge_type,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message.startswith("Insight not found") else 400
        raise HTTPException(status_code=status_code, detail=message)
    return _feedback_response(feedback)


@app.post("/api/review/insights/{insight_id}/react", response_model=InsightFeedbackResponse)
async def review_react_to_insight(insight_id: str, request: InsightFeedbackRequest):
    """Review alias для реакции на agent insight."""
    return await react_to_insight(insight_id, request)


@app.post("/api/review/insights/{insight_id}/defer", response_model=InsightFeedbackResponse)
async def review_defer_insight(insight_id: str, request: SuggestionDecisionRequest):
    """Отложить agent insight без изменения смыслового графа."""
    defer_request = InsightFeedbackRequest(
        action="defer",
        note=request.note,
    )
    return await react_to_insight(insight_id, defer_request)


@app.get("/api/personalization", response_model=InterestProfileResponse)
async def get_personalization_profile():
    """Получить базовую статистику взаимодействий и интересов."""
    return InterestProfileResponse(**get_personalization_service().build_interest_profile())


@app.delete("/api/nodes/{node_id}")
async def delete_node(node_id: str):
    """Удалить узел из графа."""
    repository = get_repository()
    
    if not repository.delete_node(node_id):
        raise HTTPException(status_code=404, detail="Node not found")
    
    # Сохраняем изменения
    if repository.storage_path:
        repository.save()
    
    return {"message": "Node deleted", "node_id": node_id}


@app.delete("/api/edges/{edge_id}")
async def delete_edge(edge_id: str):
    """Удалить связь из графа."""
    repository = get_repository()
    
    if not repository.delete_edge(edge_id):
        raise HTTPException(status_code=404, detail="Edge not found")
    
    # Сохраняем изменения
    if repository.storage_path:
        repository.save()
    
    return {"message": "Edge deleted", "edge_id": edge_id}
