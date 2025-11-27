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

    def count_active_downline(self, user: User, max_depth: int = 50) -> int:
        """
        Count active users in entire downline structure.

        Active partner = user with isActive == True anywhere in downline.
        Uses walk_downline for safe recursive traversal.

        Args:
            user: Starting user
            max_depth: Maximum depth for recursion

        Returns:
            Count of users with isActive == True
        """
        count = [0]  # Use list to allow modification in callback

        def counter(downline_user, level):
            if downline_user.isActive:
                count[0] += 1

        self.walk_downline(user, counter, max_depth)
        return count[0]

    def validate_default_referrer(self) -> bool:
        """
        Validate that DEFAULT_REFERRER exists and has upline=self.

        Returns:
            True if valid, False otherwise
        """
        default_ref_id = self.get_default_referrer_id()
        if not default_ref_id:
            logger.error("DEFAULT_REFERRER_ID not configured!")
            return False

        root_user = self.session.query(User).filter_by(
            telegramID=default_ref_id
        ).first()

        if not root_user:
            logger.error(f"DEFAULT_REFERRER (telegramID={default_ref_id}) not found in DB!")
            return False

        if root_user.upline != root_user.telegramID:
            logger.error(
                f"DEFAULT_REFERRER (userID={root_user.userID}) has "
                f"upline={root_user.upline}, should be {root_user.telegramID}"
            )
            return False

        logger.info(f"✓ DEFAULT_REFERRER validation passed (userID={root_user.userID})")
        return True

    def validate_chain_to_root(self, user_id: int) -> bool:
        """
        Validate that user's upline chain reaches DEFAULT_REFERRER.

        Args:
            user_id: User ID to validate

        Returns:
            True if chain is valid, False otherwise
        """
        default_ref_id = self.get_default_referrer_id()
        if not default_ref_id:
            logger.error("DEFAULT_REFERRER_ID not configured!")
            return False

        user = self.session.query(User).filter_by(userID=user_id).first()
        if not user:
            logger.error(f"User {user_id} not found")
            return False

        # Walk up the chain
        visited = set()
        current_user = user
        max_depth = 100  # Safety limit
        depth = 0

        while depth < max_depth:
            # Check if reached root
            if current_user.telegramID == default_ref_id:
                logger.debug(f"User {user_id} chain is valid (depth={depth})")
                return True

            # Check for self-reference (should only be root)
            if current_user.upline == current_user.telegramID:
                if current_user.telegramID == default_ref_id:
                    return True  # Valid root
                else:
                    logger.error(
                        f"Invalid self-reference: user {current_user.userID} "
                        f"(telegramID={current_user.telegramID}) has upline=self "
                        f"but is NOT DEFAULT_REFERRER"
                    )
                    return False

            # Check for cycles
            if current_user.userID in visited:
                logger.error(f"Cycle detected in chain for user {user_id}")
                return False

            visited.add(current_user.userID)

            # Get upline
            if not current_user.upline:
                logger.error(
                    f"Broken chain: user {current_user.userID} has no upline "
                    f"and is not DEFAULT_REFERRER"
                )
                return False

            upline_user = self.session.query(User).filter_by(
                telegramID=current_user.upline
            ).first()

            if not upline_user:
                logger.error(
                    f"Broken chain: upline telegramID={current_user.upline} "
                    f"not found for user {current_user.userID}"
                )
                return False

            current_user = upline_user
            depth += 1

        logger.error(f"Chain too deep (>{max_depth}) for user {user_id}")
        return False

    def find_orphan_branches(self) -> Set[int]:
        """
        Find all users whose chains don't reach DEFAULT_REFERRER.

        Returns:
            Set of user IDs in orphan branches
        """
        default_ref_id = self.get_default_referrer_id()
        if not default_ref_id:
            logger.error("DEFAULT_REFERRER_ID not configured!")
            return set()

        orphans = set()
        all_users = self.session.query(User).filter(
            User.telegramID != default_ref_id
        ).all()

        for user in all_users:
            if not self.validate_chain_to_root(user.userID):
                orphans.add(user.userID)

        if orphans:
            logger.warning(f"Found {len(orphans)} users in orphan branches: {orphans}")
        else:
            logger.info("No orphan branches found")

        return orphans