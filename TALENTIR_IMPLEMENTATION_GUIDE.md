# TALENTIR IMPLEMENTATION GUIDE FOR JETUP-2

## Quick Reference - Most Important Files & Their Roles

### Core Business Logic (MUST IMPLEMENT)

**MLM System** (`mlm_system/`)
- `config/ranks.py` - Rank definitions & commission percentages
- `services/commission_service.py` - Differential commission calculation with compression
- `services/rank_service.py` - Rank qualification & promotion
- `services/volume_service.py` - Volume tracking (PV & TV)
- `services/global_pool_service.py` - Global pool bonus calculation

**Payment Processing** (`txid_checker.py`, `models/payment.py`)
- TXID format validation
- Blockchain verification (Etherscan V2, TRON API)
- Payment model with direction/method/status fields
- 2-step admin approval workflow

**Bonus Processing** (`bonus_processor.py`)
- 6-level referral bonus calculation
- Passive balance updates
- Bonus notifications

**Purchase Flow** (`main.py` - purchase handlers)
- Project carousel
- Option selection
- Payment method routing
- TXID submission
- Admin approval

### Database Models (COPY STRUCTURE EXACTLY)

```
models/
├── base.py           - Base model class with audit mixin
├── user.py           - User with 5 JSON fields
├── purchase.py       - Purchase with project/option FKs
├── bonus.py          - Bonus with commission type tracking
├── payment.py        - Payment with direction/method/status
├── transfer.py       - Transfer with source/recipient/balance tracking
├── active_balance.py - Active balance transactions
├── passive_balance.py - Passive balance transactions
├── notification.py   - Notification & NotificationDelivery
├── project.py        - Project with language variations
├── option.py         - Investment option/package
└── (add RankHistory & MonthlyStats)
```

### Admin Commands (`admin_commands.py` - HIGH COMPLEXITY)

**Most Important Commands:**
1. `&import` - Full Google Sheets sync
2. `&restore` - Database backup restoration
3. `&delpurchase` - Purchase deletion with balance rollback
4. `&broadcast` - Async mass messaging
5. `&testmail` - Email provider testing

**Supporting Commands:**
- `&upconfig` - Update config from Google Sheets
- `&upro` - Update projects & options
- `&ut` - Update templates
- `&check` - Payment verification
- `&legacy` - Manual legacy user migration
- `&object` - Media delivery

### Email System (`email_sender.py` - CRITICAL)

**Dual Provider Setup:**
- SMTP (mail.jetup.info) - Primary
- Mailgun - Fallback
- Secure domain list (@t-online.de, @gmx.de, @web.de)
- Provider health checking
- Template-based messages

### Notifications (`notificator.py`)

**Delivery:**
- Telegram messages (async)
- Email (HTML + text)
- Database persistence
- Retry logic with exponential backoff
- Status tracking

---

## Architecture Patterns Used

### 1. Transaction Safety Pattern

```python
# All balance-modifying operations use atomic transactions
with Session() as session:
    session.begin()
    try:
        # 1. Modify balances
        user.balancePassive += amount
        
        # 2. Create audit records
        passive_balance = PassiveBalance(...)
        session.add(passive_balance)
        
        # 3. Create notifications
        notification = Notification(...)
        session.add(notification)
        
        session.commit()
    except Exception as e:
        session.rollback()
        raise
```

### 2. Commission Calculation Pattern

```python
# Differential commissions with compression
commissions = []
lastPercentage = 0
for upline in walk_upline_chain(user):
    if not upline.isActive:
        # Mark for compression
        commissions.append({
            'userId': upline.userID,
            'compressed': True,
            'percentage': get_rank_percentage(upline)
        })
    else:
        # Calculate differential
        differential = get_rank_percentage(upline) - lastPercentage
        commissions.append({
            'userId': upline.userID,
            'amount': purchase.packPrice * differential,
            'compressed': False
        })
        lastPercentage = get_rank_percentage(upline)
```

### 3. State Machine Pattern

```python
# FSM for multi-step flows
TransferDialog states:
- select_source → select_recipient_type → enter_recipient_id → 
  enter_amount → confirm_transfer

UserDataDialog states:
- waiting_for_firstname → waiting_for_surname → waiting_for_birthday → 
  waiting_for_passport → waiting_for_country → waiting_for_city → 
  waiting_for_address → waiting_for_phone → waiting_for_email → 
  waiting_for_confirmation
```

### 4. JSON Field Pattern

