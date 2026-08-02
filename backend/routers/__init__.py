"""FastAPI Sub-Routers for MinerWatch."""
from .miners import router as miners_router
from .benchmark import router as benchmark_router
from .guardian import router as guardian_router
from .discovery import router as discovery_router
from .system import router as system_router

__all__ = [
    "miners_router",
    "benchmark_router",
    "guardian_router",
    "discovery_router",
    "system_router",
]
