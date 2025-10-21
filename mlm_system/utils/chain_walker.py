# mlm_system/utils/chain_walker.py
"""
Safe MLM chain walking utilities.
Prevents infinite loops and validates chain integrity.
"""
from typing import Optional, Callable, Set, List
from sqlalchemy.orm import Session
import logging

from models.user import User
from config import Config

logger = logging.getLogger(__name__)


class ChainWalker:
    """
    Safe utilities for walking MLM upline/downline chains.
    Prevents infinite loops and validates chain integrity.
    """

    def __init__(self, session: Session):
        self.session = session
        self._default_referrer_id = None

    def get_default_referrer_id(self) -> Optional[int]:
        """Get DEFAULT_REFERRER telegram ID from config."""
        if self._default_referrer_id is None:
            default_ref = Config.get(Config.DEFAULT_REFERRER_ID)
            if default_ref:
                self._default_referrer_id = int(default_ref)
        return self._default_referrer_id

    def is_system_root(self, user: User) -> bool:
        """
        Check if user is system root (DEFAULT_REFERRER with upline=self).

        Args:
            user: User to check

        Returns:
            True if user is system root
        """
        default_ref_id = self.get_default_referrer_id()
        return (
                default_ref_id and
                user.telegramID == default_ref_id and
                user.upline == user.telegramID
        )

    def walk_upline(
            self,
            start_user: User,
            callback: Callable[[User, int], bool],
            max_depth: int = 50
    ) -> int:
        """
        Safely walk up the upline chain, calling callback for each user.

        Args:
            start_user: Starting user
            callback: Function(user, level) -> continue_walking (bool)
            max_depth: Maximum depth to prevent runaway loops

        Returns:
            Number of users processed

        Example:
            def process_upline(user, level):
                print(f"Level {level}: {user.userID}")
                return True  # Continue walking

            walker.walk_upline(user, process_upline)
        """
        current_user = start_user
        level = 1
        processed = 0
        visited = set()

        while current_user.upline and level <= max_depth:
            # CRITICAL: Check for system root
            if self.is_system_root(current_user):
                logger.debug(f"Reached system root at level {level}")
                break

            # Check for cycles
            if current_user.userID in visited:
                logger.error(f"Cycle detected at user {current_user.userID}")
                break

            visited.add(current_user.userID)

            # Get upline user
            upline_user = self.session.query(User).filter_by(
                telegramID=current_user.upline
            ).first()

            if not upline_user:
                logger.warning(
                    f"Upline not found: telegramID={current_user.upline} "
                    f"for user {current_user.userID}"
                )
                break

            # Call callback
            should_continue = callback(upline_user, level)
            processed += 1

            if not should_continue:
                break

            current_user = upline_user
            level += 1

        if level > max_depth:
            logger.error(f"Max depth ({max_depth}) exceeded starting from user {start_user.userID}")

        return processed

    def walk_downline(
            self,
            start_user: User,
            callback: Callable[[User, int], None],
            max_depth: int = 50,
            visited: Optional[Set[int]] = None
    ) -> int:
        """
        Safely walk down the downline tree recursively.

        Args:
            start_user: Starting user
            callback: Function(user, level) to call for each user
            max_depth: Maximum depth
            visited: Set of visited user IDs (for cycle detection)

        Returns:
            Total number of users processed
        """
        if visited is None:
            visited = set()

        if max_depth <= 0:
            logger.warning(f"Max depth reached at user {start_user.userID}")
            return 0

        # Check for cycles
        if start_user.userID in visited:
            logger.error(f"Cycle detected in downline at user {start_user.userID}")
            return 0

        visited.add(start_user.userID)

        # Get direct referrals
        referrals = self.session.query(User).filter(
            User.upline == start_user.telegramID
        ).all()

        processed = 0

        for referral in referrals:
            # Don't process system root as downline
            if self.is_system_root(referral):
                continue

            # Call callback
            callback(referral, max_depth)
            processed += 1

            # Recurse
            processed += self.walk_downline(
                referral,
                callback,
                max_depth - 1,
                visited
            )

        return processed

    def get_upline_chain(self, user: User, max_depth: int = 50) -> List[User]:
        """
        Get list of all users in upline chain.

        Args:
            user: Starting user
            max_depth: Maximum depth

        Returns:
            List of users from immediate upline to root
        """
        chain = []

        def collect(upline_user, level):
            chain.append(upline_user)
            return True  # Continue

        self.walk_upline(user, collect, max_depth)
        return chain

    def count_downline(self, user: User, max_depth: int = 50) -> int:
        """
        Count total number of users in downline.

        Args:
            user: Starting user
            max_depth: Maximum depth

        Returns:
            Total count of downline users
        """
        count = [0]  # Use list to allow modification in callback

        def counter(downline_user, level):
            count[0] += 1

        self.walk_downline(user, counter, max_depth)
        return count[0]