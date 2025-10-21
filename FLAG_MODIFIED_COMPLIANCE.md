# flag_modified Compliance Analysis for JSON Fields

**Date**: 2025-10-21
**Status**: ⚠️ **CRITICAL ISSUES FOUND**
**Purpose**: Verify flag_modified usage when modifying JSON fields in SQLAlchemy

---

## Executive Summary

### ⚠️ MULTIPLE MISSING flag_modified CALLS

SQLAlchemy does NOT automatically track changes inside JSON/JSONB fields. When modifying JSON field contents, **MUST call `flag_modified(obj, 'field_name')`** to tell SQLAlchemy the field changed.

**Current Status**: **Mixed compliance** - some places use it, many don't.

**Impact**: Changes to JSON fields may NOT be saved to database without `session.commit()` being aware of them.

---

## JSON Fields in Models

### User Model (models/user.py)

**5 JSON Fields**:
1. `mlmStatus` - MLM status information
2. `mlmVolumes` - Volume tracking (PV, FV, TV)
3. `personalData` - User personal information
4. `emailVerification` - Email verification status
5. `settings` - User preferences

---

## Analysis Results

### ✅ Places Using flag_modified (CORRECT)

#### 1. handlers/start.py (lines 656-660, 716-719)
```python
user.emailVerification['confirmed'] = True
user.emailVerification['confirmedAt'] = datetime.now(timezone.utc).isoformat()

# ✅ CORRECT: Flag as modified
flag_modified(user, 'emailVerification')

session.commit()
```
**Status**: ✅ CORRECT

---

#### 2. handlers/portfolio.py (lines 246-251)
```python
user.settings['strategy'] = strategy_key

# ✅ CORRECT: Flag as modified
flag_modified(user, 'settings')

session.commit()
```
**Status**: ✅ CORRECT

---

#### 3. handlers/user_data.py (lines 578-583)
```python
user.emailVerification['sentAt'] = datetime.now(timezone.utc).isoformat()
user.emailVerification['attempts'] = user.emailVerification.get('attempts', 0) + 1

# ✅ CORRECT: Flag as modified
flag_modified(user, 'emailVerification')

session.commit()
```
**Status**: ✅ CORRECT

---

#### 4. services/user_domain/user_data_service.py (lines 307-313, 344-351, 376-383)
```python
user.personalData['dataFilled'] = True
user.personalData['filledAt'] = datetime.now(timezone.utc).isoformat()

# ✅ CORRECT: Flag as modified
flag_modified(user, 'personalData')

session.commit()
```
**Status**: ✅ CORRECT (3 locations)

---

### ❌ Places NOT Using flag_modified (BUGS)

#### ❌ 1. mlm_system/services/volume_service.py (lines 45-65)

**Location**: `_updatePersonalVolume()` method

**Code**:
```python
if not user.mlmVolumes:
    user.mlmVolumes = {}

user.mlmVolumes["personalTotal"] = str(user.personalVolumeTotal)
user.mlmVolumes["monthlyPV"] = str(
    Decimal(user.mlmVolumes.get("monthlyPV", "0")) + amount
)

# Check activation status
monthlyPv = Decimal(user.mlmVolumes["monthlyPV"])
if monthlyPv >= Decimal("200"):
    user.isActive = True
    user.lastActiveMonth = currentMonth

    if user.mlmStatus:
        user.mlmStatus["lastActiveMonth"] = currentMonth  # ❌ ALSO MODIFIED!

# ❌ NO flag_modified(user, 'mlmVolumes')
# ❌ NO flag_modified(user, 'mlmStatus')
```

**Impact**:
- Changes to `mlmVolumes` may not be saved
- Changes to `mlmStatus` may not be saved
- Critical for volume tracking!

**Fix Required**:
```python
user.mlmVolumes["personalTotal"] = str(user.personalVolumeTotal)
user.mlmVolumes["monthlyPV"] = str(...)

# FIX: Add flag_modified
from sqlalchemy.orm.attributes import flag_modified
flag_modified(user, 'mlmVolumes')

if user.mlmStatus:
    user.mlmStatus["lastActiveMonth"] = currentMonth
    flag_modified(user, 'mlmStatus')
```

**Priority**: ❌ **CRITICAL** (affects MLM volume tracking)

---

#### ❌ 2. mlm_system/services/volume_service.py (lines 84-92)

**Location**: `_updateFullVolumeChain()` method

