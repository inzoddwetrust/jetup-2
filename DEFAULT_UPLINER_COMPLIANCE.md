# DEFAULT_UPLINER System Root Compliance Analysis

**Date**: 2025-10-21
**Status**: ❌ **CRITICAL SYSTEM DESIGN VIOLATION**
**Purpose**: Verify DEFAULT_UPLINER as system root with self-reference stop mechanism

---

## Executive Summary

### ❌ CATASTROPHIC ISSUES FOUND

1. **INFINITE LOOPS**: MLM cycles don't check for self-reference → INFINITE LOOP at DEFAULT_UPLINER
2. **NO CHAIN VALIDATION**: No verification that chains end at DEFAULT_UPLINER
3. **NO ORPHAN DETECTION**: No mechanism to ban broken branches
4. **DESIGN IGNORED**: Self-reference stop mechanism NOT USED in MLM code

**Impact**: System will HANG when processing any user in complete structure.

---

## Requirement Specification

From user:
> DEFAULT_UPLINER - это корень всей системы, все структуры ОБЯЗАТЕЛЬНО И ВСЕГДА кончаются на нем,
> НИКАК И НИКОГДА иначе быть не может. Если такая ситуация создается, ВЕТКА ДОЛЖНА БЫТЬ ЗАБАНЕНА В БД НАВСЕГДА.
>
> DEFAULT_UPLINER в БД - это ЕДИНСТВЕННЫЙ ЮЗЕР, который ссылается сам на себя.
> Это сделано для использования рекурсий в начислении бонусов, анализе структур, и всем прочем.
> Это ВЕЗДЕ в коде надо было использовать.

**Translation**:
- DEFAULT_UPLINER is the root of entire system
- ALL structures MUST ALWAYS end at him
- If not - branch MUST BE BANNED FOREVER
- DEFAULT_UPLINER is the ONLY user with self-reference (upline = telegramID)
- This is designed for stopping recursions in bonuses, structure analysis, etc.
- This MUST BE USED EVERYWHERE in code

---

## Critical Issue #1: INFINITE LOOPS in MLM Cycles

### ❌ Commission Service (commission_service.py:88-134)

#### Current Code:
```python
async def _calculateDifferentialCommissions(self, purchase: Purchase) -> List[Dict]:
    """Calculate differential commissions up the chain."""
    commissions = []
    currentUser = purchase.user
    lastPercentage = Decimal("0")
    level = 1

    # Walk up the upline chain
    while currentUser.upline:
        uplineUser = self.session.query(User).filter_by(
            telegramID=currentUser.upline
        ).first()

        if not uplineUser:
            break

        # ❌ NO CHECK FOR SELF-REFERENCE!

        # Calculate and add commission
        commissions.append({...})

        currentUser = uplineUser  # ← MOVES TO NEXT USER
        level += 1

        # Stop at max percentage
        if lastPercentage >= Decimal("0.18"):
            break

    return commissions
```

#### The Problem:

**Chain**: User A → User B → User C → DEFAULT_UPLINER (upline=itself)

**Execution**:
1. currentUser = User A
2. while currentUser.upline: ✓ (has upline: User B)
3. uplineUser = User B
4. currentUser = User B
5. while currentUser.upline: ✓ (has upline: User C)
6. uplineUser = User C
7. currentUser = User C
8. while currentUser.upline: ✓ (has upline: DEFAULT_UPLINER)
9. uplineUser = DEFAULT_UPLINER
10. currentUser = DEFAULT_UPLINER
11. **while currentUser.upline: ✓ (has upline: DEFAULT_UPLINER itself!)** ← INFINITE LOOP STARTS
12. uplineUser = DEFAULT_UPLINER (queries itself)
13. currentUser = DEFAULT_UPLINER
14. **GOTO 11** ← INFINITE LOOP

**Result**:
- Process HANGS FOREVER
- Database queries in infinite loop
- Memory consumption grows
- System UNUSABLE

#### Required Fix:
```python
while currentUser.upline:
    # CHECK FOR SELF-REFERENCE (stop at root)
    if currentUser.upline == currentUser.telegramID:
        logger.debug(
            f"Reached system root (self-reference) at user {currentUser.userID}, "
            f"stopping commission chain"
        )
        break

    uplineUser = self.session.query(User).filter_by(
        telegramID=currentUser.upline
    ).first()

    if not uplineUser:
        logger.error(
            f"ORPHAN BRANCH: User {currentUser.userID} has upline "
            f"{currentUser.upline} that doesn't exist!"
        )
        # TODO: Flag branch for admin review/ban
        break

    # ... rest of logic
```

