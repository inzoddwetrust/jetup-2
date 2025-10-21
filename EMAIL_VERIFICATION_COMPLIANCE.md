# Email Verification Compliance Analysis

**Date**: 2025-10-21
**Status**: ❌ **CRITICAL NON-COMPLIANCE**
**Purpose**: Verify unverified email users are blocked from ALL operations

---

## Executive Summary

### ❌ REQUIREMENT MASSIVELY VIOLATED

Users with unverified emails should be "invisible people" - cannot buy, cannot receive funds, not counted in MLM, completely isolated.

**Current Reality**: NO email verification checks in ANY critical operations.

**Impact**: Unverified users can fully participate in the system.

---

## Requirement Specification

From user:
> В системе категорически запрещены любые операции для юзеров с неподтвержденным емейлом.
> Они - люди-невидимки. Не учитываются ни в МЛМ, нигде еще, ничего не могут ни покупать,
> ни на счет себе заводить, как будто их и нет вообще в природе и БД.

**Translation**:
- Unverified email users are STRICTLY FORBIDDEN from ANY operations
- They are "invisible people"
- NOT counted in MLM
- CANNOT buy
- CANNOT receive funds
- As if they don't exist at all

---

## Email Verification Field

### ✅ Database Structure (models/user.py:78-85)

```python
emailVerification = Column(JSON, nullable=True)
# {
#   "confirmed": false,
#   "token": "UCfwYV7sNTu8p4X7",
#   "sentAt": "2024-01-15T10:30:00",
#   "confirmedAt": null,
#   "attempts": 1
# }
```

**Helper Function** (utils/helpers.py:135-137):
```python
def is_email_confirmed(user: User) -> bool:
    """Check if user's email is confirmed"""
    if not user.emailVerification:
        return False
    return user.emailVerification.get('confirmed', False)
```

**Status**: ✅ Infrastructure exists but UNUSED

---

## Critical Operations WITHOUT Email Check

### ❌ 1. Purchase Creation (handlers/projects.py:446-560)

#### Current Code:
```python
@projects_router.callback_query(F.data.startswith("confirm_purchase_"))
@with_user
async def confirm_purchase(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        ...
):
    """Confirm and execute purchase."""

    # ❌ NO EMAIL VERIFICATION CHECK!

    # Lock user for update
    user = session.query(User).filter_by(
        userID=user.userID
    ).with_for_update().first()

    # Check balance
    if user.balanceActive < option.packPrice:
        # ... error handling

    # Create Purchase
    purchase = Purchase()
    purchase.userID = user.userID
    purchase.projectID = option.projectID
    purchase.packPrice = option.packPrice
    session.add(purchase)

    # Deduct balance
    user.balanceActive -= pack_price

    # Create transaction record
    active_record = ActiveBalance()
    active_record.amount = -pack_price
    session.add(active_record)

    session.commit()

    # Emit MLM event
    await eventBus.emit(MLMEvents.PURCHASE_COMPLETED, ...)
```

#### Issue:
Unverified user can:
- ✗ Create purchases
- ✗ Trigger MLM commissions for upline
- ✗ Accumulate volume
- ✗ Participate fully in system

#### Required Fix:
```python
@projects_router.callback_query(F.data.startswith("confirm_purchase_"))
@with_user
async def confirm_purchase(...):
    """Confirm and execute purchase."""

    # CHECK EMAIL VERIFICATION
    from utils.helpers import is_email_confirmed

    if not is_email_confirmed(user):
        await message_manager.send_template(
            user=user,
            template_key='email_not_verified_error',
            update=callback_query,
            edit=True
        )
        return

    # ... rest of purchase logic
```

**Location**: handlers/projects.py:446 (start of function)
**Priority**: ❌ **CRITICAL**

---

###❌ 2. Transfers (handlers/transfers.py:571)

#### Current Code:
```python
async def execute_transfer(...):
    """Execute transfer between users."""

    # ❌ NO EMAIL CHECK for sender OR recipient!

    # Deduct from sender
    sender.balanceActive -= total_amount

    # Add to recipient
    recipient.balanceActive += amount

    # Create transaction records
    # ...
```

#### Issue:
Unverified users can:
- ✗ Send transfers
- ✗ Receive transfers
- ✗ Move funds freely

