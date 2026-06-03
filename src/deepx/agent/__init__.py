"""Agent module — routing, caching, compression."""
from deepx.agent.router import route_model
from deepx.agent.prefix_cache import PrefixCache

__all__ = ["route_model", "PrefixCache"]