**Code**:
```python
def update_volume(upline_user: User, level: int) -> bool:
    """Update FV for each upline user."""
    # Update FV
    upline_user.fullVolume = (upline_user.fullVolume or Decimal("0")) + amount

    # DEPRECATED: Also update old teamVolumeTotal
    upline_user.teamVolumeTotal = (upline_user.teamVolumeTotal or Decimal("0")) + amount

    if not upline_user.mlmVolumes:
        upline_user.mlmVolumes = {}

    upline_user.mlmVolumes["teamTotal"] = str(upline_user.teamVolumeTotal)

    # ❌ NO flag_modified(upline_user, 'mlmVolumes')

    return True
```

**Impact**:
- Team volume changes in `mlmVolumes` may not be saved
- Affects entire upline chain

**Fix Required**:
```python
upline_user.mlmVolumes["teamTotal"] = str(upline_user.teamVolumeTotal)

# FIX: Add flag_modified
from sqlalchemy.orm.attributes import flag_modified
flag_modified(upline_user, 'mlmVolumes')
```

**Priority**: ❌ **CRITICAL** (affects team volume tracking)

---

#### ❌ 3. mlm_system/services/volume_service.py (line 161)

**Location**: `resetMonthlyVolumes()` method

**Code**:
```python
async def resetMonthlyVolumes(self):
    """Reset all monthly volumes - called on 1st of month."""
    allUsers = self.session.query(User).all()

    for user in allUsers:
        if user.mlmVolumes:
            user.mlmVolumes["monthlyPV"] = "0"  # ❌ NO flag_modified!

        user.isActive = False

    session.commit()
```

**Impact**:
- Monthly PV reset may not be saved for all users
- Affects monthly volume reset

**Fix Required**:
```python
for user in allUsers:
    if user.mlmVolumes:
        user.mlmVolumes["monthlyPV"] = "0"

        # FIX: Add flag_modified
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(user, 'mlmVolumes')

    user.isActive = False
```

**Priority**: ❌ **CRITICAL** (affects monthly reset)

---

#### ❌ 4. mlm_system/services/rank_service.py (lines 92-110)

**Location**: `_qualifyForRank()` method

**Code**:
```python
user.rank = newRank

# Update MLM status
if not user.mlmStatus:
    user.mlmStatus = {}
user.mlmStatus["rankQualifiedAt"] = timeMachine.now.isoformat()

# ❌ NO flag_modified(user, 'mlmStatus')

# Create history record
history = RankHistory(...)
self.session.add(history)
```

**Impact**:
- `rankQualifiedAt` timestamp may not be saved
- Affects rank qualification tracking

**Fix Required**:
```python
user.mlmStatus["rankQualifiedAt"] = timeMachine.now.isoformat()

# FIX: Add flag_modified
from sqlalchemy.orm.attributes import flag_modified
flag_modified(user, 'mlmStatus')
```

**Priority**: ❌ **HIGH** (affects rank tracking)

---

#### ❌ 5. mlm_system/services/rank_service.py (lines 135-138)

**Location**: `assignRankByFounder()` method

**Code**:
```python
if not user.mlmStatus:
    user.mlmStatus = {}
user.mlmStatus["assignedRank"] = newRank
user.mlmStatus["rankQualifiedAt"] = timeMachine.now.isoformat()

# ❌ NO flag_modified(user, 'mlmStatus')
```

**Impact**:
- Manual rank assignments may not save timestamps
- Affects founder rank assignments

**Fix Required**:
```python
user.mlmStatus["assignedRank"] = newRank
user.mlmStatus["rankQualifiedAt"] = timeMachine.now.isoformat()

# FIX: Add flag_modified
from sqlalchemy.orm.attributes import flag_modified
flag_modified(user, 'mlmStatus')
```

**Priority**: ❌ **HIGH**

---

#### ❌ 6. mlm_system/services/rank_service.py (line 187)

**Location**: `saveMonthlyStats()` method

**Code**:
```python
if user.mlmStatus:
    user.mlmStatus["lastActiveMonth"] = timeMachine.currentMonth if isActive else None
    # ❌ NO flag_modified(user, 'mlmStatus')
```

**Impact**:
- Last active month may not be saved

**Fix Required**:
```python
if user.mlmStatus:
    user.mlmStatus["lastActiveMonth"] = timeMachine.currentMonth if isActive else None

    # FIX: Add flag_modified
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(user, 'mlmStatus')
```

**Priority**: ⚠️ **MEDIUM**

---

#### ❌ 7. utils/helpers.py (lines 140-145)

**Location**: `set_email_last_sent()` function