**Location**: commission_service.py:88 (start of while loop)
**Priority**: ❌ **CRITICAL - SYSTEM BREAKING**

---

### ❌ Volume Service (volume_service.py:71-94)

#### Current Code:
```python
async def _updateTeamVolumeChain(self, user: User, amount: Decimal):
    """Update team volumes up the upline chain."""
    currentUser = user

    while currentUser.upline:
        uplineUser = self.session.query(User).filter_by(
            telegramID=currentUser.upline
        ).first()

        if not uplineUser:
            break

        # ❌ NO CHECK FOR SELF-REFERENCE!

        # Update team volume
        uplineUser.teamVolumeTotal = (
            uplineUser.teamVolumeTotal or Decimal("0")
        ) + amount

        uplineUser.mlmVolumes["teamTotal"] = str(uplineUser.teamVolumeTotal)

        logger.info(
            f"Updated TV for user {uplineUser.userID}: "
            f"total={uplineUser.teamVolumeTotal}"
        )

        currentUser = uplineUser  # ← NO SELF-REFERENCE CHECK!
```

#### The Problem:

**Same infinite loop as commission_service**.

When reaches DEFAULT_UPLINER:
- currentUser = DEFAULT_UPLINER
- while currentUser.upline: ✓ (upline = itself)
- Queries itself
- Updates itself
- INFINITE LOOP

#### Required Fix:
```python
while currentUser.upline:
    # STOP AT SELF-REFERENCE (system root)
    if currentUser.upline == currentUser.telegramID:
        logger.debug(
            f"Reached system root at user {currentUser.userID}, "
            f"stopping volume chain"
        )
        break

    uplineUser = self.session.query(User).filter_by(
        telegramID=currentUser.upline
    ).first()

    if not uplineUser:
        logger.error(
            f"ORPHAN BRANCH: User {currentUser.userID} upline "
            f"{currentUser.upline} not found"
        )
        break

    # ... rest of logic
```

**Location**: volume_service.py:71 (start of while loop)
**Priority**: ❌ **CRITICAL - SYSTEM BREAKING**

---

## Critical Issue #2: NO Chain Validation

### Missing: Validation that chains end at DEFAULT_UPLINER

