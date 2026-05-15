"""
Тесты для базовых операций с графом знаний.

Проверяют:
- Создание и управление узлами
- Создание и управление связями
- Сохранение и загрузку графа
- Поиск и фильтрацию
"""

import pytest
from datetime import datetime, timedelta, timezone
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
)
from app.core.repository import GraphRepository


def utc_now():
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


class TestNode:
    """Тесты для модели Node."""
    
    def test_create_node_default_values(self):
        """Создание узла с параметрами по умолчанию."""
        node = Node(content="Test fact")
        
        assert node.content == "Test fact"
        assert node.node_type == NodeType.FACT
        assert node.strength == 1.0
        assert node.decay_rate == 0.01
        assert node.metadata['source'] == 'manual'
        assert node.trust_status == TrustStatus.CONFIRMED
        assert node.origin == Origin.USER
        assert node.review_status == ReviewStatus.ACCEPTED
        assert node.tags == []
        assert node.id is not None
    
    def test_create_node_custom_values(self):
        """Создание узла с кастомными параметрами."""
        node = Node(
            content="Important idea",
            node_type=NodeType.IDEA,
            strength=0.8,
            decay_rate=0.05,
            metadata={'topic': 'AI', 'difficulty': 'hard'},
            title="AI note",
            tags=["ai", "thinking"],
            user_comment="seed",
        )
        
        assert node.node_type == NodeType.IDEA
        assert node.strength == 0.8
        assert node.decay_rate == 0.05
        assert node.metadata['topic'] == 'AI'
        assert node.title == "AI note"
        assert node.tags == ["ai", "thinking"]
        assert node.metadata["trust_status"] == "confirmed"
    
    def test_node_serialization(self):
        """Сериализация и десериализация узла."""
        original = Node(
            content="Test content",
            node_type=NodeType.IDEA,
            source_text="Original source paragraph.",
            strength=0.9,
            trust_status=TrustStatus.SUGGESTED,
            origin=Origin.LLM,
            review_status=ReviewStatus.PENDING,
            title="Test title",
            tags=["test"],
            user_comment="Review me",
        )
        
        serialized = original.to_dict()
        restored = Node.from_dict(serialized)
        
        assert restored.id == original.id
        assert restored.content == original.content
        assert restored.source_text == original.source_text
        assert restored.node_type == original.node_type
        assert restored.strength == original.strength
        assert restored.trust_status == TrustStatus.SUGGESTED
        assert restored.origin == Origin.LLM
        assert restored.review_status == ReviewStatus.PENDING
        assert restored.title == "Test title"
        assert restored.tags == ["test"]
        assert restored.user_comment == "Review me"
    
    def test_node_interact_increases_strength(self):
        """Взаимодействие увеличивает силу памяти."""
        node = Node(content="Test", strength=0.5)
        
        node.interact()
        
        assert node.strength == 0.6  # 0.5 + 0.1
        assert node.last_interacted <= utc_now()
    
    def test_node_strength_caps_at_1(self):
        """Сила памяти не превышает 1.0."""
        node = Node(content="Test", strength=0.95)
        
        node.interact()
        
        assert node.strength == 1.0
    
    def test_calculate_current_strength_no_decay(self):
        """Расчёт силы без забывания (свежий узел)."""
        node = Node(content="Test", strength=0.8)
        # last_interacted установлен в now при создании
        
        current = node.calculate_current_strength()
        
        assert current == 0.8
    
    def test_calculate_current_strength_with_decay(self, monkeypatch):
        """Расчёт силы с учётом забывания."""
        node = Node(
            content="Test",
            strength=1.0,
            decay_rate=0.1  # 10% в день
        )
        # Устанавливаем last_interacted в прошлое
        node.last_interacted = utc_now() - timedelta(days=7)
        
        current = node.calculate_current_strength()
        
        # После 7 дней с decay_rate=0.1: e^(-0.1*7) ≈ 0.496
        assert current < 0.6
        assert current > 0.4
    
    def test_is_forgotten(self, monkeypatch):
        """Проверка статуса «забыт»."""
        node = Node(content="Test", strength=1.0, decay_rate=0.1)
        node.last_interacted = utc_now() - timedelta(days=30)
        
        assert node.is_forgotten(threshold=0.3) is True
        assert node.is_forgotten(threshold=0.01) is False


