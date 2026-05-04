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
from app.core.repository import GraphRepository
from app.llm.extraction import extract_and_store, LLMService
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


class IngestSourceRequest(BaseModel):
    """Запрос на импорт внешнего текстового источника."""
    text: Optional[str] = Field(default=None, description="Текст для импорта")
    url: Optional[str] = Field(default=None, description="URL текстового источника")
    source_type: str = Field(default="external", description="Тип источника")


class ManualFragmentRequest(BaseModel):
    """Запрос на ручное сохранение выделенного фрагмента."""
    text: str = Field(..., description="Выделенный текст", min_length=1)
    source_type: str = Field(default="manual_selection", description="Тип источника")
    source_url: Optional[str] = Field(default=None, description="URL или путь источника")
    document_title: Optional[str] = Field(default=None, description="Название документа")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Метаданные выделения")


class ManualFragmentResponse(BaseModel):
    """Ответ после ручного сохранения фрагмента."""
    fragment_id: str
    node_id: str
    node_type: str
    nodes_created: int
    edges_created: int
    summary: str


class NodeResponse(BaseModel):
    """Представление узла в API."""
    id: str
    node_type: str
    content: str
    strength: float
    created_at: str
    metadata: Dict[str, Any]


class EdgeResponse(BaseModel):
    """Представление связи в API."""
    id: str
    source_id: str
    target_id: str
    edge_type: str
    weight: float
    metadata: Dict[str, Any]


class GraphStatsResponse(BaseModel):
    """Статистика графа."""
    total_nodes: int
    total_edges: int
    total_fragments: int
    node_types: Dict[str, int]
    edge_types: Dict[str, int]
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


@app.post("/api/knowledge", response_model=AddKnowledgeResponse)
async def add_knowledge(request: AddKnowledgeRequest):
    """
    Добавить новое знание в систему.
    
    Текст будет обработан LLM для извлечения сущностей и связей,
    которые затем будут сохранены в граф знаний.
    """
    repository = get_repository()
    llm_service = get_llm_service()
    
    try:
        # Извлекаем знания и сохраняем в граф
        fragment = await extract_and_store(
            text=request.text,
            repository=repository,
            source_type=request.source_type,
            source_url=request.source_url,
            llm_service=llm_service
        )
        
        return AddKnowledgeResponse(
            fragment_id=fragment.id,
            nodes_created=len(fragment.extracted_nodes),
            edges_created=len([e for e in repository.get_all_edges() 
                             if e.metadata.get('source_fragment') == fragment.id]),
            summary=fragment.content[:200] + "..." if len(fragment.content) > 200 else fragment.content
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
            fragment = await ingestor.ingest_url(request.url)
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
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error ingesting source: {str(exc)}")


@app.post("/api/manual-fragments", response_model=ManualFragmentResponse)
async def add_manual_fragment(request: ManualFragmentRequest):
    """Сохранить выделенный пользователем фрагмент без LLM-обработки."""
    try:
        fragment, node = store_manual_fragment(
            repository=get_repository(),
            text=request.text,
            source_type=request.source_type,
            source_url=request.source_url,
            document_title=request.document_title,
            metadata=request.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ManualFragmentResponse(
        fragment_id=fragment.id,
        node_id=node.id,
        node_type=node.node_type.value,
        nodes_created=1,
        edges_created=0,
        summary=fragment.content[:200] + "..." if len(fragment.content) > 200 else fragment.content,
    )


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
        nodes=[
            NodeResponse(
                id=n.id,
                node_type=n.node_type.value,
                content=n.content,
                strength=n.strength,
                created_at=n.created_at.isoformat(),
                metadata=n.metadata
            )
            for n in nodes
        ],
        total=len(nodes)
    )


@app.get("/api/nodes/{node_id}", response_model=NodeResponse)
async def get_node(node_id: str):
    """Получить конкретный узел по ID."""
    repository = get_repository()
    node = repository.get_node(node_id)
    
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    return NodeResponse(
        id=node.id,
        node_type=node.node_type.value,
        content=node.content,
        strength=node.strength,
        created_at=node.created_at.isoformat(),
        metadata=node.metadata
    )


@app.get("/api/edges", response_model=EdgeListResponse)
async def get_edges(
    edge_type: Optional[str] = None,
    limit: int = 100
):
    """
    Получить список связей.
    
    Поддерживает фильтрацию по типу связи.
    """
    repository = get_repository()
    
    if edge_type == "contradicts":
        edges = repository.get_contradictions()[:limit]
    else:
        edges = repository.get_all_edges()[:limit]
    
    return EdgeListResponse(
        edges=[
            EdgeResponse(
                id=e.id,
                source_id=e.source_id,
                target_id=e.target_id,
                edge_type=e.edge_type.value,
                weight=e.weight,
                metadata=e.metadata
            )
            for e in edges
        ],
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
        nodes=[
            NodeResponse(
                id=n.id,
                node_type=n.node_type.value,
                content=n.content,
                strength=n.strength,
                created_at=n.created_at.isoformat(),
                metadata=n.metadata
            )
            for n in neighbors
        ],
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
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message.startswith("Insight not found") else 400
        raise HTTPException(status_code=status_code, detail=message)
    return _feedback_response(feedback)


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
