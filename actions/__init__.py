# jetup/actions/__init__.py
"""
Actions package for Jetup.
Provides stub implementation for preAction/postAction compatibility.

In Jetup we don't use the full action system from old Talentir,
but templates expect these modules to exist.
"""
import logging
from typing import Dict

logger = logging.getLogger(__name__)

# Empty registries (stubs)
PRE_ACTION_REGISTRY: Dict[str, str] = {}
POST_ACTION_REGISTRY: Dict[str, str] = {}


def register_preaction(name: str, path: str) -> None:
    """
    Stub for registering preAction.

    Args:
        name: Action name
        path: Module path (not used in stub)
    """
    logger.debug(f"register_preaction called (stub): {name} -> {path}")


def register_postaction(name: str, path: str) -> None:
    """
    Stub for registering postAction.

    Args:
        name: Action name
        path: Module path (not used in stub)
    """
    logger.debug(f"register_postaction called (stub): {name} -> {path}")


def get_registry(action_type: str) -> Dict[str, str]:
    """
    Get action registry (empty stubs).

    Args:
        action_type: 'pre' or 'post'

    Returns:
        Empty dictionary
    """
    if action_type.lower() == "pre":
        return PRE_ACTION_REGISTRY
    elif action_type.lower() == "post":
        return POST_ACTION_REGISTRY
    else:
        raise ValueError(f"Unknown action type: {action_type}")


def initialize_registries() -> None:
    """
    Initialize empty registries.
    Called by system_services during startup.
    """
    logger.info("Initialized empty action registries (stub mode)")


__all__ = [
    'PRE_ACTION_REGISTRY',
    'POST_ACTION_REGISTRY',
    'register_preaction',
    'register_postaction',
    'get_registry',
    'initialize_registries',
]