```python
# Structured JSON in database for flexibility
user.mlmStatus = {
    "rankQualifiedAt": "2024-01-15T10:30:00",
    "assignedRank": "builder",
    "isFounder": true,
    "lastActiveMonth": "2024-01",
    "pioneerPurchasesCount": 5,
    "hasPioneerBonus": true
}

# Properties for backward compatibility
@property
def isPioneer(self):
    return self.mlmStatus.get('isFounder', False) if self.mlmStatus else False
```

### 5. Async Background Task Pattern

```python
# Broadcasting & legacy migration
async def run_broadcast():
    while is_running:
        # Process batch
        for recipient in batch:
            await send_to_telegram(recipient)
            await send_email(recipient)
            stats['processed'] += 1
        
        # Progress update every 200
        if stats['processed'] % 200 == 0:
            await progress_callback(stats)
        
        # Cancellation check
        if should_cancel:
            break
        
        await asyncio.sleep(batch_delay)
    
    await completion_callback(final_stats)
```

### 6. Provider Selection Pattern

```python
# Email provider routing
def select_provider(email):
    domain = get_email_domain(email)
    
    if domain in secure_domains:
        # Force SMTP for German providers
        return 'smtp'
    else:
        # Use Mailgun with SMTP fallback
        return ['mailgun', 'smtp']  # Try in order
```

---

## Key Implementation Details

### MLM Commission Calculation Complexity

**Highest Risk Areas:**
1. **Compression Logic**
   - Must skip inactive users
   - Must accumulate percentages
   - Must not exceed 18% (director max)

2. **Pioneer Bonus**
   - Count must be per-structure
   - Limited to 50 total
   - Applied after differential

3. **Referral Vs Differential**
   - Referral: Direct sponsor only, 1%
   - Differential: Multiple levels, capped at rank %

### Payment Verification Complexity

**Critical Checks:**
1. **TXID Format**
   - ETH/BNB: `0x` + 64 hex = 66 chars
   - TRX: 64 hex chars only
   - Regex: `^0x[0-9a-f]{64}$` for EVM, `^[0-9a-f]{64}$` for TRON

2. **Blockchain Verification**
   - Etherscan V2 API (chainid parameter!)
   - TRON API (different endpoint)
   - Must verify:
     - Transaction exists
     - "to" address matches our wallet
     - Transaction status success

3. **Deduplication**
   - Query Payment table
   - Check if TXID already used
   - Prevent double-processing

### Admin Command Complexity

**&import Command** (Most Complex)
- Parse mode (dry/safe/force)
- Parse tables list
- Create backup (if not dry)
- Sync each table with change tracking
- Report statistics & errors
- Handle balance mismatches

**&broadcast Command** (Async Complexity)
- Read from Google Sheets
- Test mode (first 10 only)
- Batch processing (50 per batch, 3s delay)
- Progress updates (every 200)
- Cancellation support
- Error tracking

**&delpurchase Command** (Transaction Complexity)
- Find purchase & related records
- Delete bonuses & update balances
- Delete balance transactions
- Create negative balance records
- Atomic rollback on error

---

## Data Flow Diagrams

### Purchase → Bonus Processing

```
User makes purchase ($1,000)
  ↓
Payment confirmed (admin approval)
  ↓
CommissionService.processPurchase()
  ├─ _calculateDifferentialCommissions()
  │  └─ Walk upline: User A (Director) → User B (Growth) → User C (Builder) → User D (Start)
  ├─ _applyCompression()
  │  └─ If User B inactive: accumulate 12% for next active (User C)
  ├─ _applyPioneerBonus()
  │  └─ If qualified: add +4% to commission
  └─ processReferralBonus()
     └─ If purchase >= $5,000: add 1% to direct sponsor
  ↓
Save all bonuses to database
  ↓
Update user.balancePassive for each recipient
  ↓
Create notifications for recipients
  ↓
Update volumes (User A gets $1000, User B gets $1000, etc.)
  ↓
Check rank qualifications for all recipients
```

### Payment Deposit Flow

```
User clicks "Add Balance"
  ↓
Select amount ($50/$100/$500/$1000/custom)
  ↓
Select payment method (USDT-TRC20, ETH, BNB, etc.)
  ↓
Generate invoice with wallet address
  ↓
User sends crypto to wallet
  ↓
User provides TXID in bot
  ↓
System validates:
  ├─ Format validation (regex)
  ├─ Blockchain verification (Etherscan/TRON API)
  ├─ Address verification (our wallet?)
  └─ Deduplication (TXID already used?)
  ↓
Payment status → 'check' (awaiting admin)
  ↓
Create admin notification
  ↓
Admin reviews & approves
  ↓
Payment status → 'confirmed'
  ↓
User.balanceActive += amount
  ↓
Create ActiveBalance transaction record
  ↓
Create user notification
```

