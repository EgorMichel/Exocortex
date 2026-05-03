"""Manual knowledge capture without LLM extraction."""

from __future__ import annotations

from typing import Any, Optional

from app.core.models import KnowledgeFragment, Node, NodeType
from app.core.repository import GraphRepository


def store_manual_fragment(
    repository: GraphRepository,
    text: str,
    source_type: str = "manual_selection",
    source_url: Optional[str] = None,
    document_title: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> tuple[KnowledgeFragment, Node]:
    """Store a user-selected text fragment as a single graph node."""
    content = text.strip()
    if not content:
        raise ValueError("No text provided.")

    fragment = KnowledgeFragment(
        content=content,
        source_type=source_type,
        source_url=source_url,
    )
    node_metadata: dict[str, Any] = {
        "source": fragment.id,
        "source_type": source_type,
        "entry_mode": "manual_selection",
    }
    if source_url:
        node_metadata["source_url"] = source_url
    if document_title:
        node_metadata["document_title"] = document_title
    if metadata:
        node_metadata.update(metadata)

    node = Node(
        content=content,
        node_type=NodeType.EXCERPT,
        metadata=node_metadata,
    )

    repository.add_node(node)
    fragment.extracted_nodes.append(node.id)
    repository.add_fragment(fragment)
    if repository.storage_path:
        repository.save()
    return fragment, node