#### Required Fix:
```python
async def execute_transfer(...):
    """Execute transfer between users."""

    from utils.helpers import is_email_confirmed

    # CHECK SENDER
    if not is_email_confirmed(sender):
        await message.answer("❌ You must verify your email first")
        return

    # CHECK RECIPIENT
    if not is_email_confirmed(recipient):
        await message.answer("❌ Recipient has not verified email")
        return

    # ... rest of transfer logic
```

**Location**: handlers/transfers.py (before balance updates)
**Priority**: ❌ **CRITICAL**

---

### ❌ 3. Payment Processing (Admin Approval)

**Note**: Payment approval logic not found in codebase, but when implemented, MUST check email verification before crediting balanceActive.

#### Required Implementation:
```python
async def approve_payment(payment_id: int, admin_user: User):
    """Admin approves payment and credits user balance."""

    payment = session.query(Payment).filter_by(paymentID=payment_id).first()
    user = payment.user

    from utils.helpers import is_email_confirmed

    # CHECK EMAIL VERIFICATION
    if not is_email_confirmed(user):
        # Reject payment or put on hold
        payment.status = "on_hold"
        payment.notes = "Email not verified"
        session.commit()

        # Notify admin
        await message.answer(
            f"⚠️ Cannot approve: User {user.userID} email not verified"
        )
        return

    # Approve and credit
    payment.status = "paid"
    user.balanceActive += payment.amount

    # Create ActiveBalance record
    # ...
```

**Location**: To be implemented in admin handlers
**Priority**: ❌ **CRITICAL**

---

### ❌ 4. MLM Commission Calculation (commission_service.py:77-135)

#### Current Code:
```python
async def _calculateDifferentialCommissions(self, purchase: Purchase) -> List[Dict]:
    """Calculate differential commissions up the chain."""

    commissions = []
    currentUser = purchase.user

    # ❌ NO CHECK if purchaser has verified email!

    # Walk up the upline chain
    while currentUser.upline:
        uplineUser = self.session.query(User).filter_by(
            telegramID=currentUser.upline
        ).first()

        # ❌ NO CHECK if upline has verified email!

        # Calculate and add commission
        if uplineUser.isActive:
            commissions.append({
                "userId": uplineUser.userID,
                "amount": amount,
                ...
            })

        currentUser = uplineUser
```

#### Issue:
- Purchase by unverified user GENERATES commissions for upline
- Unverified upline users RECEIVE commissions

#### Required Fix:
```python
async def _calculateDifferentialCommissions(self, purchase: Purchase) -> List[Dict]:
    """Calculate differential commissions up the chain."""

    from utils.helpers import is_email_confirmed

    commissions = []
    currentUser = purchase.user

    # STOP if purchaser email not verified
    if not is_email_confirmed(currentUser):
        logger.warning(
            f"Purchase {purchase.purchaseID} by unverified user {currentUser.userID} - "
            f"NO commissions generated"
        )
        return []  # Empty list - no commissions

    # Walk up the upline chain
    while currentUser.upline:
        uplineUser = self.session.query(User).filter_by(
            telegramID=currentUser.upline
        ).first()

        if not uplineUser:
            break

        # SKIP unverified upline users
        if not is_email_confirmed(uplineUser):
            logger.debug(
                f"Skipping commission for unverified upline user {uplineUser.userID}"
            )
            currentUser = uplineUser
            continue

        # Calculate commission only for verified users
        if uplineUser.isActive:
            commissions.append(...)

        currentUser = uplineUser

    return commissions
```

**Location**: commission_service.py:77-95
**Priority**: ❌ **CRITICAL**

---

### ❌ 5. Referral Bonus (commission_service.py:270-340)

#### Current Code:
```python
async def processReferralBonus(self, purchase: Purchase) -> Optional[Dict]:
    """Process 1% referral bonus for direct sponsor."""

    # ❌ NO CHECK if purchaser verified
    # ❌ NO CHECK if sponsor verified

    purchaseUser = purchase.user
    sponsor = self.session.query(User).filter_by(
        telegramID=purchaseUser.upline
    ).first()

    if not sponsor or not sponsor.isActive:
        return None

    # Calculate and give bonus
    bonusAmount = ...
    sponsor.balancePassive += bonusAmount
```

