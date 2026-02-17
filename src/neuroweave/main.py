"""NeuroWeave entry point."""

from neuroweave.config import NeuroWeaveConfig
from neuroweave.logging import configure_logging, get_logger


def main() -> None:
    """Run the NeuroWeave conversation loop."""
    config = NeuroWeaveConfig.load()
    configure_logging(config)

    log = get_logger("main")
    log.info(
        "neuroweave.started",
        version="0.1.0",
        llm_provider=config.llm_provider.value,
        graph_backend=config.graph_backend.value,
        server_port=config.server_port,
    )
    log.info("neuroweave.ready", status="not yet implemented — see IMPLEMENTATION_PLAN.md")


if __name__ == "__main__":
    main()
