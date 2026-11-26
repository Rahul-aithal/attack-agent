"""Entry point for the HTTP/WebSocket API server (``attack-agent-serve``)."""

from __future__ import annotations

import uvicorn

from attack_agent.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "attack_agent.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