#### Required Fix:
```python
async def processReferralBonus(self, purchase: Purchase) -> Optional[Dict]:
    """Process 1% referral bonus for direct sponsor."""

    from utils.helpers import is_email_confirmed

    purchaseUser = purchase.user

    # CHECK purchaser verified
    if not is_email_confirmed(purchaseUser):
        logger.debug("Referral bonus skipped - purchaser email not verified")
        return None

    sponsor = self.session.query(User).filter_by(
        telegramID=purchaseUser.upline
    ).first()

    if not sponsor or not sponsor.isActive:
        return None

    # CHECK sponsor verified
    if not is_email_confirmed(sponsor):
        logger.debug(f"Referral bonus skipped - sponsor {sponsor.userID} email not verified")
        return None

    # Calculate and give bonus
    ...
```

**Location**: commission_service.py:270-290
**Priority**: ❌ **CRITICAL**

---

### ❌ 6. Volume Calculation (volume_service.py:25-84)

#### Current Code:
```python
async def updatePurchaseVolumes(self, purchase: Purchase):
    """Update volumes for purchase and upline chain."""

    purchaseAmount = Decimal(str(purchase.packPrice))
    currentMonth = timeMachine.currentMonth

    # Update purchaser's personal volume
    user = purchase.user
    await self._updatePersonalVolume(user, purchaseAmount, currentMonth)

    # Update team volumes up the chain
    await self._updateTeamVolumeChain(user, purchaseAmount)

async def _updateTeamVolumeChain(self, user: User, amount: Decimal):
    """Update team volumes up the upline chain."""

    currentUser = user

    # ❌ NO EMAIL CHECKS anywhere!

    while currentUser.upline:
        uplineUser = self.session.query(User).filter_by(
            telegramID=currentUser.upline
        ).first()

        if not uplineUser:
            break

        # Update team volume
        uplineUser.teamVolumeTotal += amount

        # ...
```

#### Issue:
- Unverified purchaser's volume COUNTED
- Unverified upline receives team volume credit

#### Required Fix:
```python
async def updatePurchaseVolumes(self, purchase: Purchase):
    """Update volumes for purchase and upline chain."""

    from utils.helpers import is_email_confirmed

    user = purchase.user

    # STOP if user email not verified
    if not is_email_confirmed(user):
        logger.warning(
            f"Volume update skipped for purchase {purchase.purchaseID} - "
            f"user {user.userID} email not verified"
        )
        return

    purchaseAmount = Decimal(str(purchase.packPrice))
    currentMonth = timeMachine.currentMonth

    # Update volumes
    await self._updatePersonalVolume(user, purchaseAmount, currentMonth)
    await self._updateTeamVolumeChain(user, purchaseAmount)

async def _updateTeamVolumeChain(self, user: User, amount: Decimal):
    """Update team volumes up the upline chain."""

    from utils.helpers import is_email_confirmed

    currentUser = user

    while currentUser.upline:
        uplineUser = self.session.query(User).filter_by(
            telegramID=currentUser.upline
        ).first()

        if not uplineUser:
            break

        # SKIP unverified users in volume calculation
        if not is_email_confirmed(uplineUser):
            logger.debug(f"Skipping volume for unverified user {uplineUser.userID}")
            currentUser = uplineUser
            continue

        # Update team volume only for verified
        uplineUser.teamVolumeTotal += amount
        ...
```

**Location**: volume_service.py:25-32, 67-84
**Priority**: ❌ **CRITICAL**

---

### ❌ 7. Global Pool Qualification (global_pool_service.py:109-130)

#### Current Code:
```python
async def _findQualifiedUsers(self) -> List[Dict]:
    """Find users qualified for Global Pool."""

    qualifiedUsers = []

    # ❌ NO EMAIL VERIFICATION FILTER!

    allUsers = self.session.query(User).filter(
        User.isActive == True
    ).all()

    for user in allUsers:
        if await self._checkGlobalPoolQualification(user):
            qualifiedUsers.append({
                "userId": user.userID,
                ...
            })

    return qualifiedUsers
```

#### Required Fix:
```python
async def _findQualifiedUsers(self) -> List[Dict]:
    """Find users qualified for Global Pool."""

    from utils.helpers import is_email_confirmed

    qualifiedUsers = []

    allUsers = self.session.query(User).filter(
        User.isActive == True
    ).all()

    for user in allUsers:
        # SKIP unverified users
        if not is_email_confirmed(user):
            continue

        if await self._checkGlobalPoolQualification(user):
            qualifiedUsers.append({
                "userId": user.userID,
                ...
            })

    return qualifiedUsers
```

