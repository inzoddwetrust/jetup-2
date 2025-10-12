# jetup/actions/loader.py
"""
Action loader stubs for Jetup compatibility.
Templates may try to execute preAction/postAction, so we provide stubs.
"""
import logging
from typing import Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)


def load_action(action_type: str, action_name: str) -> Optional[Callable]:
    """
    Stub for loading actions - always returns None.

    Args:
        action_type: 'pre' or 'post'
        action_name: Action name

    Returns:
        None (action not found)
    """
    if action_name:  # Only log if name is not empty
        logger.debug(f"load_action called for {action_type}Action '{action_name}' (stub)")
    return None


def get_action_metadata(action_type: str, action_name: str) -> Optional[Dict[str, Any]]:
    """
    Stub for getting action metadata - always returns None.

    Args:
        action_type: 'pre' or 'post'
        action_name: Action name

    Returns:
        None (no metadata)
    """
    if action_name:
        logger.debug(f"get_action_metadata called for {action_type}Action '{action_name}' (stub)")
    return None


async def execute_preaction(
        name: str,
        user,
        context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Stub for executing preAction - always returns original context unchanged.

    PreActions normally modify context before sending a message.
    In stub mode, we just pass through.

    Args:
        name: PreAction name
        user: User object
        context: Variables context

    Returns:
        Original context unchanged
    """
    if name:
        logger.debug(f"execute_preaction called for '{name}' (stub - no action taken)")
    return context


async def execute_postaction(
        name: str,
        user,
        context: Dict[str, Any],
        callback_data: Optional[str] = None
) -> Optional[str]:
    """
    Stub for executing postAction - always returns None.

    PostActions normally return next state after button press.
    In stub mode, we return None (no state transition).

    Args:
        name: PostAction name
        user: User object
        context: Variables context
        callback_data: Callback data from button press

    Returns:
        None (no state transition)
    """
    if name:
        logger.debug(
            f"execute_postaction called for '{name}' "
            f"with callback_data: {callback_data} (stub - no action taken)"
        )
    return None


def initialize_actions() -> None:
    """
    Initialize action system (stub - does nothing).
    Called by system_services during startup.
    """
    try:
        from actions import initialize_registries
        initialize_registries()
        logger.info("Action system initialized in stub mode")
    except Exception as e:
        logger.error(f"Error initializing action registries: {e}", exc_info=True)


__all__ = [
    'load_action',
    'get_action_metadata',
    'execute_preaction',
    'execute_postaction',
    'initialize_actions',
]