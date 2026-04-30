"""
Репозиторий для операций с графом знаний.

Использует NetworkX для хранения графа в памяти (для MVP).
В будущем может быть заменён на Neo4j или другую графовую БД.
"""

import ast
import json
from io import BytesIO
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import xml.etree.ElementTree as ET
import networkx as nx

from app.core.models import Node, Edge, NodeType, EdgeType, KnowledgeFragment


class GraphRepository:
    """
    Репозиторий для управления графом знаний.
    
    Поддерживает:
    - CRUD операции для узлов и связей
    - Сохранение/загрузку графа на диск
    - Поиск и фильтрацию узлов
    - Получение связанных узлов
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        Инициализация репозитория.
        
        Args:
            storage_path: Путь к файлу для сохранения графа.
                         Если None, граф хранится только в памяти.
        """
        self.graph = nx.MultiDiGraph()  # MultiDiGraph позволяет несколько связей между узлами
        self.storage_path = Path(storage_path) if storage_path else None
        self.fragments: Dict[str, KnowledgeFragment] = {}
        
        # Проверяем существование файла графа (с расширением .gexf)
        if self.storage_path:
            gexf_path = self.storage_path.with_suffix('.gexf')
            if gexf_path.exists():
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
        
        data = self.graph.nodes[node_id]
        return Node.from_dict(data)
    
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
            Node.from_dict(dict(self.graph.nodes[node_id]))
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
        """Добавить связь в граф."""
        self.graph.add_edge(
            edge.source_id,
            edge.target_id,
            key=edge.id,
            **edge.to_dict()
        )
    
    def get_edge(self, edge_id: str) -> Optional[Edge]:
        """Получить связь по ID."""
        for source, target, key, data in self.graph.edges(keys=True, data=True):
            if key == edge_id:
                return Edge.from_dict(data)
        return None
    
    def get_edges_between(self, source_id: str, target_id: str) -> List[Edge]:
        """Получить все связи между двумя узлами."""
        if source_id not in self.graph or target_id not in self.graph:
            return []
        
        edges = []
        for key, data in self.graph.get_edge_data(source_id, target_id, default={}).items():
            if key != 'key':  # Пропускаем служебные ключи
                edges.append(Edge.from_dict(data))
        
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
    
    def get_all_edges(self) -> List[Edge]:
        """Получить все связи графа."""
        edges = []
        for source, target, key, data in self.graph.edges(keys=True, data=True):
            edges.append(Edge.from_dict(data))
        return edges
    
    def get_contradictions(self) -> List[Edge]:
        """Получить все связи типа «противоречие»."""
        return [
            edge for edge in self.get_all_edges()
            if edge.edge_type == EdgeType.CONTRADICTS
        ]
    
    # === Навигация по графу ===
    
    def get_neighbors(self, node_id: str, radius: int = 1) -> List[Node]:
        """
        Получить соседние узлы.
        
        Args:
            node_id: ID центрального узла
            radius: Количество шагов от узла (по умолчанию 1)
        """
        if node_id not in self.graph:
            return []
        
        neighbor_ids = nx.single_source_shortest_path_length(
            self.graph, node_id, cutoff=radius
        ).keys()
        
        return [
            Node.from_dict(dict(self.graph.nodes[nid]))
            for nid in neighbor_ids
            if nid != node_id
        ]
    
    def get_related_nodes(self, node_id: str) -> List[tuple[Node, Edge]]:
        """
        Получить узлы, связанные с данным, вместе со связями.
        
        Returns:
            Список кортежей (узел, связь)
        """
        if node_id not in self.graph:
            return []
        
        result = []
        for neighbor_id in self.graph.neighbors(node_id):
            neighbor = self.get_node(neighbor_id)
            if neighbor:
                edges = self.get_edges_between(node_id, neighbor_id)
                for edge in edges:
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
    
    # === Сохранение и загрузка ===
    
    def save(self) -> None:
        """Сохранить граф и фрагменты на диск."""
        if not self.storage_path:
            raise ValueError("storage_path не указан")

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Сохраняем граф как GEXF (лучше поддерживает MultiDiGraph)
        gexf_path = self.storage_path.with_suffix('.gexf')
        nx.write_gexf(self.graph, gexf_path)
        
        # Сохраняем фрагменты отдельно как JSON
        fragments_path = self.storage_path.with_suffix('.fragments.json')
        with open(fragments_path, 'w', encoding='utf-8') as f:
            json.dump(
                [f.to_dict() for f in self.fragments.values()],
                f,
                ensure_ascii=False,
                indent=2
            )
    
    def load(self) -> None:
        """Загрузить граф и фрагменты с диска."""
        if not self.storage_path:
            raise ValueError("storage_path не указан")
        
        # Загружаем граф (GEXF формат)
        gexf_path = self.storage_path.with_suffix('.gexf')
        if gexf_path.exists():
            loaded_graph = self._read_gexf_safely(gexf_path)
            self.graph = self._normalize_loaded_graph(loaded_graph)
            
            # Обрабатываем атрибуты узлов
            for node_id in self.graph.nodes():
                data = dict(self.graph.nodes[node_id])
                # Преобразуем строковые представления обратно в типы
                if 'metadata' in data and isinstance(data['metadata'], str):
                    data['metadata'] = self._decode_mapping(data['metadata'])
                if 'embeddings' in data and isinstance(data['embeddings'], str):
                    data['embeddings'] = json.loads(data['embeddings']) if data['embeddings'] != '[]' else None
                # Обновляем данные узла
                for key, value in data.items():
                    if key in ('strength', 'decay_rate'):
                        self.graph.nodes[node_id][key] = float(value) if isinstance(value, str) else value
            
            # Обрабатываем атрибуты связей
            for source, target, key in self.graph.edges(keys=True):
                data = dict(self.graph.edges[source, target, key])
                if 'metadata' in data and isinstance(data['metadata'], str):
                    data['metadata'] = self._decode_mapping(data['metadata'])
                if 'weight' in data:
                    data['weight'] = float(data['weight']) if isinstance(data['weight'], str) else data['weight']
                # Обновляем данные связи
                for k, v in data.items():
                    self.graph.edges[source, target, key][k] = v
        
        # Загружаем фрагменты
        fragments_path = self.storage_path.with_suffix('.fragments.json')
        if fragments_path.exists():
            with open(fragments_path, 'r', encoding='utf-8') as f:
                fragments_data = json.load(f)
                self.fragments = {
                    frag['id']: KnowledgeFragment.from_dict(frag)
                    for frag in fragments_data
                }

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
        node_types_count = {}
        for node in nodes:
            node_type = node.node_type.value
            node_types_count[node_type] = node_types_count.get(node_type, 0) + 1
        
        # Распределение типов связей
        edge_types_count = {}
        for edge in edges:
            edge_type = edge.edge_type.value
            edge_types_count[edge_type] = edge_types_count.get(edge_type, 0) + 1
        
        return {
            'total_nodes': len(nodes),
            'total_edges': len(edges),
            'total_fragments': len(self.fragments),
            'node_types': node_types_count,
            'edge_types': edge_types_count,
            'avg_node_strength': sum(n.strength for n in nodes) / len(nodes) if nodes else 0,
            'forgotten_nodes_count': len(self.get_forgotten_nodes()),
        }
