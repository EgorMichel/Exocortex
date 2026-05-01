"""Task scheduler integration for proactive agents."""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from app.agents.proactive import AgentSettings, ProactiveAgent
from app.core.repository import GraphRepository


logger = logging.getLogger(__name__)


def build_agent_scheduler(
    repository: GraphRepository,
    llm_service=None,
    interval_minutes: int = 1440,
    agent_settings: Optional[AgentSettings] = None,
) -> BackgroundScheduler:
    """Create a background scheduler that periodically runs graph analysis."""
    scheduler = BackgroundScheduler()
    agent = ProactiveAgent(
        repository=repository,
        llm_service=llm_service,
        settings=agent_settings,
    )

    def run_agent() -> None:
        try:
            agent.analyze_sync(save=True)
        except Exception:
            logger.exception("Scheduled proactive agent run failed")

    scheduler.add_job(
        run_agent,
        "interval",
        minutes=interval_minutes,
        id="proactive_agent_analysis",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler
