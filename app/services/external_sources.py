"""External source ingestion helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

from app.core.models import KnowledgeFragment
from app.core.repository import GraphRepository
from app.llm.extraction import LLMService, extract_and_store


class ExternalSourceIngestor:
    """Import text from files, URLs, or direct payloads into the knowledge graph."""

    def __init__(
        self,
        repository: GraphRepository,
        llm_service: Optional[LLMService] = None,
    ) -> None:
        self.repository = repository
        self.llm_service = llm_service

    async def ingest_text(
        self,
        text: str,
        source_type: str = "external",
        source_url: Optional[str] = None,
    ) -> KnowledgeFragment:
        """Extract and store a direct text payload."""
        return await extract_and_store(
            text=text,
            repository=self.repository,
            source_type=source_type,
            source_url=source_url,
            llm_service=self.llm_service,
        )

    async def ingest_file(
        self,
        path: str | Path,
        source_type: str = "file",
    ) -> KnowledgeFragment:
        """Read a UTF-8 file and ingest its contents."""
        file_path = Path(path)
        text = file_path.read_text(encoding="utf-8")
        return await self.ingest_text(
            text=text,
            source_type=source_type,
            source_url=str(file_path),
        )

    async def ingest_url(
        self,
        url: str,
        timeout: int = 15,
        source_type: str = "url",
    ) -> KnowledgeFragment:
        """Fetch a text-like URL and ingest the response body."""
        request = Request(url, headers={"User-Agent": "Exocortex/0.1"})
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            text = response.read().decode(charset, errors="replace")
        return await self.ingest_text(
            text=text,
            source_type=source_type,
            source_url=url,
        )
