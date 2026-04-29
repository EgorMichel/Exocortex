"""
REST API для Exocortex.

Предоставляет endpoints для:
- Добавления знаний (текст, заметки)
- Просмотра графа знаний
- Получения статистики
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import asyncio

from app.core.repository import GraphRepository
from app.core.models import KnowledgeFragment, Node, Edge
from app.llm.extraction import extract_and_store, LLMService


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


# === Создание приложения FastAPI ===

app = FastAPI(
    title="Exocortex API",
    description="API для системы управления персональными знаниями",
    version="0.1.0"
)

# Глобальный репозиторий (в будущем можно вынести в dependency injection)
_repository: Optional[GraphRepository] = None
_llm_service: Optional[LLMService] = None


def get_repository() -> GraphRepository:
    """Получить или создать репозиторий."""
    global _repository
    if _repository is None:
        _repository = GraphRepository(storage_path="data/knowledge_graph")
    return _repository


def get_llm_service() -> LLMService:
    """Получить или создать LLM сервис."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


# === Endpoints ===

@app.get("/")
async def root():
    """Корневой endpoint."""
    return {
        "message": "Welcome to Exocortex API",
        "version": "0.1.0",
        "docs": "/docs"
    }


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


# === Lifecycle events ===

@app.on_event("startup")
async def startup_event():
    """Инициализация при запуске приложения."""
    # Инициализируем репозиторий
    repository = get_repository()
    print(f"Exocortex started. Graph loaded with {len(repository.get_all_nodes())} nodes.")


@app.on_event("shutdown")
async def shutdown_event():
    """Очистка при остановке приложения."""
    repository = get_repository()
    if repository.storage_path:
        repository.save()
        print("Graph saved to disk.")