class TestEdge:
    """Тесты для модели Edge."""
    
    def test_create_edge_default_values(self):
        """Создание связи с параметрами по умолчанию."""
        edge = Edge(source_id="node1", target_id="node2")
        
        assert edge.source_id == "node1"
        assert edge.target_id == "node2"
        assert edge.edge_type == EdgeType.USED_IN
        assert edge.weight == 1.0
        assert edge.trust_status == TrustStatus.CONFIRMED
        assert edge.origin == Origin.USER
        assert edge.review_status == ReviewStatus.ACCEPTED
    
    def test_create_edge_custom_values(self):
        """Создание связи с кастомными параметрами."""
        edge = Edge(
            source_id="node1",
            target_id="node2",
            edge_type=EdgeType.CONTRADICTS,
            weight=0.5,
            metadata={'reason': 'logical conflict'}
        )
        
        assert edge.edge_type == EdgeType.CONTRADICTS
        assert edge.weight == 0.5
        assert edge.metadata['reason'] == 'logical conflict'
    
    def test_edge_serialization(self):
        """Сериализация и десериализация связи."""
        original = Edge(
            source_id="a",
            target_id="b",
            edge_type=EdgeType.DERIVED_FROM,
            weight=0.8,
            trust_status=TrustStatus.SUGGESTED,
            origin=Origin.AGENT,
            review_status=ReviewStatus.PENDING,
            user_comment="Check direction",
        )
        
        serialized = original.to_dict()
        restored = Edge.from_dict(serialized)
        
        assert restored.id == original.id
        assert restored.source_id == original.source_id
        assert restored.edge_type == original.edge_type
        assert restored.weight == original.weight
        assert restored.trust_status == TrustStatus.SUGGESTED
        assert restored.origin == Origin.AGENT
        assert restored.review_status == ReviewStatus.PENDING
        assert restored.user_comment == "Check direction"


class TestKnowledgeFragment:
    """Тесты для модели KnowledgeFragment."""
    
    def test_create_fragment(self):
        """Создание фрагмента знания."""
        fragment = KnowledgeFragment(
            content="Full article text...",
            source_type='article',
            source_url='https://example.com/article'
        )
        
        assert fragment.content == "Full article text..."
        assert fragment.source_type == 'article'
        assert fragment.source_url == 'https://example.com/article'
        assert fragment.extracted_nodes == []
    
    def test_fragment_serialization(self):
        """Сериализация и десериализация фрагмента."""
        original = KnowledgeFragment(
            content="Test content",
            source_type='chat'
        )
        
        serialized = original.to_dict()
        restored = KnowledgeFragment.from_dict(serialized)
        
        assert restored.id == original.id
        assert restored.content == original.content
        assert restored.source_type == original.source_type


