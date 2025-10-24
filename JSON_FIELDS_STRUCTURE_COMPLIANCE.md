# JSON Fields Structure Compliance Analysis

**Date**: 2025-10-24
**Status**: ⚠️ **CRITICAL INCONSISTENCIES FOUND**
**Purpose**: Verify JSON field structures match their documented comments in User model

---

## Executive Summary

### ⚠️ MAJOR ISSUES FOUND

The JSON fields in the User model have **significant inconsistencies** between documented structures (comments) and actual usage:

1. **totalVolume** - ❌ **NOT USED AT ALL** (0 locations)
2. **mlmStatus** - ⚠️ **PARTIAL** (3 of 6 fields used, 1 field read but never written)
3. **mlmVolumes** - ⚠️ **PARTIAL** (2 of 3 documented fields + 1 undocumented field)
4. **personalData** - ⚠️ **PARTIAL** (4 documented fields + 1 undocumented field + incomplete kyc)
5. **emailVerification** - ✅ **MOSTLY COMPLIANT** (5 fields + 4 undocumented fields for old email)
6. **settings** - ❌ **MINIMAL** (1 of 3 documented fields used)

**Total Compliance**: ~45% (many documented fields never used)

---

## Field-by-Field Analysis

### 1. totalVolume (JSON)

**Documented Structure**:
```python
{
    "qualifyingVolume": 35000.00,
    "fullVolume": 60000.00,
    "requiredForNextRank": 50000.00,
    "gap": 15000.00,
    "nextRank": "growth",
    "currentRank": "builder",
    "capLimit": 25000.00,
    "branches": [
        {
            "referralTelegramId": 123456789,
            "referralName": "Иван Петров (1001)",
            "referralUserId": 1001,
            "fullVolume": 50000.00,
            "cappedVolume": 25000.00,
            "isCapped": true
        }
    ],
    "calculatedAt": "2025-01-15T10:30:00Z"
}
```

**Actual Usage**: ❌ **NONE**

**Analysis**:
```bash
# Search for assignments to totalVolume
grep -r "\.totalVolume\s*=" --include="*.py" .
# Result: NO MATCHES

# Search for assignments to totalVolume dict keys
grep -r "\.totalVolume\[" --include="*.py" .
# Result: NO MATCHES
```

**Status**: ❌ **CRITICAL - FIELD NOT USED**

**Impact**:
- The entire complex structure with qualifyingVolume, branches, cap calculations is documented but **NEVER POPULATED**
- This appears to be a planned feature that was never implemented
- Dead code in model comments

**Recommendation**:
- Either implement the feature OR remove the field from the model
- Current code calculates qualifyingVolume in rank_service.py but doesn't store it in totalVolume

---

### 2. mlmStatus (JSON)

**Documented Structure**:
```python
{
  "rankQualifiedAt": null,
  "assignedRank": null,
  "isFounder": false,
  "lastActiveMonth": null,
  "pioneerPurchasesCount": 0,
  "hasPioneerBonus": false
}
```

**Actual Usage**: ⚠️ **PARTIAL COMPLIANCE**

**Fields Analysis**:

| Field | Status | Used Where | Notes |
|-------|--------|------------|-------|
| rankQualifiedAt | ✅ USED | rank_service.py:97, 141 | Set when rank changes |
| assignedRank | ✅ USED | rank_service.py:140 | Set for manual rank assignment |
| isFounder | ✅ USED | models/user.py:268, rank_service.py:130 | Via isPioneer property |
| lastActiveMonth | ✅ USED | rank_service.py:193, volume_service.py:63 | Activity tracking |
| pioneerPurchasesCount | ❌ NEVER USED | - | Field documented but never read or written |
| hasPioneerBonus | ⚠️ READ ONLY | commission_service.py:188 | **READ but NEVER WRITTEN** |

**Critical Issues**:

#### ❌ Issue 1: `hasPioneerBonus` Read But Never Written

**Location**: mlm_system/services/commission_service.py:188
```python
if user and user.mlmStatus:
    hasPioneerBonus = user.mlmStatus.get("hasPioneerBonus", False)

    if hasPioneerBonus:
        # Add 4% bonus
        pioneerAmount = Decimal(str(purchase.packPrice)) * PIONEER_BONUS_PERCENTAGE
        commission["pioneerBonus"] = pioneerAmount
```

**Problem**: This field is read to determine if pioneer bonus should be applied, but it's **NEVER SET TO TRUE** anywhere in the code!

**Impact**: Pioneer bonus system is broken - the 4% bonus can never be triggered because `hasPioneerBonus` is always `False`