**Code**:
```python
def set_email_last_sent(user: User, timestamp: datetime) -> None:
    """Set timestamp of last email sent"""
    if not user.emailVerification:
        user.emailVerification = {}
    user.emailVerification['sentAt'] = timestamp.isoformat()
    user.emailVerification['attempts'] = user.emailVerification.get('attempts', 0) + 1

    # ❌ NO flag_modified(user, 'emailVerification')
```

**Impact**:
- Email send tracking may not be saved
- Affects email rate limiting

**Fix Required**:
```python
def set_email_last_sent(user: User, timestamp: datetime) -> None:
    """Set timestamp of last email sent"""
    if not user.emailVerification:
        user.emailVerification = {}
    user.emailVerification['sentAt'] = timestamp.isoformat()
    user.emailVerification['attempts'] = user.emailVerification.get('attempts', 0) + 1

    # FIX: Add flag_modified
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(user, 'emailVerification')
```

**Priority**: ⚠️ **MEDIUM**

---

#### ❌ 8. services/user_domain/auth_service.py (lines 78-86)

**Location**: `accept_eula()` method

**Code**:
```python
if not user.personalData:
    user.personalData = {}

user.personalData['eulaAccepted'] = True
user.personalData['eulaVersion'] = eula_version
user.personalData['eulaAcceptedAt'] = datetime.now(timezone.utc).isoformat()

# ❌ NO flag_modified(user, 'personalData')

self.session.commit()
```

**Impact**:
- EULA acceptance may not be saved
- Critical for legal compliance

**Fix Required**:
```python
user.personalData['eulaAccepted'] = True
user.personalData['eulaVersion'] = eula_version
user.personalData['eulaAcceptedAt'] = datetime.now(timezone.utc).isoformat()

# FIX: Add flag_modified
from sqlalchemy.orm.attributes import flag_modified
flag_modified(user, 'personalData')

self.session.commit()
```

**Priority**: ❌ **HIGH** (legal compliance)

---

#### ❌ 9. models/user.py - Property Setters (lines 227-263)

**Locations**: Multiple property setters

**Code**:
```python
@emailConfirmed.setter
def emailConfirmed(self, value):
    if not self.emailVerification:
        self.emailVerification = {}
    self.emailVerification['confirmed'] = bool(value)
    if value:
        self.emailVerification['confirmedAt'] = datetime.now(timezone.utc).isoformat()
    # ❌ NO flag_modified

@strategy.setter
def strategy(self, value):
    if not self.settings:
        self.settings = {}
    self.settings['strategy'] = value
    # ❌ NO flag_modified

@isPioneer.setter
def isPioneer(self, value):
    if not self.mlmStatus:
        self.mlmStatus = {}
    self.mlmStatus['isFounder'] = bool(value)
    # ❌ NO flag_modified

@monthlyPV.setter
def monthlyPV(self, value):
    if not self.mlmVolumes:
        self.mlmVolumes = {}
    self.mlmVolumes['monthlyPV'] = float(value)
    # ❌ NO flag_modified

@personalVolumeTotal.setter
def personalVolumeTotal(self, value):
    if not self.mlmVolumes:
        self.mlmVolumes = {}
    self.mlmVolumes['personalTotal'] = float(value)
    # ❌ NO flag_modified
```

**Impact**:
- ANY code using these properties will silently fail to save changes
- Very dangerous because properties hide the problem

**Fix Required**:
```python
@emailConfirmed.setter
def emailConfirmed(self, value):
    if not self.emailVerification:
        self.emailVerification = {}
    self.emailVerification['confirmed'] = bool(value)
    if value:
        self.emailVerification['confirmedAt'] = datetime.now(timezone.utc).isoformat()

    # FIX: Add flag_modified
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(self, 'emailVerification')

# Same for all other setters
```

**Priority**: ❌ **CRITICAL** (affects many operations silently)

---

## Summary of Issues

