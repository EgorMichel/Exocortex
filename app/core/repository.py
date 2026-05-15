"""
Репозиторий для операций с графом знаний.

Использует NetworkX для хранения графа в памяти (для MVP).
В будущем может быть заменён на Neo4j или другую графовую БД.
"""

import ast
import json
import os
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Optional, List, Dict, Any, Literal, Protocol
import xml.etree.ElementTree as ET
import networkx as nx

from app.core.models import (
    AgentProposal,
    Edge,
    EdgeLayer,
    EdgeType,
    KnowledgeFragment,
    Node,
    NodeType,
    ReviewStatus,
)


SCHEMA_VERSION = 1
Direction = Literal["out", "in", "both"]


class GraphStore(Protocol):
    """Storage adapter protocol for graph persistence."""

    def save(self, repository: "GraphRepository") -> None:
        ...

    def load(self, repository: "GraphRepository") -> bool:
        ...


class NetworkXFileGraphStore:
    """Versioned JSON canonical storage with GEXF export compatibility."""

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)

    @property
    def graph_json_path(self) -> Path:
        return self.storage_path.with_suffix(".graph.json")

    @property
    def gexf_path(self) -> Path:
        return self.storage_path.with_suffix(".gexf")

    @property
    def fragments_path(self) -> Path:
        return self.storage_path.with_suffix(".fragments.json")

    @property
    def proposals_path(self) -> Path:
        return self.storage_path.with_suffix(".proposals.json")

    def save(self, repository: "GraphRepository") -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self._file_lock():
            payload = repository.to_storage_dict()
            self._atomic_write_json(self.graph_json_path, payload)
            self._atomic_write_json(
                self.fragments_path,
                [fragment.to_dict() for fragment in repository.fragments.values()],
            )
            self._atomic_write_json(
                self.proposals_path,
                [proposal.to_dict() for proposal in repository.proposals.values()],
            )
            nx.write_gexf(repository.graph, self.gexf_path)

    def load(self, repository: "GraphRepository") -> bool:
        with self._file_lock():
            if self.graph_json_path.exists():
                with open(self.graph_json_path, "r", encoding="utf-8") as file:
                    repository.load_storage_dict(json.load(file))
                self._load_sidecars(repository)
                return True
            if self.gexf_path.exists():
                repository.load_legacy_gexf(self.gexf_path)
                self._load_sidecars(repository)
                return True
        return False

    def _load_sidecars(self, repository: "GraphRepository") -> None:
        if self.fragments_path.exists():
            with open(self.fragments_path, "r", encoding="utf-8") as file:
                fragments_data = json.load(file)
            repository.fragments = {
                fragment['id']: KnowledgeFragment.from_dict(fragment)
                for fragment in fragments_data
            }
        if self.proposals_path.exists():
            with open(self.proposals_path, "r", encoding="utf-8") as file:
                proposals_data = json.load(file)
            repository.proposals = {
                proposal['id']: AgentProposal.from_dict(proposal)
                for proposal in proposals_data
            }

    def _atomic_write_json(self, path: Path, payload: Any) -> None:
        tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)

    @contextmanager
    def _file_lock(self):
        lock_path = self.storage_path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+b") as file:
            try:
                try:
                    import msvcrt

                    msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
                    unlock = lambda: msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                except ImportError:
                    import fcntl

                    fcntl.flock(file.fileno(), fcntl.LOCK_EX)
                    unlock = lambda: fcntl.flock(file.fileno(), fcntl.LOCK_UN)
                yield
            finally:
                unlock()