**Location**: global_pool_service.py:117-129
**Priority**: ❌ **CRITICAL**

---

### ❌ 8. Company Monthly Volume (global_pool_service.py:92-107)

#### Current Code:
```python
async def _calculateCompanyMonthlyVolume(self) -> Decimal:
    """Calculate total company volume for current month."""

    totalVolume = Decimal("0")

    # ❌ NO EMAIL VERIFICATION FILTER!

    users = self.session.query(User).filter(
        User.isActive == True
    ).all()

    for user in users:
        if user.mlmVolumes:
            monthlyPV = Decimal(user.mlmVolumes.get("monthlyPV", "0"))
            totalVolume += monthlyPV

    return totalVolume
```

#### Required Fix:
```python
async def _calculateCompanyMonthlyVolume(self) -> Decimal:
    """Calculate total company volume for current month."""

    from utils.helpers import is_email_confirmed

    totalVolume = Decimal("0")

    users = self.session.query(User).filter(
        User.isActive == True
    ).all()

    for user in users:
        # SKIP unverified users
        if not is_email_confirmed(user):
            continue

        if user.mlmVolumes:
            monthlyPV = Decimal(user.mlmVolumes.get("monthlyPV", "0"))
            totalVolume += monthlyPV

    return totalVolume
```

**Location**: global_pool_service.py:98-106
**Priority**: ❌ **CRITICAL**

---

### ❌ 9. Legacy Purchases (background/legacy_processor.py:503-589)

#### Current Code:
```python
async def _create_purchase(self, session: Session, user: LegacyUserRecord) -> bool:
    """Create a purchase for legacy user."""

    db_user = self._get_user_from_legacy_record(session, user)

    # ❌ NO EMAIL VERIFICATION CHECK!

    # Create purchase
    purchase = Purchase()
    purchase.userID = db_user.userID
    session.add(purchase)

    # Add balance
    balance_record = ActiveBalance()
    balance_record.amount = total_price
    session.add(balance_record)

    session.commit()

    # ❌ SHOULD emit PURCHASE_COMPLETED (see separate bug report)
```

#### Required Fix:
```python
async def _create_purchase(self, session: Session, user: LegacyUserRecord) -> bool:
    """Create a purchase for legacy user."""

    from utils.helpers import is_email_confirmed

    db_user = self._get_user_from_legacy_record(session, user)

    if not db_user:
        return False

    # CHECK EMAIL VERIFICATION
    if not is_email_confirmed(db_user):
        logger.warning(
            f"Legacy purchase skipped for user {db_user.email} - email not verified"
        )
        return False

    # Create purchase
    ...
```

**Location**: background/legacy_processor.py:503-515
**Priority**: ❌ **CRITICAL**

---

## Summary of Violations

| Operation | File | Line | Email Check? | Impact |
|-----------|------|------|--------------|--------|
| Purchase Creation | handlers/projects.py | 446 | ❌ NO | Unverified can buy |
| Transfers (Sender) | handlers/transfers.py | 571 | ❌ NO | Unverified can send money |
| Transfers (Recipient) | handlers/transfers.py | 571 | ❌ NO | Unverified can receive money |
| Payment Approval | (not implemented) | N/A | ❌ NO | Unverified can deposit |
| Differential Commission | commission_service.py | 77 | ❌ NO | Generates commissions |
| Referral Bonus | commission_service.py | 270 | ❌ NO | Unverified get bonuses |
| Pioneer Bonus | commission_service.py | 171 | ❌ NO | Unverified get +4% |
| Volume Update | volume_service.py | 25 | ❌ NO | Unverified counted in MLM |
| Volume Chain | volume_service.py | 67 | ❌ NO | Unverified upline gets credit |
| Global Pool Qualified | global_pool_service.py | 109 | ❌ NO | Unverified can qualify |
| Company Volume | global_pool_service.py | 92 | ❌ NO | Unverified volume counted |
| Legacy Purchase | legacy_processor.py | 503 | ❌ NO | Legacy without email OK |

**Total Violations**: 12 critical locations
**Email Checks Found**: 0

---

## Impact Scenarios

### Scenario 1: Unverified User Purchases $10,000

