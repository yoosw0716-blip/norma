from __future__ import annotations

import logging

from app.config import Settings
from app.slack_bot import CompanyPolicyBot


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    settings = Settings.from_env()
    settings.validate()
    CompanyPolicyBot(settings).start()


if __name__ == "__main__":
    main()
