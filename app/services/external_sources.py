"""External source ingestion helpers."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
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
        max_response_bytes: int = 1_000_000,
        allow_private_hosts: bool = False,
    ) -> None:
        self.repository = repository
        self.llm_service = llm_service
        self.max_response_bytes = max_response_bytes
        self.allow_private_hosts = allow_private_hosts

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
        self._validate_url(url)
        text = await asyncio.to_thread(self._fetch_text_url, url, timeout)
        return await self.ingest_text(
            text=text,
            source_type=source_type,
            source_url=url,
        )

    def _fetch_text_url(self, url: str, timeout: int) -> str:
        request = Request(url, headers={"User-Agent": "Exocortex/0.1"})
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            if not self._is_text_content_type(content_type):
                raise ValueError(f"Unsupported content-type: {content_type}")
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(self.max_response_bytes + 1)
        if len(body) > self.max_response_bytes:
            raise ValueError("URL response exceeds maximum allowed size")
        return body.decode(charset, errors="replace")

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Only http and https URLs are allowed")
        if not parsed.hostname:
            raise ValueError("URL host is required")
        if not self.allow_private_hosts and self._is_private_host(parsed.hostname):
            raise ValueError("Private, loopback, and localhost URLs are not allowed")

    def _is_private_host(self, host: str) -> bool:
        if host.lower() == "localhost":
            return True
        try:
            addresses = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise ValueError(f"Cannot resolve URL host: {host}") from exc
        for item in addresses:
            address = item[4][0]
            ip = ipaddress.ip_address(address)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                return True
        return False

    def _is_text_content_type(self, content_type: str) -> bool:
        if content_type.startswith("text/"):
            return True
        return content_type in {"application/json", "application/xml", "application/xhtml+xml"}
