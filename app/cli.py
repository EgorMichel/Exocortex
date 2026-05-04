"""Command line interface for Exocortex."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Iterable, Optional

from app.agents.proactive import AgentSettings, ProactiveAgent
from app.config import load_settings
from app.core.models import Node
from app.core.repository import GraphRepository
from app.llm.extraction import LLMService, extract_and_store
from app.services.external_sources import ExternalSourceIngestor
from app.services.manual_capture import store_manual_fragment
from app.services.personalization import PersonalizationService


def _build_repository() -> GraphRepository:
    settings = load_settings()
    return GraphRepository(storage_path=settings.storage_path)


def _build_llm_service() -> LLMService:
    settings = load_settings()
    return LLMService(
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        base_url=settings.llm_api_base,
    )


def _build_agent(repo: Optional[GraphRepository] = None) -> ProactiveAgent:
    settings = load_settings()
    return ProactiveAgent(
        repository=repo or GraphRepository(storage_path=settings.storage_path),
        llm_service=_build_llm_service(),
        settings=AgentSettings(
            digest_limit=settings.agent_digest_limit,
            forgotten_threshold=settings.agent_forgotten_threshold,
            contradiction_batch_size=settings.agent_contradiction_batch_size,
        ),
    )


def _build_personalization_service(repo: Optional[GraphRepository] = None) -> PersonalizationService:
    repository = repo or _build_repository()
    agent = _build_agent(repository)
    return PersonalizationService(repository=repository, insight_store=agent.insight_store)


def _read_input(args: argparse.Namespace) -> str:
    chunks: list[str] = []

    if getattr(args, "file", None):
        chunks.append(Path(args.file).read_text(encoding="utf-8"))

    if getattr(args, "stdin", False):
        chunks.append(sys.stdin.read())

    if getattr(args, "text", None):
        chunks.append(" ".join(args.text))

    text = "\n".join(chunk.strip() for chunk in chunks if chunk.strip()).strip()
    if not text:
        raise ValueError("No text provided. Pass text arguments, --file, or --stdin.")
    return text


def _print_stats(repo: GraphRepository) -> None:
    stats = repo.get_stats()
    print(f"Nodes: {stats['total_nodes']}")
    print(f"Edges: {stats['total_edges']}")
    print(f"Fragments: {stats['total_fragments']}")
    print(f"Forgotten nodes: {stats['forgotten_nodes_count']}")
    print(f"Average node strength: {stats['avg_node_strength']:.3f}")
    if stats["node_types"]:
        print("Node types:")
        for node_type, count in sorted(stats["node_types"].items()):
            print(f"  {node_type}: {count}")
    if stats["edge_types"]:
        print("Edge types:")
        for edge_type, count in sorted(stats["edge_types"].items()):
            print(f"  {edge_type}: {count}")


def _print_nodes(nodes: Iterable[Node], limit: Optional[int] = None) -> None:
    count = 0
    for node in nodes:
        count += 1
        if limit is not None and count > limit:
            break
        strength = node.calculate_current_strength()
        content = node.content.replace("\n", " ")
        print(f"{node.id} [{node.node_type.value}] strength={strength:.3f} {content}")
    if count == 0:
        print("No nodes found.")


async def _cmd_add(args: argparse.Namespace) -> int:
    text = _read_input(args)
    repo = _build_repository()
    fragment = await extract_and_store(
        text=text,
        repository=repo,
        source_type=args.source_type,
        source_url=args.source_url,
        llm_service=_build_llm_service(),
    )
    print(f"Added fragment: {fragment.id}")
    print(f"Nodes created: {len(fragment.extracted_nodes)}")
    print(f"Total nodes: {repo.get_stats()['total_nodes']}")
    return 0


def _cmd_add_manual(args: argparse.Namespace) -> int:
    text = _read_input(args)
    repo = _build_repository()
    fragment, node = store_manual_fragment(
        repository=repo,
        text=text,
        source_type=args.source_type,
        source_url=args.source_url,
        document_title=args.document_title,
    )
    print(f"Added manual fragment: {fragment.id}")
    print(f"Node created: {node.id}")
    print(f"Total nodes: {repo.get_stats()['total_nodes']}")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    _print_stats(_build_repository())
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    repo = _build_repository()
    _print_nodes(repo.get_all_nodes(), limit=args.limit)
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    repo = _build_repository()
    _print_nodes(repo.search_nodes(args.query), limit=args.limit)
    return 0


def _cmd_forgotten(args: argparse.Namespace) -> int:
    repo = _build_repository()
    _print_nodes(repo.get_forgotten_nodes(threshold=args.threshold), limit=args.limit)
    return 0


def _cmd_clear(args: argparse.Namespace) -> int:
    settings = load_settings()
    storage_path = Path(settings.storage_path)
    deleted = 0
    for path in (
        storage_path.with_suffix(".gexf"),
        storage_path.with_suffix(".fragments.json"),
        storage_path.with_suffix(".insights.json"),
        storage_path.with_suffix(".feedback.json"),
    ):
        if path.exists():
            path.unlink()
            deleted += 1
    print(f"Cleared storage files: {deleted}")
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    repo = _build_repository()
    agent = _build_agent(repo)
    digest = agent.analyze_sync(save=not args.no_save)
    print(digest.format_text())
    return 0


def _cmd_digest(args: argparse.Namespace) -> int:
    agent = _build_agent()
    digest = agent.get_latest_digest()
    if digest is None:
        print("No saved digest found.")
        return 0
    print(digest.format_text())
    return 0


def _cmd_inbox(args: argparse.Namespace) -> int:
    service = _build_personalization_service()
    items = service.list_inbox(include_reacted=args.include_reacted, limit=args.limit)
    if not items:
        print("Inbox is empty.")
        return 0

    for item in items:
        insight = item.insight
        status = item.feedback.action.value if item.feedback else "pending"
        print(f"{insight.id} [{insight.insight_type.value}] status={status} score={insight.score:.3f}")
        print(f"  {insight.title}")
        print(f"  {insight.description}")
    return 0


def _cmd_react(args: argparse.Namespace) -> int:
    service = _build_personalization_service()
    feedback = service.react_to_insight(
        insight_id=args.insight_id,
        action=args.action,
        note=args.note,
    )
    print(f"Recorded feedback: {feedback.action.value}")
    print(f"Insight: {feedback.insight_id}")
    if feedback.effects:
        print("Effects:")
        for effect in feedback.effects:
            print(f"  {effect}")
    return 0


def _cmd_interests(args: argparse.Namespace) -> int:
    profile = _build_personalization_service().build_interest_profile()
    print(f"Feedback: {profile['total_feedback']}")
    print(f"Positive: {profile['positive_feedback']}")
    print(f"Negative: {profile['negative_feedback']}")
    print(f"Message style: {profile['message_style']}")
    if profile["top_topics"]:
        print("Top topics:")
        for item in profile["top_topics"]:
            print(f"  {item['topic']}: {item['score']}")
    return 0


async def _cmd_ingest(args: argparse.Namespace) -> int:
    repo = _build_repository()
    ingestor = ExternalSourceIngestor(repo, llm_service=_build_llm_service())
    fragments = []

    for file_path in args.file or []:
        fragments.append(await ingestor.ingest_file(file_path))
    for url in args.url or []:
        fragments.append(await ingestor.ingest_url(url))
    if args.text:
        fragments.append(await ingestor.ingest_text(" ".join(args.text)))

    if not fragments:
        raise ValueError("No sources provided. Pass --file, --url, or text arguments.")

    print(f"Ingested sources: {len(fragments)}")
    print(f"Fragments: {', '.join(fragment.id for fragment in fragments)}")
    print(f"Total nodes: {repo.get_stats()['total_nodes']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="exocortex", description="Exocortex CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Extract and store knowledge from text")
    add_parser.add_argument("text", nargs="*", help="Text to add")
    add_parser.add_argument("--file", help="Read text from a UTF-8 file")
    add_parser.add_argument("--stdin", action="store_true", help="Read text from stdin")
    add_parser.add_argument("--source-type", default="manual", help="Source type label")
    add_parser.add_argument("--source-url", default=None, help="Optional source URL")
    add_parser.set_defaults(func=_cmd_add)

    manual_parser = subparsers.add_parser(
        "add-manual",
        help="Store selected text as a graph node without LLM extraction",
    )
    manual_parser.add_argument("text", nargs="*", help="Selected text to store")
    manual_parser.add_argument("--file", help="Read selected text from a UTF-8 file")
    manual_parser.add_argument("--stdin", action="store_true", help="Read selected text from stdin")
    manual_parser.add_argument("--source-type", default="manual_selection", help="Source type label")
    manual_parser.add_argument("--source-url", default=None, help="Optional source URL or file path")
    manual_parser.add_argument("--document-title", default=None, help="Optional document title")
    manual_parser.set_defaults(func=_cmd_add_manual)

    stats_parser = subparsers.add_parser("stats", help="Show graph statistics")
    stats_parser.set_defaults(func=_cmd_stats)

    list_parser = subparsers.add_parser("list", help="List nodes")
    list_parser.add_argument("--limit", type=int, default=50)
    list_parser.set_defaults(func=_cmd_list)

    search_parser = subparsers.add_parser("search", help="Search nodes")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=50)
    search_parser.set_defaults(func=_cmd_search)

    forgotten_parser = subparsers.add_parser("forgotten", help="List forgotten nodes")
    forgotten_parser.add_argument("--threshold", type=float, default=0.3)
    forgotten_parser.add_argument("--limit", type=int, default=50)
    forgotten_parser.set_defaults(func=_cmd_forgotten)

    clear_parser = subparsers.add_parser("clear", help="Remove persisted graph files")
    clear_parser.set_defaults(func=_cmd_clear)

    analyze_parser = subparsers.add_parser("analyze", help="Run the proactive agent once")
    analyze_parser.add_argument("--no-save", action="store_true", help="Do not save generated digest")
    analyze_parser.set_defaults(func=_cmd_analyze)

    digest_parser = subparsers.add_parser("digest", help="Show the latest proactive digest")
    digest_parser.set_defaults(func=_cmd_digest)

    inbox_parser = subparsers.add_parser("inbox", help="List saved insights with feedback status")
    inbox_parser.add_argument("--limit", type=int, default=50)
    inbox_parser.add_argument(
        "--include-reacted",
        action="store_true",
        help="Include insights that already have feedback",
    )
    inbox_parser.set_defaults(func=_cmd_inbox)

    react_parser = subparsers.add_parser("react", help="React to a saved insight")
    react_parser.add_argument("insight_id")
    react_parser.add_argument(
        "action",
        help="Reaction action, e.g. confirm, reject, useful, ignore, choose_left",
    )
    react_parser.add_argument("--note", default=None, help="Optional note or refinement")
    react_parser.set_defaults(func=_cmd_react)

    interests_parser = subparsers.add_parser("interests", help="Show personalization profile")
    interests_parser.set_defaults(func=_cmd_interests)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest external text sources")
    ingest_parser.add_argument("text", nargs="*", help="Direct text to ingest")
    ingest_parser.add_argument("--file", action="append", help="Read an external UTF-8 file")
    ingest_parser.add_argument("--url", action="append", help="Fetch and ingest a text URL")
    ingest_parser.set_defaults(func=_cmd_ingest)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        if asyncio.iscoroutine(result):
            return asyncio.run(result)
        return result
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