### Transfer Execution

```
User initiates transfer
  ↓
Select source (active/passive)
  ↓
If passive: Select recipient type (self/other)
  ↓
Enter recipient ID / amount
  ↓
Validation:
  ├─ Sufficient balance
  ├─ Positive amount
  ├─ Valid recipient exists
  └─ Not self-transfer (if active)
  ↓
Calculate recipient amount:
  ├─ If passive→other: add +2% bonus
  └─ Otherwise: same amount
  ↓
Create Transfer record
  ↓
Deduct from sender balance
  ↓
Add to receiver balance (with bonus)
  ↓
Create balance transaction records
  ↓
Create notifications for both parties
```

---

## Testing Checklist

### Commission Calculation
- [ ] Single level commission (4%)
- [ ] Differential commission (18% - 12% = 6%)
- [ ] Compression (inactive upline skipped)
- [ ] Pioneer bonus (+4%)
- [ ] Referral bonus (1% for sponsor)
- [ ] Max percentage cap (18%)
- [ ] Chaining (6+ levels)

### Payment Processing
- [ ] TXID format validation (all 6 methods)
- [ ] Blockchain API verification
- [ ] Wrong recipient detection
- [ ] Wrong amount detection
- [ ] Duplicate TXID prevention
- [ ] Payment approval flow
- [ ] Balance update
- [ ] Notification creation

### Transfer System
- [ ] Active→Active transfer
- [ ] Passive→Self transfer
- [ ] Passive→Other transfer
- [ ] +2% bonus application
- [ ] Balance validation
- [ ] Recipient validation
- [ ] Audit trail creation

### Admin Commands
- [ ] &import dry mode
- [ ] &import safe mode with backup
- [ ] &restore from backup
- [ ] &delpurchase with rollback
- [ ] &broadcast with progress
- [ ] &broadcast cancellation
- [ ] &testmail SMTP
- [ ] &testmail Mailgun

---

## Performance Considerations

### Database Optimization
- Index on `User.isActive` (for active partner counts)
- Index on `User.rank` (for rank queries)
- Index on `User.upline` (for tree traversal)
- Index on `Purchase.userID` (for purchase queries)
- Index on `Bonus.userID` (for bonus queries)
- Denormalized fields to reduce joins

### Async Operations
- Broadcast: batch 50, delay 3s between batches
- Email: fallback providers, retry on failure
- Notifications: polling interval 10-30s
- Legacy processor: batch 50, run every 10 min

### Caching
- Google Sheets data cached (updated every load)
- Template cache (cleared on &ut command)
- Config cached in GlobalVariables

---

## Security Measures

### Transaction Security
- HMAC-SHA256 signature verification (webhooks)
- IP whitelist (Google Cloud ranges)
- Rate limiting (30 req/60s default)

### Admin Security
- Admin filter (check against config.ADMINS)
- All admin commands logged
- Backup before destructive operations
- 2-step payment approval required

### Payment Security
- TXID format validation
- Blockchain address verification
- Deduplication before processing
- Wallet address hardcoded in config

### Email Security
- Secure domain list for forced SMTP
- Provider fallback prevents single point of failure
- Template variables properly escaped

---

## Migration Priority Scoring

| Component | Complexity | Risk | Priority | Effort |
|-----------|-----------|------|----------|--------|
| User Model | LOW | LOW | P0 | 1-2d |
| Rank System | HIGH | HIGH | P0 | 3-5d |
| Commission Service | CRITICAL | CRITICAL | P0 | 5-7d |
| Payment System | HIGH | HIGH | P0 | 4-6d |
| Purchase Flow | HIGH | MEDIUM | P0 | 3-5d |
| Transfer System | MEDIUM | MEDIUM | P1 | 2-3d |
| Email System | MEDIUM | MEDIUM | P1 | 2-3d |
| Broadcast System | MEDIUM | LOW | P1 | 2-3d |
| Admin Commands | CRITICAL | HIGH | P1 | 5-7d |
| Reports | LOW | LOW | P2 | 1-2d |
| Webhooks | MEDIUM | MEDIUM | P2 | 2-3d |

**Total Estimate:** 30-45 development days (6-9 weeks)

