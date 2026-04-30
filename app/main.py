"""Application entry point for `python -m app.main`."""

from __future__ import annotations

import argparse
from typing import Optional

import uvicorn

from app.config import load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Exocortex API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    load_settings()
    uvicorn.run(
        "app.api.routes:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
