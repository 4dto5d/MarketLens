from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from local_presence_miner.config import AppConfig


def configure_logging(config: AppConfig) -> None:
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(config.log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
