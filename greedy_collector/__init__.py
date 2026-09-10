"""Greedy Collector public-blockchain risk and screening plugin."""

from .config import GreedyCollectorSettings, get_settings
from .router import router
from .services import GreedyCollectorService

__all__ = ["GreedyCollectorService", "GreedyCollectorSettings", "get_settings", "router"]
__version__ = "0.1.0"