**There is NO code that validates**:
1. When user created, check their upline chain reaches DEFAULT_UPLINER
2. Periodic validation of all user chains
3. Detection of "orphan branches" (chains that don't end at root)

#### Required Implementation:

**File**: `mlm_system/services/structure_validator.py` (NEW FILE)

```python
# mlm_system/services/structure_validator.py
"""
Structure validation service.
Ensures all upline chains end at DEFAULT_UPLINER.
"""
from sqlalchemy.orm import Session
from models import User
from config import Config
import logging

logger = logging.getLogger(__name__)

class StructureValidator:
    """Validates MLM structure integrity."""

    def __init__(self, session: Session):
        self.session = session
        self.default_upliner_id = Config.get(Config.DEFAULT_REFERRER_ID)

    async def validateUserChain(self, user: User) -> dict:
        """
        Validate that user's upline chain ends at DEFAULT_UPLINER.

        Returns:
            {
                "valid": bool,
                "reason": str,
                "chain_length": int,
                "orphan": bool
            }
        """
        visited = set()
        current = user
        chain_length = 0
        max_depth = 100  # Prevent infinite loop in broken chains

        while current.upline:
            chain_length += 1

            # Check for infinite loop
            if current.telegramID in visited:
                return {
                    "valid": False,
                    "reason": f"Circular reference detected at {current.telegramID}",
                    "chain_length": chain_length,
                    "orphan": True
                }

            if chain_length > max_depth:
                return {
                    "valid": False,
                    "reason": "Chain too long (>100), possible infinite loop",
                    "chain_length": chain_length,
                    "orphan": True
                }

            visited.add(current.telegramID)

            # Check for self-reference (should be DEFAULT_UPLINER)
            if current.upline == current.telegramID:
                # Found self-reference - verify it's DEFAULT_UPLINER
                if current.telegramID == self.default_upliner_id:
                    return {
                        "valid": True,
                        "reason": "Chain ends at DEFAULT_UPLINER (self-reference)",
                        "chain_length": chain_length,
                        "orphan": False
                    }
                else:
                    return {
                        "valid": False,
                        "reason": f"Non-root user {current.telegramID} has self-reference",
                        "chain_length": chain_length,
                        "orphan": True
                    }

            # Get next upline
            uplineUser = self.session.query(User).filter_by(
                telegramID=current.upline
            ).first()

            if not uplineUser:
                return {
                    "valid": False,
                    "reason": f"Upline {current.upline} not found",
                    "chain_length": chain_length,
                    "orphan": True
                }

            current = uplineUser

        # Reached user with no upline (shouldn't happen)
        return {
            "valid": False,
            "reason": "Chain ends without reaching root",
            "chain_length": chain_length,
            "orphan": True
        }

    async def validateAllChains(self) -> dict:
        """
        Validate all user chains in database.

        Returns:
            {
                "total_users": int,
                "valid_chains": int,
                "orphan_branches": [userID, ...],
                "circular_refs": [userID, ...],
                "other_errors": [userID, ...]
            }
        """
        all_users = self.session.query(User).all()
        results = {
            "total_users": len(all_users),
            "valid_chains": 0,
            "orphan_branches": [],
            "circular_refs": [],
            "other_errors": []
        }

        for user in all_users:
            # Skip DEFAULT_UPLINER itself
            if user.telegramID == self.default_upliner_id:
                continue

            validation = await self.validateUserChain(user)

            if validation["valid"]:
                results["valid_chains"] += 1
            else:
                if "Circular" in validation["reason"]:
                    results["circular_refs"].append(user.userID)
                elif validation["orphan"]:
                    results["orphan_branches"].append(user.userID)
                else:
                    results["other_errors"].append(user.userID)

                logger.error(
                    f"Invalid chain for user {user.userID}: {validation['reason']}"
                )

        return results

    async def banOrphanBranch(self, user_id: int, reason: str):
        """
        Ban user and all their downline (orphan branch).

        This is called when chain doesn't end at DEFAULT_UPLINER.
        """
        user = self.session.query(User).filter_by(userID=user_id).first()
        if not user:
            return

        # Get all downline recursively
        to_ban = [user]
        queue = [user]

        while queue:
            current = queue.pop(0)

            # Get direct referrals
            downline = self.session.query(User).filter_by(
                upline=current.telegramID
            ).all()

            for child in downline:
                if child not in to_ban:
                    to_ban.append(child)
                    queue.append(child)

        # Ban all users in orphan branch
        for user_to_ban in to_ban:
            user_to_ban.status = "banned"
            if not user_to_ban.notes:
                user_to_ban.notes = ""
            user_to_ban.notes += f"\n[AUTO-BAN] Orphan branch: {reason}"

        self.session.commit()

        logger.critical(
            f"BANNED orphan branch: {len(to_ban)} users starting from "
            f"user {user_id}. Reason: {reason}"
        )

        return len(to_ban)
```

**Priority**: ❌ **CRITICAL**

---

## Critical Issue #3: DEFAULT_UPLINER Not Initialized Correctly

### Missing: Initialization of DEFAULT_UPLINER User

**There is NO code that ensures**:
1. DEFAULT_UPLINER user exists in database
2. DEFAULT_UPLINER has `upline = telegramID` (self-reference)
3. This is verified on system startup

#### Required Implementation:

**File**: `services/system_init.py` (NEW FILE or add to existing)

```python
async def initializeDefaultUpliner(session: Session):
    """
    Ensure DEFAULT_UPLINER exists with self-reference.

    Called on system startup.
    """
    from config import Config
    from models import User

    default_id = Config.get(Config.DEFAULT_REFERRER_ID)

    if not default_id:
        logger.critical("DEFAULT_REFERRER_ID not configured!")
        raise ValueError("DEFAULT_REFERRER_ID not configured")

    # Check if exists
    default_user = session.query(User).filter_by(
        telegramID=default_id
    ).first()

    if default_user:
        # Verify self-reference
        if default_user.upline != default_user.telegramID:
            logger.critical(
                f"DEFAULT_UPLINER {default_id} exists but upline is "
                f"{default_user.upline}, NOT self-reference! FIXING..."
            )
            default_user.upline = default_user.telegramID
            session.commit()
            logger.info("Fixed DEFAULT_UPLINER self-reference")
        else:
            logger.info(f"DEFAULT_UPLINER {default_id} verified OK")
    else:
        # Create DEFAULT_UPLINER
        logger.warning(
            f"DEFAULT_UPLINER {default_id} not found, creating..."
        )

        default_user = User(
            userID=1,  # Always userID=1
            telegramID=default_id,
            upline=default_id,  # SELF-REFERENCE
            firstname="System",
            surname="Root",
            rank=None,
            isActive=False,
            status="active"
        )

        session.add(default_user)
        session.commit()

        logger.info(f"Created DEFAULT_UPLINER {default_id} with self-reference")

    return default_user
```

**Call on startup** (main.py or app initialization):
```python
async def startup():
    session = get_session()
    await initializeDefaultUpliner(session)
    # ... rest of startup
```

**Priority**: ❌ **CRITICAL**

---

## Critical Issue #4: User Creation Validation

### Current: No Chain Validation on Creation (models/user.py:134-148)

#### Current Code:
```python
if referrer_id:
    referrer = session.query(cls).filter_by(telegramID=referrer_id).first()
    if referrer:
        upline = referrer_id
    else:
        # Referrer not found, use default
        upline = Config.get(Config.DEFAULT_REFERRER_ID)
else:
    # No referrer provided, use default
    upline = Config.get(Config.DEFAULT_REFERRER_ID)

# ❌ NO VALIDATION that referrer's chain reaches DEFAULT_UPLINER!
```

#### The Problem:

If referrer itself is in an orphan branch, new user is also orphaned.

**Example**:
- User A has broken chain (doesn't reach DEFAULT_UPLINER)
- User B registers with referrer=User A
- User B is now also in orphan branch
- **Orphan branch grows!**

#### Required Fix:
```python
if referrer_id:
    referrer = session.query(cls).filter_by(telegramID=referrer_id).first()
    if referrer:
        # VALIDATE referrer's chain
        from mlm_system.services.structure_validator import StructureValidator

        validator = StructureValidator(session)
        validation = await validator.validateUserChain(referrer)

        if not validation["valid"]:
            logger.error(
                f"Referrer {referrer_id} has invalid chain: "
                f"{validation['reason']}. Using DEFAULT_UPLINER instead."
            )
            upline = Config.get(Config.DEFAULT_REFERRER_ID)
        else:
            upline = referrer_id
    else:
        # Referrer not found, use default
        upline = Config.get(Config.DEFAULT_REFERRER_ID)
else:
    # No referrer provided, use default
    upline = Config.get(Config.DEFAULT_REFERRER_ID)
```

**Location**: models/user.py:134-143
**Priority**: ❌ **HIGH**

---

## Summary of Issues

| Issue | File | Line | Impact | Status |
|-------|------|------|--------|--------|
| Infinite loop in commissions | commission_service.py | 88 | System hangs | ❌ CRITICAL |
| Infinite loop in volumes | volume_service.py | 71 | System hangs | ❌ CRITICAL |
| No chain validation | (missing) | N/A | Orphan branches grow | ❌ CRITICAL |
| No orphan detection | (missing) | N/A | Bad data persists | ❌ CRITICAL |
| No orphan banning | (missing) | N/A | Broken branches not cleaned | ❌ CRITICAL |
| DEFAULT_UPLINER not initialized | (missing) | N/A | Root may not exist | ❌ CRITICAL |
| No creation validation | user.py | 134 | Orphans can invite | ❌ HIGH |

**Total Critical Issues**: 7

---

## Existing Validation (NOT USED)

### Sync System Has Validation (sync_system/sync_config.py:316-330)

```python
def validate_upline(user_telegram_id: int, upline_value: int, session) -> int:
    """Валидация uplinerID с учетом бизнес-логики"""

    # DEFAULT_REFERRER может ссылаться сам на себя - это ОК!
    if user_telegram_id == config.DEFAULT_REFERRER_ID and upline_value == config.DEFAULT_REFERRER_ID:
        return upline_value

    # Остальные не могут ссылаться на себя
    if upline_value == user_telegram_id:
        raise ValueError(f"User {user_telegram_id} has self-reference as upline")

    # Проверяем существование
    upliner = session.query(User).filter_by(telegramID=upline_value).first()
    if not upliner:
        raise ValueError(f"Invalid upline {upline_value}: does not exist")

    return upline_value
```

**Also in sync_config.py:73**:
```python
'stop_recursion_at': config.DEFAULT_REFERRER_ID
```

### The Problem:

✅ Validation EXISTS
❌ Only used in sync_system (Google Sheets import)
❌ NOT used in:
- User creation (models/user.py)
- Commission calculation (commission_service.py)
- Volume calculation (volume_service.py)
- ANY MLM recursions

---

## Required Fixes Summary

### Phase 1: Stop Infinite Loops (EMERGENCY - 30 minutes)

1. **commission_service.py:88**
   - Add self-reference check in while loop
   - `if currentUser.upline == currentUser.telegramID: break`

2. **volume_service.py:71**
   - Add self-reference check in while loop
   - `if currentUser.upline == currentUser.telegramID: break`

**Result**: System stops hanging

---

### Phase 2: Structure Validation (HIGH PRIORITY - 2-3 hours)

3. **Create StructureValidator service**
   - validateUserChain() method
   - validateAllChains() method
   - banOrphanBranch() method

4. **Add validation on user creation** (models/user.py:134)
   - Validate referrer chain before accepting

5. **Add system initialization** (startup)
   - Ensure DEFAULT_UPLINER exists
   - Verify self-reference
   - Create if missing

**Result**: No orphan branches can be created

---

### Phase 3: Clean Existing Data (MAINTENANCE - 1-2 hours)

6. **Run validateAllChains() on existing database**
   - Identify orphan branches
   - Ban them or fix them
   - Log report

7. **Add periodic validation** (background job)
   - Run daily
   - Alert admins if issues found

**Result**: Existing bad data cleaned

---

## Testing Recommendations

After fixes implemented, test:

### Test 1: Infinite Loop Prevention
```python
# Create DEFAULT_UPLINER with self-reference
default_user = User(
    telegramID=526738615,
    upline=526738615  # Self-reference
)

# Create normal user chain
user_a = User(telegramID=111, upline=526738615)
user_b = User(telegramID=222, upline=111)

# Test commission calculation
purchase = Purchase(userID=user_b.userID, packPrice=1000)
commissions = await commission_service._calculateDifferentialCommissions(purchase)

# Should NOT hang, should return commissions for user_a and stop at DEFAULT_UPLINER
```

### Test 2: Chain Validation
```python
# Create orphan user (upline doesn't exist)
orphan = User(telegramID=999, upline=888)  # 888 doesn't exist

# Validate chain
validator = StructureValidator(session)
result = await validator.validateUserChain(orphan)

# Should return {"valid": False, "orphan": True}
```

### Test 3: User Creation with Orphan Referrer
```python
# Try to create user with orphan referrer
new_user = User.create_from_telegram_data(
    session=session,
    telegram_user=telegram_user,
    referrer_id=999  # Orphan
)

# Should fallback to DEFAULT_REFERRER_ID, NOT use orphan
assert new_user.upline == Config.get(Config.DEFAULT_REFERRER_ID)
```

---

## Conclusion

### Current Status: ❌ **0% COMPLIANT - SYSTEM BREAKING**

DEFAULT_UPLINER requirements are **COMPLETELY IGNORED** with **CATASTROPHIC CONSEQUENCES**:

1. ❌ **System HANGS on ANY commission/volume calculation** (infinite loops)
2. ❌ **No validation that chains end at root**
3. ❌ **No detection of orphan branches**
4. ❌ **No banning mechanism for broken branches**
5. ❌ **Self-reference stop pattern NOT USED in MLM code**

### Required Actions:

**Phase 1 (EMERGENCY)**: Fix infinite loops in 2 locations (30 minutes)
**Phase 2 (CRITICAL)**: Add structure validation (2-3 hours)
**Phase 3 (MAINTENANCE)**: Clean existing data (1-2 hours)

**Total effort**: 4-6 hours
**Priority**: ❌ **HIGHEST - SYSTEM IS BROKEN WITHOUT THIS**
**Risk**: MEDIUM (requires testing with real structure)

---

**Next Step**: IMMEDIATELY fix infinite loops (Phase 1), then implement validation (Phase 2).
