# DEFAULT_REFERRER Compliance Analysis

**Date**: 2025-10-21
**Status**: ❌ **CRITICAL ISSUE FOUND**
**Purpose**: Verify DEFAULT_REFERRER stops bonus recursion

---

## Executive Summary

### ❌ REQUIREMENT NOT SATISFIED

DEFAULT_REFERRER_ID is configured and used for user creation, but **MLM services DO NOT check for it** when distributing bonuses and calculating volumes.

**Impact**: DEFAULT_REFERRER receives commissions, global pool bonuses, and participates in volume calculations.

---

## Requirement Specification

From user:
> DEFAULT_REFFERER - это своеобразный флаг (хоть это и реальный юзер).
> Он назначается всем юзерам аплайнером, если не указано иное.
> На нем тормозятся все рекуррентные начисления бонусов и прочего
> (ему самому ничего не начисляется никогда).

**Translation**:
- DEFAULT_REFERRER is a flag (though it's a real user)
- Assigned as upline to all users if no other referrer specified
- **MUST STOP** all recursive bonus calculations
- **NEVER** receives any bonuses/commissions

---

## Current Implementation Status

### ✅ Configuration (config.py)

**Line 70**: Constant defined
```python
DEFAULT_REFERRER_ID = "DEFAULT_REFERRER_ID"
```

**Lines 183-184**: Value loaded from environment
```python
cls._config[cls.DEFAULT_REFERRER_ID] = int(
    os.getenv("DEFAULT_REFERRER_ID", "526738615")
)
```

**Status**: ✅ Properly configured

---

### ✅ User Creation (models/user.py:103-148)

**Lines 139-143**: DEFAULT_REFERRER used as fallback upline
```python
if referrer:
    upline = referrer_id
else:
    # Referrer not found, use default
    upline = Config.get(Config.DEFAULT_REFERRER_ID)
else:
    # No referrer provided, use default
    upline = Config.get(Config.DEFAULT_REFERRER_ID)
```

**Status**: ✅ Correctly assigns DEFAULT_REFERRER as upline

---

### ❌ Differential Commissions (commission_service.py:77-135)

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

        # ❌ NO CHECK FOR DEFAULT_REFERRER_ID HERE!

        # Calculate and add commission
        if uplineUser.isActive:
            userPercentage = self._getUserRankPercentage(uplineUser)
            differential = userPercentage - lastPercentage

            if differential > 0:
                amount = Decimal(str(purchase.packPrice)) * differential
                commissions.append({
                    "userId": uplineUser.userID,
                    "amount": amount,
                    ...
                })

        currentUser = uplineUser
        level += 1
```

#### Issue:
- Loop continues through DEFAULT_REFERRER
- DEFAULT_REFERRER gets differential commission if active
- No stop condition for DEFAULT_REFERRER

#### Required Fix:
```python
while currentUser.upline:
    # STOP at DEFAULT_REFERRER
    from config import Config
    if currentUser.upline == Config.get(Config.DEFAULT_REFERRER_ID):
        logger.debug(f"Stopped at DEFAULT_REFERRER")
        break

    uplineUser = self.session.query(User).filter_by(
        telegramID=currentUser.upline
    ).first()

    # ... rest of logic
```

**Status**: ❌ **CRITICAL BUG**

---

### ❌ Referral Bonus (commission_service.py:270-340)

#### Current Code:
```python
async def processReferralBonus(self, purchase: Purchase) -> Optional[Dict]:
    """
    Process 1% referral bonus for direct sponsor.
    Only for purchases >= 5000.
    """
    if Decimal(str(purchase.packPrice)) < REFERRAL_BONUS_MIN_AMOUNT:
        return None

    # Get direct sponsor
    purchaseUser = purchase.user
    if not purchaseUser.upline:
        return None

    sponsor = self.session.query(User).filter_by(
        telegramID=purchaseUser.upline
    ).first()

    if not sponsor or not sponsor.isActive:
        return None

    # ❌ NO CHECK IF SPONSOR IS DEFAULT_REFERRER!

    # Calculate 1% bonus
    bonusAmount = Decimal(str(purchase.packPrice)) * REFERRAL_BONUS_PERCENTAGE

    # Create bonus record
    bonus = Bonus()
    bonus.userID = sponsor.userID
    bonus.bonusAmount = bonusAmount
    # ...
    self.session.add(bonus)
```

#### Issue:
- DEFAULT_REFERRER receives 1% referral bonus if active
- No check before creating bonus

#### Required Fix:
```python
sponsor = self.session.query(User).filter_by(
    telegramID=purchaseUser.upline
).first()

if not sponsor or not sponsor.isActive:
    return None

# CHECK if sponsor is DEFAULT_REFERRER
from config import Config
if sponsor.telegramID == Config.get(Config.DEFAULT_REFERRER_ID):
    logger.debug("Skipping referral bonus for DEFAULT_REFERRER")
    return None

# Calculate 1% bonus
bonusAmount = ...
```

**Status**: ❌ **CRITICAL BUG**

---

### ❌ Pioneer Bonus (commission_service.py:171-202)

#### Current Code:
```python
async def _applyPioneerBonus(self, commissions: List[Dict], purchase: Purchase) -> List[Dict]:
    """Apply +4% Pioneer bonus to founders."""
    pioneeredCommissions = []

    for commission in commissions:
        user = self.session.query(User).filter_by(
            userID=commission["userId"]
        ).first()

        # ❌ NO CHECK FOR DEFAULT_REFERRER HERE!

        # Check if user is pioneer
        if user and user.isPioneer and commission["amount"] > 0:
            pioneerAmount = Decimal(str(purchase.packPrice)) * PIONEER_BONUS_PERCENTAGE
            commission["amount"] += pioneerAmount
```

#### Issue:
- If DEFAULT_REFERRER has isPioneer=True, gets +4% bonus
- No explicit check

#### Required Fix:
```python
for commission in commissions:
    user = self.session.query(User).filter_by(
        userID=commission["userId"]
    ).first()

    # SKIP if DEFAULT_REFERRER
    from config import Config
    if user and user.telegramID == Config.get(Config.DEFAULT_REFERRER_ID):
        pioneeredCommissions.append(commission)
        continue

    # Check if user is pioneer
    if user and user.isPioneer and commission["amount"] > 0:
        ...
```

**Status**: ❌ **CRITICAL BUG**

---

### ❌ Global Pool Distribution (global_pool_service.py:109-130)

#### Current Code:
```python
async def _findQualifiedUsers(self) -> List[Dict]:
    """
    Find users qualified for Global Pool.
    Requirement: 2 Directors in different direct branches.
    """
    qualifiedUsers = []

    # Get all potential qualifiers
    allUsers = self.session.query(User).filter(
        User.isActive == True
    ).all()

    # ❌ NO FILTER FOR DEFAULT_REFERRER!

    for user in allUsers:
        # Check if user has 2 directors in different branches
        if await self._checkGlobalPoolQualification(user):
            qualifiedUsers.append({
                "userId": user.userID,
                "telegramId": user.telegramID,
                "rank": user.rank
            })

    return qualifiedUsers
```

#### Issue:
- DEFAULT_REFERRER can qualify for Global Pool if has 2 Director branches
- Receives share of 2% monthly pool

#### Required Fix:
```python
async def _findQualifiedUsers(self) -> List[Dict]:
    qualifiedUsers = []

    from config import Config
    default_referrer_id = Config.get(Config.DEFAULT_REFERRER_ID)

    allUsers = self.session.query(User).filter(
        User.isActive == True
    ).all()

    for user in allUsers:
        # SKIP DEFAULT_REFERRER
        if user.telegramID == default_referrer_id:
            continue

        # Check if user has 2 directors in different branches
        if await self._checkGlobalPoolQualification(user):
            qualifiedUsers.append({...})

    return qualifiedUsers
```

**Status**: ❌ **CRITICAL BUG**

---

### ❌ Company Monthly Volume (global_pool_service.py:92-107)

#### Current Code:
```python
async def _calculateCompanyMonthlyVolume(self) -> Decimal:
    """Calculate total company volume for current month."""
    totalVolume = Decimal("0")
    users = self.session.query(User).filter(
        User.isActive == True
    ).all()

    # ❌ DEFAULT_REFERRER's volume included in total!

    for user in users:
        if user.mlmVolumes:
            monthlyPV = Decimal(user.mlmVolumes.get("monthlyPV", "0"))
            totalVolume += monthlyPV

    return totalVolume
```

#### Issue:
- DEFAULT_REFERRER's PV counts toward company total volume
- Inflates Global Pool size (2% of total)

#### Required Fix:
```python
async def _calculateCompanyMonthlyVolume(self) -> Decimal:
    totalVolume = Decimal("0")

    from config import Config
    default_referrer_id = Config.get(Config.DEFAULT_REFERRER_ID)

    users = self.session.query(User).filter(
        User.isActive == True
    ).all()

    for user in users:
        # SKIP DEFAULT_REFERRER's volume
        if user.telegramID == default_referrer_id:
            continue

        if user.mlmVolumes:
            monthlyPV = Decimal(user.mlmVolumes.get("monthlyPV", "0"))
            totalVolume += monthlyPV

    return totalVolume
```

**Status**: ❌ **BUG** (but less critical than commission bugs)

---

## Summary of Issues

| Service | Method | Issue | Severity |
|---------|--------|-------|----------|
| commission_service.py | _calculateDifferentialCommissions | Loop doesn't stop at DEFAULT_REFERRER | ❌ CRITICAL |
| commission_service.py | processReferralBonus | No check before granting 1% bonus | ❌ CRITICAL |
| commission_service.py | _applyPioneerBonus | No check before granting +4% bonus | ❌ CRITICAL |
| global_pool_service.py | _findQualifiedUsers | Can include DEFAULT_REFERRER | ❌ CRITICAL |
| global_pool_service.py | _calculateCompanyMonthlyVolume | Includes DEFAULT_REFERRER's PV | ⚠️ MEDIUM |

---

## Impact Analysis

### Scenario: User with no referrer makes $1000 purchase

**Current Behavior** (WRONG):
1. User created with `upline = DEFAULT_REFERRER_ID` ✅
2. User makes $1000 purchase
3. `_calculateDifferentialCommissions` walks upline:
   - Reaches DEFAULT_REFERRER
   - Calculates commission based on DEFAULT_REFERRER's rank
   - ❌ Creates Bonus record for DEFAULT_REFERRER
   - ❌ Updates DEFAULT_REFERRER's balancePassive
4. If purchase >= $5000:
   - ❌ DEFAULT_REFERRER gets 1% referral bonus
5. If DEFAULT_REFERRER.isPioneer == True:
   - ❌ DEFAULT_REFERRER gets +4% Pioneer bonus
6. At month end:
   - ❌ DEFAULT_REFERRER's PV counts in company total
   - ❌ DEFAULT_REFERRER can qualify for Global Pool share

**Expected Behavior** (CORRECT):
1. User created with `upline = DEFAULT_REFERRER_ID` ✅
2. User makes $1000 purchase
3. `_calculateDifferentialCommissions` walks upline:
   - Reaches DEFAULT_REFERRER
   - ✅ STOPS immediately (no commission)
4. ✅ No referral bonus to DEFAULT_REFERRER
5. ✅ No Pioneer bonus to DEFAULT_REFERRER
6. At month end:
   - ✅ DEFAULT_REFERRER's PV excluded from company total
   - ✅ DEFAULT_REFERRER excluded from Global Pool

---

## Recommended Fixes

### Fix 1: Add DEFAULT_REFERRER Check to CommissionService

**File**: `mlm_system/services/commission_service.py`

**Add import at top**:
```python
from config import Config
```

**Modify `__init__`**:
```python
def __init__(self, session: Session):
    self.session = session
    self.default_referrer_id = Config.get(Config.DEFAULT_REFERRER_ID)
```

**Fix `_calculateDifferentialCommissions`** (after line 88):
```python
while currentUser.upline:
    # STOP at DEFAULT_REFERRER - no commissions beyond this point
    if currentUser.upline == self.default_referrer_id:
        logger.debug(
            f"Stopped differential commission chain at DEFAULT_REFERRER "
            f"(level {level})"
        )
        break

    uplineUser = self.session.query(User).filter_by(
        telegramID=currentUser.upline
    ).first()

    # ... rest of logic unchanged
```

**Fix `processReferralBonus`** (after line 287):
```python
sponsor = self.session.query(User).filter_by(
    telegramID=purchaseUser.upline
).first()

if not sponsor or not sponsor.isActive:
    return None

# Never give referral bonus to DEFAULT_REFERRER
if sponsor.telegramID == self.default_referrer_id:
    logger.debug("Skipping referral bonus for DEFAULT_REFERRER")
    return None

# Calculate 1% bonus
bonusAmount = ...
```

**Fix `_applyPioneerBonus`** (inside loop, before Pioneer check):
```python
for commission in commissions:
    user = self.session.query(User).filter_by(
        userId=commission["userId"]
    ).first()

    # Skip DEFAULT_REFERRER (shouldn't get here, but double-check)
    if user and user.telegramID == self.default_referrer_id:
        pioneeredCommissions.append(commission)
        continue

    # Check if user is pioneer
    if user and user.isPioneer and commission["amount"] > 0:
        ...
```

**Estimated effort**: 1 hour
**Risk**: Low - straightforward checks
**Priority**: ❌ **CRITICAL**

---

### Fix 2: Add DEFAULT_REFERRER Check to GlobalPoolService

**File**: `mlm_system/services/global_pool_service.py`

**Add to `__init__`**:
```python
def __init__(self, session: Session):
    self.session = session
    self.volumeService = VolumeService(session)
    from config import Config
    self.default_referrer_id = Config.get(Config.DEFAULT_REFERRER_ID)
```

**Fix `_findQualifiedUsers`** (after line 121):
```python
for user in allUsers:
    # DEFAULT_REFERRER never qualifies for Global Pool
    if user.telegramID == self.default_referrer_id:
        continue

    # Check if user has 2 directors in different branches
    if await self._checkGlobalPoolQualification(user):
        ...
```

**Fix `_calculateCompanyMonthlyVolume`** (inside loop):
```python
for user in users:
    # Exclude DEFAULT_REFERRER's volume from company total
    if user.telegramID == self.default_referrer_id:
        continue

    if user.mlmVolumes:
        monthlyPV = Decimal(user.mlmVolumes.get("monthlyPV", "0"))
        totalVolume += monthlyPV
```

**Estimated effort**: 30 minutes
**Risk**: Low
**Priority**: ❌ **CRITICAL**

---

### Fix 3: Consider Marking DEFAULT_REFERRER as Inactive

**Optional defensive measure**:

If DEFAULT_REFERRER user record exists, ensure:
- `isActive = False` (already checked in some places)
- `isPioneer = False` (prevent Pioneer bonus)
- `rank = None` (no rank percentage)

This provides defense-in-depth even if checks are missed.

**Priority**: ⚪ **OPTIONAL** (nice-to-have)

---

## Testing Recommendations

After fixes applied, test:

1. **Create user with no referrer**
   - Verify upline = DEFAULT_REFERRER_ID
   - Make purchase
   - Verify DEFAULT_REFERRER gets NO commissions

2. **Create user with DEFAULT_REFERRER as direct upline**
   - Make $10,000 purchase
   - Verify DEFAULT_REFERRER gets:
     - ❌ NO differential commission
     - ❌ NO referral bonus (even though >= $5000)
     - ❌ NO Pioneer bonus

3. **Month-end processing**
   - Verify DEFAULT_REFERRER excluded from Global Pool qualified users
   - Verify DEFAULT_REFERRER's PV excluded from company volume total

4. **Edge case: DEFAULT_REFERRER makes purchase**
   - Create Purchase for DEFAULT_REFERRER
   - Verify no infinite loops
   - Verify no commissions generated

---

## Conclusion

### Current Status: ❌ **NON-COMPLIANT**

DEFAULT_REFERRER requirement is **NOT satisfied**. The user is assigned as upline correctly, but MLM services don't check for it when distributing bonuses.

### Required Actions:

1. ❌ **CRITICAL**: Fix commission_service.py (3 locations)
2. ❌ **CRITICAL**: Fix global_pool_service.py (2 locations)
3. ✅ **TEST**: Verify fixes with test scenarios
4. ⚪ **OPTIONAL**: Mark DEFAULT_REFERRER as inactive/no rank

**Total estimated effort**: 2-3 hours
**Priority**: Highest - affects financial calculations
**Risk**: Low - simple null checks

---

## Code Locations Reference

| File | Lines | Issue |
|------|-------|-------|
| commission_service.py | 88-94 | Add stop check in while loop |
| commission_service.py | 283-288 | Add sponsor check |
| commission_service.py | 177-190 | Add Pioneer bonus check |
| global_pool_service.py | 117-129 | Add qualified users filter |
| global_pool_service.py | 98-106 | Add volume calculation filter |

---

**Next Step**: Apply fixes to all 5 locations and test thoroughly.