**Current Behavior** (WRONG):
1. ✗ User creates purchase successfully
2. ✗ Purchase triggers PURCHASE_COMPLETED event
3. ✗ VolumeService counts PV, FV, TV
4. ✗ CommissionService calculates upline bonuses
5. ✗ ReferralBonus gives 1% to sponsor ($100)
6. ✗ PioneerBonus adds +4% if applicable ($400)
7. ✗ InvestmentBonusService may trigger
8. ✗ User becomes isActive if PV >= $200
9. ✗ Can qualify for Global Pool
10. ✗ Fully participates in MLM structure

**Expected Behavior** (CORRECT):
1. ✅ Purchase blocked with error message
2. ✅ User prompted to verify email
3. ✅ NO MLM processing
4. ✅ NO balance changes
5. ✅ Complete isolation from system

---

### Scenario 2: Unverified User in Upline Chain

User A (verified) → User B (UNVERIFIED) → User C (verified)

**Current Behavior** (WRONG):
- User C purchases $1000
- ✗ User B receives team volume credit (+$1000)
- ✗ User B may receive differential commission
- ✗ User B counted in User A's structure
- ✗ User A's qualifyingVolume includes User C via User B

**Expected Behavior** (CORRECT):
- User C purchases $1000
- ✅ User B SKIPPED (as if doesn't exist)
- ✅ Volume/commission goes directly A → C
- ✅ User B receives NOTHING
- ✅ User B invisible in MLM structure

---

## Required Fixes Summary

### Immediate Actions (CRITICAL - implement first)

1. **Purchase Handler** (handlers/projects.py:446)
   - Add email check at start of confirm_purchase()
   - Show error template if not verified
   - Estimated effort: 15 minutes

2. **Transfer Handler** (handlers/transfers.py:~500)
   - Check both sender AND recipient
   - Block transfer if either unverified
   - Estimated effort: 20 minutes

3. **Commission Service** (commission_service.py:77, 270)
   - Return empty list if purchaser unverified
   - Skip unverified users in upline chain
   - Estimated effort: 30 minutes

4. **Volume Service** (volume_service.py:25, 67)
   - Return early if purchaser unverified
   - Skip unverified users in chain
   - Estimated effort: 20 minutes

5. **Global Pool Service** (global_pool_service.py:117, 98)
   - Filter out unverified from qualified users
   - Exclude unverified from company volume
   - Estimated effort: 15 minutes

### Secondary Actions

6. **Legacy Processor** (legacy_processor.py:503)
   - Check email before creating legacy purchase
   - Estimated effort: 10 minutes

7. **Payment Approval** (to be implemented)
   - When implemented, MUST check email
   - Estimated effort: Included in implementation

---

## Implementation Strategy

### Phase 1: Block User Actions (15 minutes)
- handlers/projects.py:446 (purchase)
- handlers/transfers.py (send/receive)

**Result**: Unverified users cannot initiate operations

### Phase 2: Block MLM Participation (1 hour)
- commission_service.py (all methods)
- volume_service.py (all methods)
- global_pool_service.py (all methods)

**Result**: Unverified users don't participate in MLM even if somehow get purchase

### Phase 3: Legacy & Edge Cases (30 minutes)
- legacy_processor.py
- Any other edge cases found

**Total Estimated Effort**: 2-3 hours

---

## Testing Recommendations

After fixes implemented, test:

1. **Unverified user attempts purchase**
   - Verify blocked with error message
   - Verify shown email verification prompt

2. **Unverified user attempts transfer**
   - Verify blocked (both send and receive)

3. **Verified user purchases with unverified upline**
   - Verify upline receives NO commission
   - Verify upline receives NO volume
   - Verify upline SKIPPED in chain

4. **Global Pool calculation**
   - Verify unverified users excluded
   - Verify unverified volume not counted

5. **Legacy migration**
   - Verify unverified legacy users skipped

---

## Conclusion

### Current Status: ❌ **0% COMPLIANT**

Email verification requirement is **COMPLETELY IGNORED** throughout the system.

Unverified users can:
- ❌ Make purchases
- ❌ Send/receive transfers
- ❌ Generate MLM commissions
- ❌ Accumulate volume
- ❌ Qualify for Global Pool
- ❌ Fully participate in all operations

### Required Actions:

**12 critical locations** need email verification checks added.

**Estimated total effort**: 2-3 hours
**Priority**: ❌ **HIGHEST** - This is a fundamental business rule violation
**Risk**: LOW - Simple boolean checks with helper function

---

**Next Step**: Implement fixes in order of priority, starting with user-facing handlers (Phase 1).