| File | Location | Field | Severity | Lines |
|------|----------|-------|----------|-------|
| volume_service.py | _updatePersonalVolume | mlmVolumes | ❌ CRITICAL | 48-51 |
| volume_service.py | _updatePersonalVolume | mlmStatus | ❌ CRITICAL | 60 |
| volume_service.py | _updateFullVolumeChain | mlmVolumes | ❌ CRITICAL | 87 |
| volume_service.py | resetMonthlyVolumes | mlmVolumes | ❌ CRITICAL | 161 |
| rank_service.py | _qualifyForRank | mlmStatus | ❌ HIGH | 97 |
| rank_service.py | assignRankByFounder | mlmStatus | ❌ HIGH | 137-138 |
| rank_service.py | saveMonthlyStats | mlmStatus | ⚠️ MEDIUM | 187 |
| utils/helpers.py | set_email_last_sent | emailVerification | ⚠️ MEDIUM | 144-145 |
| auth_service.py | accept_eula | personalData | ❌ HIGH | 82-84 |
| user.py | emailConfirmed setter | emailVerification | ❌ CRITICAL | 231-233 |
| user.py | strategy setter | settings | ❌ CRITICAL | 248 |
| user.py | isPioneer setter | mlmStatus | ❌ CRITICAL | 263 |
| user.py | monthlyPV setter | mlmVolumes | ❌ CRITICAL | 278 |
| user.py | personalVolumeTotal setter | mlmVolumes | ❌ CRITICAL | 293 |

**Total Issues**: 14 locations
**Critical**: 10
**High**: 3
**Medium**: 2

---

## Correct Patterns Found

### ✅ Pattern 1: Direct Modification + flag_modified

```python
user.emailVerification['confirmed'] = True
user.emailVerification['confirmedAt'] = datetime.now(timezone.utc).isoformat()

from sqlalchemy.orm.attributes import flag_modified
flag_modified(user, 'emailVerification')

session.commit()
```

### ✅ Pattern 2: Helper Function (utils/helpers.py:239-259)

```python
def safe_set_json_value(obj, field_name: str, value, *keys) -> None:
    """
    Safely set value in JSON field with automatic flag_modified.

    Example:
        safe_set_json_value(user, 'personalData', True, 'dataFilled')
    """
    from sqlalchemy.orm.attributes import flag_modified

    json_field = getattr(obj, field_name)
    if json_field is None:
        json_field = {}
        setattr(obj, field_name, json_field)

    current = json_field
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]

    current[keys[-1]] = value

    # Mark as modified for SQLAlchemy
    flag_modified(obj, field_name)
```

**Status**: ✅ GOOD - but NOT USED in most places

---

## Recommendations

### Phase 1: Fix Critical MLM Issues (URGENT - 2 hours)

1. **volume_service.py** - Add flag_modified for all mlmVolumes and mlmStatus modifications
2. **models/user.py** - Add flag_modified to all property setters

**Impact**: Fixes core MLM functionality

---

### Phase 2: Fix High Priority (1 hour)

3. **rank_service.py** - Add flag_modified for mlmStatus modifications
4. **auth_service.py** - Add flag_modified for personalData (EULA)

**Impact**: Fixes rank tracking and legal compliance

---

### Phase 3: Fix Medium Priority (30 minutes)

5. **utils/helpers.py** - Add flag_modified to set_email_last_sent
6. **rank_service.py** - Add flag_modified to saveMonthlyStats

**Impact**: Fixes email tracking

---

### Phase 4: Refactor to Use Helper (2-3 hours)

7. Replace all direct JSON modifications with `safe_set_json_value()` helper
8. Add linter rule to catch direct JSON field modifications

**Impact**: Future-proof solution

---

## Implementation Priority

**IMMEDIATE** (affects data integrity):
1. models/user.py property setters
2. volume_service.py all locations
3. rank_service.py all locations

**HIGH** (affects features):
4. auth_service.py EULA acceptance

**MEDIUM** (nice to have):
5. utils/helpers.py email tracking
6. Refactoring to use helper everywhere

---

## Testing After Fixes

After adding flag_modified, test:

1. **Volume Updates**: Make purchase, check mlmVolumes saved correctly
2. **Rank Changes**: Update rank, check mlmStatus timestamps saved
3. **Email Verification**: Verify email, check emailVerification saved
4. **EULA Acceptance**: Accept EULA, check personalData saved
5. **Strategy Changes**: Change strategy, check settings saved

**Test Method**:
```python
# Before commit
print(user.mlmVolumes)

session.commit()
session.refresh(user)

# After commit - should match
print(user.mlmVolumes)
```

---

## Conclusion

### ⚠️ CRITICAL DATA INTEGRITY ISSUE

**14 locations** are modifying JSON fields without `flag_modified`, causing potential data loss.

**Most Critical**:
- MLM volume tracking (volume_service.py)
- Rank qualification (rank_service.py)
- Property setters (models/user.py) - silently fail

**Estimated Fix Time**: 4-6 hours total
**Priority**: ❌ **HIGHEST** - affects data integrity
**Risk**: LOW (straightforward fixes)

**Next Step**: Implement Phase 1 fixes immediately (MLM core functionality).