class TestGraphRepository:
    """Тесты для GraphRepository."""
    
    @pytest.fixture
    def repo(self, tmp_path):
        """Создание репозитория для тестов."""
        storage_file = tmp_path / "test_graph"
        return GraphRepository(storage_path=str(storage_file))
    
    def test_add_and_get_node(self, repo):
        """Добавление и получение узла."""
        node = Node(content="Test node")
        
        repo.add_node(node)
        retrieved = repo.get_node(node.id)
        
        assert retrieved is not None
        assert retrieved.content == "Test node"
        assert retrieved.id == node.id
    
    def test_get_nonexistent_node(self, repo):
        """Получение несуществующего узла."""
        result = repo.get_node("nonexistent-id")
        assert result is None
    
    def test_update_node(self, repo):
        """Обновление узла."""
        node = Node(content="Original")
        repo.add_node(node)
        
        node.content = "Updated"
        node.strength = 0.5
        success = repo.update_node(node)
        
        assert success is True
        retrieved = repo.get_node(node.id)
        assert retrieved.content == "Updated"
        assert retrieved.strength == 0.5
    
    def test_update_nonexistent_node(self, repo):
        """Обновление несуществующего узла."""
        node = Node(content="Test")
        success = repo.update_node(node)
        assert success is False
    
    def test_delete_node(self, repo):
        """Удаление узла."""
        node = Node(content="To delete")
        repo.add_node(node)
        
        success = repo.delete_node(node.id)
        
        assert success is True
        assert repo.get_node(node.id) is None
    
    def test_delete_nonexistent_node(self, repo):
        """Удаление несуществующего узла."""
        success = repo.delete_node("nonexistent")
        assert success is False
    
    def test_get_all_nodes(self, repo):
        """Получение всех узлов."""
        nodes = [
            Node(content=f"Node {i}")
            for i in range(5)
        ]
        
        for node in nodes:
            repo.add_node(node)
        
        all_nodes = repo.get_all_nodes()
        
        assert len(all_nodes) == 5
        contents = {n.content for n in all_nodes}
        assert contents == {"Node 0", "Node 1", "Node 2", "Node 3", "Node 4"}
    
    def test_get_nodes_by_type(self, repo):
        """Фильтрация узлов по типу."""
        repo.add_node(Node(content="Fact 1", node_type=NodeType.FACT))
        repo.add_node(Node(content="Fact 2", node_type=NodeType.FACT))
        repo.add_node(Node(content="Idea 1", node_type=NodeType.IDEA))
        
        facts = repo.get_nodes_by_type(NodeType.FACT)
        
        assert len(facts) == 2
        assert all(n.node_type == NodeType.FACT for n in facts)
    
    def test_search_nodes(self, repo):
        """Поиск узлов по содержимому."""
        repo.add_node(Node(content="Python is a programming language"))
        repo.add_node(Node(content="Java is also a programming language"))
        repo.add_node(Node(content="Cats are cute"))
        
        results = repo.search_nodes("programming language")
        
        assert len(results) == 2
        assert all("programming language" in n.content.lower() for n in results)
    
    def test_add_and_get_edge(self, repo):
        """Добавление и получение связи."""
        node1 = Node(content="Source")
        node2 = Node(content="Target")
        repo.add_node(node1)
        repo.add_node(node2)
        
        edge = Edge(source_id=node1.id, target_id=node2.id, edge_type=EdgeType.DERIVED_FROM)
        repo.add_edge(edge)
        
        retrieved = repo.get_edge(edge.id)
        
        assert retrieved is not None
        assert retrieved.source_id == node1.id
        assert retrieved.edge_type == EdgeType.DERIVED_FROM

    def test_add_edge_rejects_missing_nodes(self, repo):
        """Repository does not let NetworkX create empty nodes from broken edges."""
        node = Node(content="Existing")
        repo.add_node(node)

        with pytest.raises(ValueError):
            repo.add_edge(Edge(source_id=node.id, target_id="missing"))

        assert repo.get_node("missing") is None
        assert repo.get_all_edges() == []
    
    def test_get_edges_between(self, repo):
        """Получение связей между узлами."""
        node1 = Node(content="A")
        node2 = Node(content="B")
        repo.add_node(node1)
        repo.add_node(node2)
        
        edge1 = Edge(source_id=node1.id, target_id=node2.id, edge_type=EdgeType.USED_IN)
        edge2 = Edge(source_id=node1.id, target_id=node2.id, edge_type=EdgeType.DERIVED_FROM)
        repo.add_edge(edge1)
        repo.add_edge(edge2)
        
        edges = repo.get_edges_between(node1.id, node2.id)
        
        assert len(edges) == 2
    
    def test_delete_edge(self, repo):
        """Удаление связи."""
        node1 = Node(content="A")
        node2 = Node(content="B")
        repo.add_node(node1)
        repo.add_node(node2)
        
        edge = Edge(source_id=node1.id, target_id=node2.id)
        repo.add_edge(edge)
        
        success = repo.delete_edge(edge.id)
        
        assert success is True
        assert repo.get_edge(edge.id) is None
    
    def test_get_contradictions(self, repo):
        """Получение противоречий."""
        node1 = Node(content="Statement A")
        node2 = Node(content="Statement B")
        node3 = Node(content="Statement C")
        repo.add_node(node1)
        repo.add_node(node2)
        repo.add_node(node3)
        
        repo.add_edge(Edge(source_id=node1.id, target_id=node2.id, edge_type=EdgeType.CONTRADICTS))
        repo.add_edge(Edge(source_id=node2.id, target_id=node3.id, edge_type=EdgeType.USED_IN))
        
        contradictions = repo.get_contradictions()
        
        assert len(contradictions) == 1
        assert contradictions[0].edge_type == EdgeType.CONTRADICTS
    
    def test_get_neighbors(self, repo):
        """Получение соседних узлов."""
        center = Node(content="Center")
        neighbor1 = Node(content="Neighbor 1")
        neighbor2 = Node(content="Neighbor 2")
        distant = Node(content="Distant")
        
        repo.add_node(center)
        repo.add_node(neighbor1)
        repo.add_node(neighbor2)
        repo.add_node(distant)
        
        repo.add_edge(Edge(source_id=center.id, target_id=neighbor1.id))
        repo.add_edge(Edge(source_id=center.id, target_id=neighbor2.id))
        repo.add_edge(Edge(source_id=neighbor1.id, target_id=distant.id))
        
        neighbors = repo.get_neighbors(center.id, radius=1)
        
        assert len(neighbors) == 2
        neighbor_contents = {n.content for n in neighbors}
        assert neighbor_contents == {"Neighbor 1", "Neighbor 2"}

    def test_get_neighbors_supports_incoming_outgoing_and_layer_filters(self, repo):
        """Navigation can traverse directionally and filter manual/service layers."""
        center = Node(content="Center")
        incoming = Node(content="Incoming")
        outgoing = Node(content="Outgoing")
        service = Node(content="Service")
        for node in (center, incoming, outgoing, service):
            repo.add_node(node)

        repo.add_edge(Edge(source_id=incoming.id, target_id=center.id, edge_type=EdgeType.USED_IN))
        repo.add_edge(Edge(source_id=center.id, target_id=outgoing.id, edge_type=EdgeType.USED_IN))
        repo.add_edge(
            Edge(
                source_id=center.id,
                target_id=service.id,
                edge_type=EdgeType.USED_IN,
                edge_layer=EdgeLayer.SERVICE,
            )
        )

        assert {node.content for node in repo.get_neighbors(center.id, direction="in")} == {"Incoming"}
        assert {node.content for node in repo.get_neighbors(center.id, direction="out")} == {"Outgoing", "Service"}
        assert {node.content for node in repo.get_neighbors(center.id, edge_layer=EdgeLayer.MANUAL)} == {
            "Incoming",
            "Outgoing",
        }
    
    def test_get_related_nodes(self, repo):
        """Получение связанных узлов с связями."""
        node1 = Node(content="A")
        node2 = Node(content="B")
        repo.add_node(node1)
        repo.add_node(node2)
        
        edge = Edge(source_id=node1.id, target_id=node2.id, edge_type=EdgeType.USED_IN)
        repo.add_edge(edge)
        
        related = repo.get_related_nodes(node1.id)
        
        assert len(related) == 1
        related_node, related_edge = related[0]
        assert related_node.id == node2.id
        assert related_edge.id == edge.id

    def test_get_related_nodes_includes_incoming_edges(self, repo):
        """Related nodes include incoming edges by default."""
        node1 = Node(content="A")
        node2 = Node(content="B")
        repo.add_node(node1)
        repo.add_node(node2)

        edge = Edge(source_id=node2.id, target_id=node1.id, edge_type=EdgeType.DERIVED_FROM)
        repo.add_edge(edge)

        related = repo.get_related_nodes(node1.id)

        assert len(related) == 1
        related_node, related_edge = related[0]
        assert related_node.id == node2.id
        assert related_edge.source_id == node2.id

    def test_old_non_mvp_edge_types_are_rejected(self, repo):
        """Old persisted edge type values are no longer accepted in the MVP model."""
        node1 = Node(content="A")
        node2 = Node(content="B")
        repo.add_node(node1)
        repo.add_node(node2)

        with pytest.raises(ValueError):
            Edge.from_dict({
                "id": "legacy-edge",
                "source_id": node1.id,
                "target_id": node2.id,
                "edge_type": "related_to",
                "weight": 1.0,
                "metadata": "{}",
                "created_at": utc_now().isoformat(),
            })
    
    def test_add_and_get_fragment(self, repo):
        """Добавление и получение фрагмента."""
        fragment = KnowledgeFragment(content="Article text", source_type='article')
        
        repo.add_fragment(fragment)
        retrieved = repo.get_fragment(fragment.id)
        
        assert retrieved is not None
        assert retrieved.content == "Article text"
    
    def test_get_stats(self, repo):
        """Получение статистики графа."""
        repo.add_node(Node(content="Fact", node_type=NodeType.FACT))
        repo.add_node(Node(content="Idea", node_type=NodeType.IDEA))
        repo.add_node(Node(content="Another Fact", node_type=NodeType.FACT))
        
        repo.add_edge(Edge(source_id=repo.get_all_nodes()[0].id, target_id=repo.get_all_nodes()[1].id))
        
        repo.add_fragment(KnowledgeFragment(content="Source"))
        
        stats = repo.get_stats()
        
        assert stats['total_nodes'] == 3
        assert stats['total_edges'] == 1
        assert stats['total_fragments'] == 1
        assert stats['node_types']['fact'] == 2
        assert stats['node_types']['idea'] == 1
    
    def test_save_and_load(self, repo):
        """Сохранение и загрузка графа."""
        # Создаём узлы и связи
        node1 = Node(content="Persistent node 1")
        node2 = Node(content="Persistent node 2")
        repo.add_node(node1)
        repo.add_node(node2)
        repo.add_edge(Edge(source_id=node1.id, target_id=node2.id))
        
        fragment = KnowledgeFragment(content="Persistent fragment")
        repo.add_fragment(fragment)
        
        # Сохраняем
        repo.save()
        
        # Создаём новый репозиторий и загружаем
        new_repo = GraphRepository(storage_path=str(repo.storage_path))
        
        # Проверяем данные
        assert len(new_repo.get_all_nodes()) == 2
        assert len(new_repo.get_all_edges()) == 1
        assert len(new_repo.get_all_fragments()) == 1
        
        loaded_node1 = new_repo.get_node(node1.id)
        assert loaded_node1 is not None
        assert loaded_node1.content == "Persistent node 1"

    def test_save_load_add_edge_save_load_keeps_uuid_edge_keys(self, repo):
        """Повторное сохранение после загрузки не ломает GEXF edge keys."""
        node1 = Node(content="Node 1")
        node2 = Node(content="Node 2")
        repo.add_node(node1)
        repo.add_node(node2)
        repo.add_edge(Edge(source_id=node1.id, target_id=node2.id))
        repo.save()

        loaded_repo = GraphRepository(storage_path=str(repo.storage_path))
        node3 = Node(content="Node 3")
        loaded_repo.add_node(node3)
        loaded_repo.add_edge(Edge(source_id=node2.id, target_id=node3.id))
        loaded_repo.save()

        reloaded_repo = GraphRepository(storage_path=str(repo.storage_path))

        assert len(reloaded_repo.get_all_nodes()) == 3
        assert len(reloaded_repo.get_all_edges()) == 2
    
    def test_get_forgotten_nodes(self, repo):
        """Получение забытых узлов."""
        fresh_node = Node(content="Fresh", strength=1.0)
        old_node = Node(content="Old", strength=1.0, decay_rate=0.1)
        old_node.last_interacted = utc_now() - timedelta(days=30)
        
        repo.add_node(fresh_node)
        repo.add_node(old_node)
        
        forgotten = repo.get_forgotten_nodes(threshold=0.3)
        
        assert len(forgotten) == 1
        assert forgotten[0].content == "Old"


class TestMemoryModel:
    """Тесты для модели забывания."""
    
    def test_decay_exponential(self):
        """Проверка экспоненциальной модели забывания."""
        node = Node(content="Test", strength=1.0, decay_rate=0.05)
        
        # Симулируем разные промежутки времени
        for days in [0, 7, 14, 30]:
            node.last_interacted = utc_now() - timedelta(days=days)
            strength = node.calculate_current_strength()
            
            # Сила должна убывать со временем
            if days > 0:
                assert strength < 1.0
            
            # Больше дней = меньше сила
            if days == 0:
                assert strength == 1.0
    
    def test_interaction_resets_decay(self):
        """Взаимодействие сбрасывает счётчик забывания."""
        node = Node(content="Test", strength=0.5, decay_rate=0.1)  # Увеличиваем decay_rate для явного эффекта
        node.last_interacted = utc_now() - timedelta(days=30)
        
        # До взаимодействия узел «забыт»
        assert node.calculate_current_strength() < 0.3
        
        # Взаимодействуем
        node.interact()
        
        # После взаимодействия сила восстановлена
        assert node.strength == 0.6  # 0.5 + 0.1
        assert node.calculate_current_strength() == 0.6  # Свежее взаимодействие, нет забывания