**Fix Required**:
```python
# Need to add logic somewhere (probably in user creation or first purchase):
if user.mlmStatus:
    user.mlmStatus["hasPioneerBonus"] = True  # Set based on some criteria
    flag_modified(user, 'mlmStatus')
```

#### ❌ Issue 2: `pioneerPurchasesCount` Completely Unused

**Status**: Dead field - documented but never touched

**Recommendation**: Either remove from documentation or implement purchase counting logic

---

### 3. mlmVolumes (JSON)

**Documented Structure**:
```python
{
  "personalTotal": 0.0,      # Накопительный личный объем
  "monthlyPV": 0.0,          # PV текущего месяца
  "autoship": {"enabled": false, "amount": 200}
}
```

**Actual Usage**: ⚠️ **PARTIAL + UNDOCUMENTED FIELD**

**Fields Analysis**:

| Field | Status | Used Where | Type |
|-------|--------|------------|------|
| personalTotal | ✅ USED | volume_service.py:48 | String (not float as documented!) |
| monthlyPV | ✅ USED | volume_service.py:49-50, 168 | String (not float as documented!) |
| autoship | ❌ NEVER USED | - | Nested object documented but unused |
| **teamTotal** | ⚠️ UNDOCUMENTED | volume_service.py:91 | **NOT in comments but USED in code!** |

**Critical Issues**:

#### ⚠️ Issue 1: Undocumented Field `teamTotal`

**Location**: mlm_system/services/volume_service.py:91
```python
uplineUser.mlmVolumes["teamTotal"] = str(uplineUser.teamVolumeTotal)
```

**Problem**: This field is actively used but **NOT DOCUMENTED** in model comments

**Recommendation**: Add to documentation:
```python
{
  "personalTotal": "0.0",
  "monthlyPV": "0.0",
  "teamTotal": "0.0",        # <- ADD THIS
  "autoship": {"enabled": false, "amount": 200}
}
```

#### ⚠️ Issue 2: Type Mismatch

**Documentation says**: `"personalTotal": 0.0` (number)
**Actual usage**: `user.mlmVolumes["personalTotal"] = str(user.personalVolumeTotal)` (string)

**Impact**: Documentation misleading - values are strings, not numbers

**Fix Documentation**:
```python
{
  "personalTotal": "0.0",    # String, not float
  "monthlyPV": "0.0",        # String, not float
  "teamTotal": "0.0",        # String, not float - ADD THIS
  "autoship": {"enabled": false, "amount": 200}  # Documented but unused
}
```

#### ❌ Issue 3: `autoship` Never Implemented

**Status**: Dead field - entire nested object documented but never used

**Recommendation**: Remove from documentation or implement autoship feature

---

### 4. personalData (JSON)

**Documented Structure**:
```python
{
  "eulaAccepted": true,
  "eulaVersion": "1.0",
  "eulaAcceptedAt": "2024-01-01T10:00:00",
  "dataFilled": false,
  "kyc": {
    "status": "not_started",
    "verifiedAt": null,
    "documents": [],
    "level": 0
  }
}
```

**Actual Usage**: ⚠️ **PARTIAL + UNDOCUMENTED FIELD + INCOMPLETE KYC**

**Fields Analysis**:

| Field | Status | Used Where | Notes |
|-------|--------|------------|-------|
| eulaAccepted | ✅ USED | auth_service.py:82 | EULA acceptance |
| eulaVersion | ✅ USED | auth_service.py:83 | Version tracking |
| eulaAcceptedAt | ✅ USED | auth_service.py:84 | Timestamp |
| dataFilled | ✅ USED | user_data_service.py:307 | Profile completion flag |
| **filledAt** | ⚠️ UNDOCUMENTED | user_data_service.py:308 | **NOT in comments but USED!** |
| kyc.status | ⚠️ PARTIAL | models/user.py:196, 198 | Only status set, other fields ignored |
| kyc.verifiedAt | ❌ NEVER USED | - | Documented but never set |
| kyc.documents | ❌ NEVER USED | - | Documented but never set |
| kyc.level | ❌ NEVER USED | - | Documented but never set |

**Critical Issues**:

#### ⚠️ Issue 1: Undocumented Field `filledAt`

**Location**: services/user_domain/user_data_service.py:308
```python
user.personalData['dataFilled'] = True
user.personalData['filledAt'] = datetime.now(timezone.utc).isoformat()
```

**Problem**: `filledAt` is set but **NOT DOCUMENTED**

**Fix Documentation**:
```python
{
  "eulaAccepted": true,
  "eulaVersion": "1.0",
  "eulaAcceptedAt": "2024-01-01T10:00:00",
  "dataFilled": false,
  "filledAt": "2024-01-15T10:00:00",  # <- ADD THIS
  "kyc": { ... }
}
```

