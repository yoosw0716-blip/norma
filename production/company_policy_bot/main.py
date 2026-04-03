from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from app.config import Settings
from app.slack_bot import CompanyPolicyBot


BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    settings = Settings.from_env()
    search_config_path = Path(settings.search_config_path)
    if not search_config_path.is_absolute():
        search_config_path = (BASE_DIR / search_config_path).resolve()
    settings = replace(settings, search_config_path=str(search_config_path))
    settings.validate()
    logging.getLogger(__name__).info("Using search config: %s", settings.search_config_path)
    CompanyPolicyBot(settings).start()


if __name__ == "__main__":
    main()