class GraphRepository:
    """
    Репозиторий для управления графом знаний.
    
    Поддерживает:
    - CRUD операции для узлов и связей
    - Сохранение/загрузку графа на диск
    - Поиск и фильтрацию узлов
    - Получение связанных узлов
    """
    
    def __init__(self, storage_path: Optional[str] = None, store: Optional[GraphStore] = None):
        """
        Инициализация репозитория.
        
        Args:
            storage_path: Путь к файлу для сохранения графа.
                         Если None, граф хранится только в памяти.
        """
        self.graph = nx.MultiDiGraph()  # MultiDiGraph позволяет несколько связей между узлами
        self.storage_path = Path(storage_path) if storage_path else None
        self.fragments: Dict[str, KnowledgeFragment] = {}
        self.proposals: Dict[str, AgentProposal] = {}
        self.store = store or (NetworkXFileGraphStore(self.storage_path) if self.storage_path else None)
        
        if self.store:
            self.load()
    
    # === Операции с узлами ===
    
    def add_node(self, node: Node) -> None:
        """Добавить узел в граф."""
        self.graph.add_node(
            node.id,
            **node.to_dict()
        )
    
    def get_node(self, node_id: str) -> Optional[Node]:
        """Получить узел по ID."""
        if node_id not in self.graph:
            return None
        
        return self._node_from_graph_data(node_id)
    
    def update_node(self, node: Node) -> bool:
        """
        Обновить существующий узел.
        
        Returns:
            True если узел существовал и был обновлён, False иначе.
        """
        if node.id not in self.graph:
            return False
        
        self.graph.nodes[node.id].update(node.to_dict())
        return True
    
    def delete_node(self, node_id: str) -> bool:
        """
        Удалить узел из графа.
        
        Returns:
            True если узел существовал и был удалён, False иначе.
        """
        if node_id not in self.graph:
            return False
        
        self.graph.remove_node(node_id)
        return True
    
    def get_all_nodes(self) -> List[Node]:
        """Получить все узлы графа."""
        return [
            self._node_from_graph_data(node_id)
            for node_id in self.graph.nodes()
        ]
    
    def get_nodes_by_type(self, node_type: NodeType) -> List[Node]:
        """Получить узлы определённого типа."""
        return [
            node for node in self.get_all_nodes()
            if node.node_type == node_type
        ]
    
    def search_nodes(self, query: str) -> List[Node]:
        """
        Поиск узлов по содержимому (простой текстовый поиск).
        
        В будущем может быть заменён на семантический поиск через эмбеддинги.
        """
        query_lower = query.lower()
        return [
            node for node in self.get_all_nodes()
            if query_lower in node.content.lower()
        ]
    
    def get_forgotten_nodes(self, threshold: float = 0.3) -> List[Node]:
        """Получить узлы, которые считаются «забытыми»."""
        return [
            node for node in self.get_all_nodes()
            if node.is_forgotten(threshold)
        ]
    
    # === Операции со связями ===
    
    def add_edge(self, edge: Edge) -> None:
        """Добавить связь в граф, не позволяя NetworkX создать пустые узлы."""
        if edge.source_id not in self.graph:
            raise ValueError(f"Source node does not exist: {edge.source_id}")
        if edge.target_id not in self.graph:
            raise ValueError(f"Target node does not exist: {edge.target_id}")
        self.graph.add_edge(
            edge.source_id,
            edge.target_id,
            key=edge.id,
            **edge.to_dict()
        )

    def update_edge(self, edge: Edge) -> bool:
        """
        Обновить существующую связь.

        Если у связи изменились source_id или target_id, ребро переносится между
        новыми узлами с сохранением стабильного id.
        """
        for source, target, key, _ in self.graph.edges(keys=True, data=True):
            if key == edge.id:
                if edge.source_id not in self.graph or edge.target_id not in self.graph:
                    return False
                if source != edge.source_id or target != edge.target_id:
                    self.graph.remove_edge(source, target, key=key)
                    self.graph.add_edge(edge.source_id, edge.target_id, key=edge.id, **edge.to_dict())
                else:
                    self.graph.edges[source, target, key].update(edge.to_dict())
                return True
        return False
    
    def get_edge(self, edge_id: str) -> Optional[Edge]:
        """Получить связь по ID."""
        for source, target, key, data in self.graph.edges(keys=True, data=True):
            if key == edge_id:
                return Edge.from_dict(data)
        return None
    
    def get_edges_between(
        self,
        source_id: str,
        target_id: str,
        edge_layer: Optional[EdgeLayer | str] = None,
    ) -> List[Edge]:
        """Получить все связи между двумя узлами."""
        if source_id not in self.graph or target_id not in self.graph:
            return []
        
        edges = []
        layer = self._coerce_edge_layer(edge_layer)
        for key, data in self.graph.get_edge_data(source_id, target_id, default={}).items():
            if key != 'key':  # Пропускаем служебные ключи
                edge = Edge.from_dict(data)
                if layer is None or edge.edge_layer == layer:
                    edges.append(edge)
        
        return edges
    
    def delete_edge(self, edge_id: str) -> bool:
        """
        Удалить связь по ID.
        
        Returns:
            True если связь существовала и была удалена, False иначе.
        """
        for source, target, key, _ in self.graph.edges(keys=True, data=True):
            if key == edge_id:
                self.graph.remove_edge(source, target, key=key)
                return True
        return False
    
    def get_all_edges(self, edge_layer: Optional[EdgeLayer | str] = None) -> List[Edge]:
        """Получить все связи графа."""
        layer = self._coerce_edge_layer(edge_layer)
        edges = []
        for source, target, key, data in self.graph.edges(keys=True, data=True):
            edge = Edge.from_dict(data)
            if layer is None or edge.edge_layer == layer:
                edges.append(edge)
        return edges
    
    def get_contradictions(self) -> List[Edge]:
        """Получить все связи типа «противоречие»."""
        return [
            edge for edge in self.get_all_edges()
            if edge.edge_type == EdgeType.CONTRADICTS
        ]
    
    # === Навигация по графу ===
    
    def get_neighbors(
        self,
        node_id: str,
        radius: int = 1,
        direction: Direction = "both",
        edge_layer: Optional[EdgeLayer | str] = None,
    ) -> List[Node]:
        """
        Получить соседние узлы.
        
        Args:
            node_id: ID центрального узла
            radius: Количество шагов от узла (по умолчанию 1)
        """
        if node_id not in self.graph:
            return []
        traversal_graph = self._filtered_traversal_graph(direction=direction, edge_layer=edge_layer)
        if node_id not in traversal_graph:
            return []
        neighbor_ids = nx.single_source_shortest_path_length(
            traversal_graph, node_id, cutoff=radius
        ).keys()
        
        return [
            self._node_from_graph_data(nid)
            for nid in neighbor_ids
            if nid != node_id
        ]
    
    def get_related_nodes(
        self,
        node_id: str,
        direction: Direction = "both",
        edge_layer: Optional[EdgeLayer | str] = None,
    ) -> List[tuple[Node, Edge]]:
        """
        Получить узлы, связанные с данным, вместе со связями.
        
        Returns:
            Список кортежей (узел, связь)
        """
        if node_id not in self.graph:
            return []
        
        result = []
        layer = self._coerce_edge_layer(edge_layer)

        if direction in {"out", "both"}:
            for _, neighbor_id, key, data in self.graph.out_edges(node_id, keys=True, data=True):
                edge = Edge.from_dict(data)
                if layer is not None and edge.edge_layer != layer:
                    continue
                neighbor = self.get_node(neighbor_id)
                if neighbor:
                    result.append((neighbor, edge))

        if direction in {"in", "both"}:
            for neighbor_id, _, key, data in self.graph.in_edges(node_id, keys=True, data=True):
                edge = Edge.from_dict(data)
                if layer is not None and edge.edge_layer != layer:
                    continue
                neighbor = self.get_node(neighbor_id)
                if neighbor:
                    result.append((neighbor, edge))
        
        return result
    
    # === Операции с фрагментами ===
    
    def add_fragment(self, fragment: KnowledgeFragment) -> None:
        """Добавить исходный фрагмент знания."""
        self.fragments[fragment.id] = fragment
    
    def get_fragment(self, fragment_id: str) -> Optional[KnowledgeFragment]:
        """Получить фрагмент по ID."""
        return self.fragments.get(fragment_id)
    
    def get_all_fragments(self) -> List[KnowledgeFragment]:
        """Получить все фрагменты."""
        return list(self.fragments.values())

    # === Операции с предложениями агента ===

    def add_proposal(self, proposal: AgentProposal) -> None:
        """Добавить reviewable proposal без изменения смыслового графа."""
        self.proposals[proposal.id] = proposal

    def get_proposal(self, proposal_id: str) -> Optional[AgentProposal]:
        """Получить proposal по ID."""
        return self.proposals.get(proposal_id)

    def update_proposal(self, proposal: AgentProposal) -> bool:
        """Обновить существующий proposal."""
        if proposal.id not in self.proposals:
            return False
        self.proposals[proposal.id] = proposal
        return True

    def get_all_proposals(
        self,
        review_status: Optional[ReviewStatus | str] = None,
    ) -> List[AgentProposal]:
        """Получить все предложения агента с опциональной фильтрацией статуса."""
        if review_status is None:
            return list(self.proposals.values())
        status = review_status if isinstance(review_status, ReviewStatus) else ReviewStatus(review_status)
        return [proposal for proposal in self.proposals.values() if proposal.review_status == status]
    
    # === Сохранение и загрузка ===
    
    def save(self) -> None:
        """Сохранить граф и фрагменты на диск."""
        if not self.store:
            raise ValueError("storage_path не указан")
        self.store.save(self)
    
    def load(self) -> None:
        """Загрузить граф и фрагменты с диска."""
        if not self.store:
            raise ValueError("storage_path не указан")
        self.store.load(self)

    def to_storage_dict(self) -> Dict[str, Any]:
        """Serialize canonical graph state with schema version."""
        return {
            "schema_version": SCHEMA_VERSION,
            "nodes": [node.to_dict() for node in self.get_all_nodes()],
            "edges": [edge.to_dict() for edge in self.get_all_edges()],
            "fragments": [fragment.to_dict() for fragment in self.fragments.values()],
            "proposals": [proposal.to_dict() for proposal in self.proposals.values()],
        }

    def load_storage_dict(self, payload: Dict[str, Any]) -> None:
        """Load canonical graph state and migrate supported legacy values."""
        version = int(payload.get("schema_version") or 0)
        if version > SCHEMA_VERSION:
            raise ValueError(f"Unsupported graph schema version: {version}")

        graph = nx.MultiDiGraph()
        for node_data in payload.get("nodes", []):
            node = Node.from_dict(node_data)
            graph.add_node(node.id, **node.to_dict())
        self.graph = graph

        for edge_data in payload.get("edges", []):
            edge = Edge.from_dict(edge_data)
            self.add_edge(edge)

        self.fragments = {
            fragment['id']: KnowledgeFragment.from_dict(fragment)
            for fragment in payload.get("fragments", [])
        }
        self.proposals = {
            proposal['id']: AgentProposal.from_dict(proposal)
            for proposal in payload.get("proposals", [])
        }

    def load_legacy_gexf(self, gexf_path: Path) -> None:
        """Load a legacy GEXF graph and normalize data for current models."""
        loaded_graph = self._read_gexf_safely(gexf_path)
        self.graph = self._normalize_loaded_graph(loaded_graph)

        for node_id in self.graph.nodes():
            data = dict(self.graph.nodes[node_id])
            if 'metadata' in data and isinstance(data['metadata'], str):
                data['metadata'] = self._decode_mapping(data['metadata'])
            if 'embeddings' in data and isinstance(data['embeddings'], str):
                data['embeddings'] = json.loads(data['embeddings']) if data['embeddings'] != '[]' else None
            data.setdefault('user_id', 'local')
            data.setdefault('graph_id', 'default')
            for key, value in data.items():
                if key in ('strength', 'decay_rate'):
                    self.graph.nodes[node_id][key] = float(value) if isinstance(value, str) else value
                else:
                    self.graph.nodes[node_id][key] = value

        for source, target, key in self.graph.edges(keys=True):
            data = dict(self.graph.edges[source, target, key])
            if 'metadata' in data and isinstance(data['metadata'], str):
                data['metadata'] = self._decode_mapping(data['metadata'])
            if 'weight' in data:
                data['weight'] = float(data['weight']) if isinstance(data['weight'], str) else data['weight']
            data.setdefault('user_id', 'local')
            data.setdefault('graph_id', 'default')
            data.setdefault('edge_layer', data.get('metadata', {}).get('edge_layer', EdgeLayer.MANUAL.value))
            edge = Edge.from_dict(data)
            self.graph.edges[source, target, key].update(edge.to_dict())

    def _read_gexf_safely(self, gexf_path: Path) -> nx.Graph:
        """Read GEXF, tolerating older files with mixed networkx_key types."""
        try:
            return nx.read_gexf(gexf_path)
        except ValueError as exc:
            if "invalid literal for int()" not in str(exc):
                raise

            tree = ET.parse(gexf_path)
            root = tree.getroot()
            for element in root.iter():
                if element.attrib.get("title") == "networkx_key":
                    element.set("type", "string")

            buffer = BytesIO()
            tree.write(buffer, encoding="utf-8", xml_declaration=True)
            buffer.seek(0)
            return nx.read_gexf(buffer)

    def _normalize_loaded_graph(self, loaded_graph: nx.Graph) -> nx.MultiDiGraph:
        """Restore stable string edge keys after reading from GEXF."""
        graph = nx.MultiDiGraph()

        for node_id, data in loaded_graph.nodes(data=True):
            graph.add_node(str(node_id), **dict(data))

        for source, target, data in loaded_graph.edges(data=True):
            edge_data = dict(data)
            edge_id = str(edge_data.get('id') or edge_data.get('networkx_key') or len(graph.edges))
            edge_data['id'] = edge_id
            edge_data.pop('networkx_key', None)
            graph.add_edge(str(source), str(target), key=edge_id, **edge_data)

        return graph

    def _node_from_graph_data(self, node_id: str) -> Node:
        """Build a Node while preserving the graph key as the stable node id."""
        data = dict(self.graph.nodes[node_id])
        data.setdefault('id', str(node_id))
        return Node.from_dict(data)

    def _coerce_edge_layer(self, edge_layer: Optional[EdgeLayer | str]) -> Optional[EdgeLayer]:
        if edge_layer is None:
            return None
        return edge_layer if isinstance(edge_layer, EdgeLayer) else EdgeLayer(edge_layer)

    def _filtered_traversal_graph(
        self,
        direction: Direction = "both",
        edge_layer: Optional[EdgeLayer | str] = None,
    ) -> nx.Graph:
        """Build a lightweight traversal graph honoring direction and layer filters."""
        layer = self._coerce_edge_layer(edge_layer)
        traversal = nx.DiGraph() if direction in {"out", "in"} else nx.Graph()
        traversal.add_nodes_from(self.graph.nodes)
        for source, target, data in self.graph.edges(data=True):
            edge = Edge.from_dict(data)
            if layer is not None and edge.edge_layer != layer:
                continue
            if direction == "in":
                traversal.add_edge(target, source)
            else:
                traversal.add_edge(source, target)
        return traversal

    def _decode_mapping(self, value: str) -> Dict[str, Any]:
        """Decode metadata saved either as JSON or legacy Python repr."""
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = ast.literal_eval(value)
        return decoded if isinstance(decoded, dict) else {}
    
    # === Статистика ===
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику графа."""
        nodes = self.get_all_nodes()
        edges = self.get_all_edges()
        
        # Распределение типов узлов
        node_types_count: Dict[str, int] = {}
        for node in nodes:
            node_type = node.node_type.value
            node_types_count[node_type] = node_types_count.get(node_type, 0) + 1
        
        # Распределение типов связей
        edge_types_count: Dict[str, int] = {}
        for edge in edges:
            edge_type = edge.edge_type.value
            edge_types_count[edge_type] = edge_types_count.get(edge_type, 0) + 1
        
        return {
            'schema_version': SCHEMA_VERSION,
            'total_nodes': len(nodes),
            'total_edges': len(edges),
            'total_fragments': len(self.fragments),
            'total_proposals': len(self.proposals),
            'node_types': node_types_count,
            'edge_types': edge_types_count,
            'edge_layers': self._edge_layers_count(edges),
            'avg_node_strength': sum(n.strength for n in nodes) / len(nodes) if nodes else 0,
            'forgotten_nodes_count': len(self.get_forgotten_nodes()),
        }

    def _edge_layers_count(self, edges: List[Edge]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for edge in edges:
            layer = edge.edge_layer.value
            counts[layer] = counts.get(layer, 0) + 1
        return counts