#### ⚠️ Issue 2: Incomplete KYC Implementation

**Location**: models/user.py:187-198
```python
@kyc.setter
def kyc(self, value):
    if not self.personalData:
        self.personalData = {'kyc': {}}
    if 'kyc' not in self.personalData:
        self.personalData['kyc'] = {}

    if value:
        self.personalData['kyc']['status'] = 'verified'  # ONLY STATUS!
    else:
        self.personalData['kyc']['status'] = 'not_started'
```

**Problem**:
- KYC setter only sets `status`
- `verifiedAt`, `documents`, `level` are **NEVER POPULATED**
- Documentation promises rich structure, code provides minimal implementation

**Impact**: KYC tracking is essentially boolean (verified/not_started) despite complex documentation

**Recommendation**:
- Either implement full KYC structure OR simplify documentation to match reality
- Current reality: `"kyc": {"status": "not_started"}` (that's it!)

---

### 5. emailVerification (JSON)

**Documented Structure**:
```python
{
  "confirmed": false,
  "token": "UCfwYV7sNTu8p4X7",
  "sentAt": "2024-01-15T10:30:00",
  "confirmedAt": null,
  "attempts": 1
}
```

**Actual Usage**: ✅ **MOSTLY COMPLIANT + UNDOCUMENTED FIELDS**

**Fields Analysis**:

| Field | Status | Used Where | Notes |
|-------|--------|------------|-------|
| confirmed | ✅ USED | start.py:656, models/user.py:232 | Email confirmed flag |
| token | ✅ USED | user_data_service.py:345, models/user.py:331 | Verification token |
| sentAt | ✅ USED | user_data.py:578, helpers.py:144 | Email sent timestamp |
| confirmedAt | ✅ USED | start.py:657 | Confirmation timestamp |
| attempts | ✅ USED | user_data.py:579, helpers.py:145 | Send attempts counter |
| **old_email** | ⚠️ UNDOCUMENTED | user_data_service.py:376 | Email change feature |
| **old_email_token** | ⚠️ UNDOCUMENTED | user_data_service.py:377 | Email change token |
| **old_email_confirmed** | ⚠️ UNDOCUMENTED | start.py:716 | Old email confirmation |
| **old_email_sentAt** | ⚠️ UNDOCUMENTED | user_data_service.py:379 | Old email sent time |

**Status**: ✅ **BEST COMPLIANCE** - All documented fields used correctly

**Undocumented Feature**: Email change system with old email tracking

**Recommendation**: Update documentation to include old email fields:
```python
{
  "confirmed": false,
  "token": "UCfwYV7sNTu8p4X7",
  "sentAt": "2024-01-15T10:30:00",
  "confirmedAt": null,
  "attempts": 1,
  # Email change fields (when user changes email):
  "old_email": "old@example.com",
  "old_email_token": "AbCd1234",
  "old_email_confirmed": false,
  "old_email_sentAt": "2024-01-16T10:00:00"
}
```

---

### 6. settings (JSON)

**Documented Structure**:
```python
{
  "strategy": "risky",
  "notifications": {"bonus": true, "purchase": true},
  "display": {"showBalance": true}
}
```

**Actual Usage**: ❌ **MINIMAL COMPLIANCE**

**Fields Analysis**:

| Field | Status | Used Where | Notes |
|-------|--------|------------|-------|
| strategy | ✅ USED | handlers/portfolio.py:246, models/user.py:251 | Trading strategy |
| notifications | ❌ NEVER USED | - | Entire nested object unused |
| display | ❌ NEVER USED | - | Entire nested object unused |

**Status**: ❌ **ONLY 1 OF 3 FIELDS USED**

**Impact**:
- 67% of documented structure is dead code
- notification and display preferences cannot be configured

**Recommendation**:
- Either implement notification/display settings OR remove from documentation
- Current reality: `{"strategy": "manual"}` (that's it!)

---

## Summary Table

| Field | Documented Fields | Used Fields | Undocumented Used | Missing | Compliance |
|-------|------------------|-------------|-------------------|---------|------------|
| totalVolume | 8 | 0 | 0 | 8 | ❌ 0% |
| mlmStatus | 6 | 4 | 0 | 2 (1 broken) | ⚠️ 67% |
| mlmVolumes | 3 | 2 | 1 | 1 | ⚠️ 67% |
| personalData | 8 | 4 | 1 | 3 | ⚠️ 50% |
| emailVerification | 5 | 5 | 4 | 0 | ✅ 100% |
| settings | 3 | 1 | 0 | 2 | ❌ 33% |

**Overall Compliance**: ~45%

---

## Critical Issues Summary

### 🔴 CRITICAL (Must Fix)

1. **totalVolume NOT IMPLEMENTED** (models/user.py:28)
   - Entire complex field documented but never used
   - Remove field OR implement feature

2. **hasPioneerBonus Read But Never Written** (commission_service.py:188)
   - Pioneer bonus system broken
   - Field checked but always False
   - **Impact**: 4% pioneer bonus never triggers

3. **Type Mismatches in Documentation**
   - mlmVolumes: documented as numbers, actually strings
   - Misleading for developers

### ⚠️ HIGH (Should Fix)

4. **Undocumented Fields in Use**
   - mlmVolumes["teamTotal"] - used but not documented
   - personalData["filledAt"] - used but not documented
   - emailVerification["old_email_*"] - 4 fields used but not documented

5. **Incomplete KYC Implementation** (models/user.py:187-198)
   - Documentation promises rich structure
   - Reality: only status field used
   - verifiedAt, documents, level never populated

6. **Dead Fields**
   - mlmStatus["pioneerPurchasesCount"] - documented but never touched
   - mlmVolumes["autoship"] - entire nested object unused
   - settings["notifications"] - entire nested object unused
   - settings["display"] - entire nested object unused

---

## Recommendations

### Phase 1: Fix Critical Issues (2-3 hours)

1. **Fix hasPioneerBonus**
   ```python
   # Add to user creation or first purchase logic:
   if should_give_pioneer_bonus(user):  # Define criteria
       if not user.mlmStatus:
           user.mlmStatus = {}
       user.mlmStatus["hasPioneerBonus"] = True
       flag_modified(user, 'mlmStatus')
   ```

2. **Fix totalVolume**
   - Option A: Remove field from model entirely
   - Option B: Implement feature by storing calculation results from rank_service.py

3. **Update Documentation Types**
   ```python
   mlmVolumes = Column(JSON, nullable=True)
   # {
   #   "personalTotal": "0.0",  # String representation
   #   "monthlyPV": "0.0",      # String representation
   #   "teamTotal": "0.0"       # String representation - ADDED
   # }
   ```

### Phase 2: Clean Up Documentation (1 hour)

4. **Add undocumented fields to comments**
   - mlmVolumes: add teamTotal
   - personalData: add filledAt
   - emailVerification: add old_email fields

5. **Mark unused fields as TODO or remove**
   ```python
   # "pioneerPurchasesCount": 0,  # TODO: Not implemented yet
   # "autoship": {...},            # TODO: Not implemented yet
   ```

### Phase 3: Implement or Remove Dead Features (4-6 hours)

6. **Decide on each dead field**:
   - Implement autoship feature OR remove from docs
   - Implement notifications settings OR remove from docs
   - Implement display settings OR remove from docs
   - Implement pioneerPurchasesCount OR remove from docs
   - Implement full KYC structure OR simplify docs

---

## Testing Recommendations

After fixes, verify:

1. **Pioneer Bonus**:
   ```python
   # Test that hasPioneerBonus is set correctly
   user = create_pioneer_user()
   assert user.mlmStatus.get("hasPioneerBonus") == True

   purchase = make_purchase(user)
   commissions = process_commissions(purchase)
   assert commissions[0].get("pioneerBonus") > 0
   ```

2. **Field Types**:
   ```python
   # Verify mlmVolumes uses strings
   user.mlmVolumes["monthlyPV"] = "100.50"
   session.commit()
   session.refresh(user)
   assert isinstance(user.mlmVolumes["monthlyPV"], str)
   ```

3. **Documentation Accuracy**:
   - Review each JSON field comment
   - Ensure all documented fields are used
   - Ensure all used fields are documented

---

## Conclusion

### ⚠️ MODERATE COMPLIANCE WITH CRITICAL BUGS

**Key Findings**:
- Overall compliance: ~45%
- **1 system-breaking bug**: hasPioneerBonus never set (pioneer bonus broken)
- **1 completely unused field**: totalVolume (entire feature not implemented)
- **Multiple undocumented fields** in active use
- **Type mismatches** in documentation

**Priority**: ⚠️ **HIGH** - pioneer bonus system broken, documentation misleading

**Estimated Fix Time**:
- Critical issues: 2-3 hours
- Documentation cleanup: 1 hour
- Feature implementation/removal: 4-6 hours
- **Total: 7-10 hours**

**Risk**: LOW (straightforward fixes, mostly documentation and missing assignments)

**Next Step**: Fix hasPioneerBonus assignment to restore pioneer bonus functionality
