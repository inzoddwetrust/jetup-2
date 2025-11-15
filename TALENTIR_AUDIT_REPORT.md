# TALENTIR CODEBASE - COMPREHENSIVE BUSINESS LOGIC AUDIT

**Document Version:** 1.0  
**Audit Date:** 2025-11-15  
**Total Files Analyzed:** 58 Python modules  
**Database Type:** SQLite with SQLAlchemy ORM  

---

## EXECUTIVE SUMMARY

Talentir is a sophisticated Telegram bot-based MLM (Multi-Level Marketing) and investment platform featuring:
- **Core MLM System** with 5-tier rank structure
- **Payment Processing** for cryptocurrency deposits/withdrawals
- **Purchase Flow** with option-based investment system
- **Bonus System** with 6-level referral structure + differential commissions
- **Admin Infrastructure** with backup, import, and broadcast capabilities
- **Email/Telegram Broadcasting** system
- **Webhook Integration** with Google Sheets for data synchronization

---

## 1. BOT HANDLERS & COMMANDS

### 1.1 STATE MACHINE (FSM) STATES

**File:** `fsm_states.py`

```
UserDataDialog:
  - waiting_for_firstname
  - waiting_for_surname
  - waiting_for_birthday
  - waiting_for_passport
  - waiting_for_country
  - waiting_for_city
  - waiting_for_address
  - waiting_for_phone
  - waiting_for_email
  - waiting_for_confirmation

ProjectCarouselState:
  - wait_for_welcome
  - current_project_index
  - view_project_details

PurchaseFlow:
  - waiting_for_payment
  - waiting_for_purchase_confirmation

TxidInputState:
  - waiting_for_txid

TransferDialog:
  - select_source (active/passive balance)
  - select_recipient_type (self/other)
  - enter_recipient_id
  - enter_amount
  - confirm_transfer
```

### 1.2 MAIN BOT HANDLERS & ROUTES

**File:** `main.py` (116,573 bytes - PRIMARY BOT LOGIC)

**Key Handlers:**

#### WELCOME & SETUP
- `send_welcome()` - Initial welcome screen
- `show_welcome_screen()` - Shows EULA, checks subscriptions
- `check_subscription_handler()` - Validates required channel subscriptions
- `handle_language_select()` - Language selection (en, ru, de, in)
- `handle_eula_accept()` - EULA agreement acceptance

#### DASHBOARD & VIEWING
- `get_dashboard_template_keys()` - Generates dashboard templates
- `handle_case()` - Case/project selection
- `my_options_handler()` - Shows user's investments
- `handle_certificates()` - Certificate/document download
- `handle_strategies()` - Portfolio strategy display
- `set_strategy()` - Sets portfolio strategy (manual/safe/aggressive/risky)
- `handle_portfolio_value()` - Calculates portfolio value using strategy coefficients

#### FINANCE & BALANCE
- `finances()` - Finance menu
- `handle_balance()` - Shows active & passive balances
- `handle_balance_history()` - Balance transaction history
- `handle_payout()` - Withdrawal request handler
- `pending_invoices_handler()` - Shows unpaid invoices
- `paid_invoices_handler()` - Shows paid invoices

#### PURCHASES
- `start_carousel()` - Project carousel navigation
- `move_project()` - Navigate projects in carousel
- `view_project_details()` - View detailed project info
- `invest_in_project()` - Start investment process
- `handle_option_selection()` - Select investment option
- `proceed_to_purchase()` - Confirm option & show payment options
- `confirm_purchase()` - Complete purchase transaction
- `generate_document()` - Generate purchase certificates

#### PAYMENT FLOW
- `add_balance_start()` - Initiate deposit
- `select_amount()` - Preset amounts ($50, $100, $500, $1000, custom)
- `custom_amount_input()` - Custom amount input
- `confirm_invoice()` - Invoice confirmation
- `create_payment()` - Create payment record
- `request_txid()` - Request blockchain transaction ID
- `process_txid_input()` - Validate & verify transaction
- `cancel_payment()` - Cancel pending payment
- `create_payment_check_notification()` - Admin payment notification
- `handle_initial_approval()` - Admin payment review
- `handle_final_approval()` - Admin payment confirmation
- `handle_rejection()` - Admin payment rejection

#### TRANSFERS
- `transfer_start()` - Initiate transfer
- `handle_transfer_callback()` - Transfer menu selection
- `handle_transfer_input()` - Transfer input handling
- `confirm_transfer()` - Confirm & execute transfer

#### USER DATA MANAGEMENT
- `fill_user_data()` - Start user profile completion
- `handle_user_data_input()` - Process input (name, birthday, phone, etc)
- `confirm_user_data()` - Confirm profile data
- `restart_user_data()` - Restart data entry
- `edit_user_data()` - Edit existing data
- `resend_verification_email()` - Resend email verification

#### TEAM & REFERRALS
- `handle_team()` - Team management menu
- `start_referral_link_dialog()` - Show referral link
- `show_referral_link()` - Display unique referral code
- `show_marketing_info()` - Marketing materials
- `handle_team_stats()` - Team statistics

#### SETTINGS & ADMIN
- `handle_settings()` - User settings menu
- `handle_settings_language_select()` - Change language
- `handle_info_screen()` - Information screen
- `handle_csv_download()` - Download reports
- `handle_dw_instructions()` - Deposit/withdrawal instructions
- `download_project_pdf()` - PDF download

---

## 2. DATABASE MODELS

**Directory:** `/models/` - 12 models using SQLAlchemy ORM

### 2.1 USER MODEL (`models/user.py`)

**Primary Fields:**
- `userID` (Primary Key, auto-increment)
- `telegramID` (Unique, BigInteger)
- `upline` (BigInteger - sponsor's telegram ID)
- `createdAt` (DateTime with timezone)

**Personal Information:**
- `email`, `firstname`, `surname`, `birthday`, `passport`
- `address`, `phoneNumber`, `city`, `country`

**System Fields:**
- `lang` (Language preference)
- `status` (active/blocked/deleted)
- `lastActive` (DateTime of last activity)

**Balances:**
- `balanceActive` (DECIMAL 12,2)
- `balancePassive` (DECIMAL 12,2)

**MLM System Fields:**
- `rank` (start/builder/growth/leadership/director) - indexed
- `isActive` (Boolean - indexed) - True if PV >= 200 current month
- `teamVolumeTotal` (DECIMAL 12,2)

**JSON Fields (Key Features):**

```python
mlmStatus = {
    "rankQualifiedAt": null,
    "assignedRank": null,
    "isFounder": false,  # Pioneer status
    "lastActiveMonth": null,
    "pioneerPurchasesCount": 0,
    "hasPioneerBonus": false
}

mlmVolumes = {
    "personalTotal": 0.0,      # Cumulative personal volume
    "monthlyPV": 0.0,          # Personal volume (current month)
    "autoship": {
        "enabled": false, 
        "amount": 200
    }
}

personalData = {
    "eulaAccepted": true,
    "eulaVersion": "1.0",
    "eulaAcceptedAt": "2024-01-01T10:00:00",
    "dataFilled": false,
    "kyc": {
        "status": "not_started|pending|verified|rejected",
        "verifiedAt": null,
        "documents": [],
        "level": 0
    }
}

emailVerification = {
    "confirmed": false,
    "token": "...",
    "sentAt": "2024-01-15T10:30:00",
    "confirmedAt": null,
    "attempts": 1
}

settings = {
    "strategy": "manual|safe|aggressive|risky",
    "notifications": {"bonus": true, "purchase": true},
    "display": {"showBalance": true}
}
```

**Properties & Methods:**
- `isFilled` - Backward compatibility for data completion status
- `kyc` - KYC verification status (verified boolean)
- `emailConfirmed` - Email verification status
- `strategy` - Portfolio strategy getter/setter
- `isPioneer` - Pioneer status getter/setter
- `monthlyPV` - Monthly PV getter/setter
- `personalVolume` - Cumulative personal volume
- `has_filled_data()` - Check all required fields
- `needs_email_verification()` - Check email verification need
- `can_make_purchases()` - Check purchase eligibility

### 2.2 PURCHASE MODEL (`models/purchase.py`)

**Fields:**
- `purchaseID` (Primary Key)
- `userID` (FK → users)
- `optionID` (FK → options)
- `projectID` (Index, no FK due to composite key)
- `projectName` (String)
- `packQty` (Integer - shares purchased)
- `packPrice` (DECIMAL 12,2 - total investment)

**Relationships:**
- user → User (many-to-one)
- option → Option (many-to-one)
- bonuses → Bonus (one-to-many)

**Audit Mixin:**
- `createdAt`, `updatedAt` (DateTime)
- `ownerTelegramID`, `ownerEmail` (Audit trail)

### 2.3 BONUS MODEL (`models/bonus.py`)

**Fields:**
- `bonusID` (Primary Key)
- `userID` (FK - receiver)
- `downlineID` (FK - who generated the bonus)
- `purchaseID` (FK)

**MLM Commission Details:**
- `commissionType` (differential/referral/pioneer/global_pool)
- `uplineLevel` (1, 2, 3... - position in chain)
- `fromRank` (receiver's rank)
- `sourceRank` (source rank for differential)

**Calculation Fields:**
- `bonusRate` (Float - percentage 0.04 for 4%)
- `bonusAmount` (DECIMAL 12,2)
- `compressionApplied` (Integer 0/1)

**Denormalized Data:**
- `projectID`, `optionID`, `packQty`, `packPrice`

**Status:**
- `status` (pending/processing/paid/cancelled/error)
- `notes` (Text field)

### 2.4 PAYMENT MODEL (`models/payment.py`)

**Fields:**
- `paymentID` (Primary Key)
- `userID` (FK)
- `firstname`, `surname` (Denormalized)

**Payment Details:**
- `direction` ('in' for deposit, 'out' for withdrawal)
- `amount` (DECIMAL 12,2 - in USD)
- `method` (USDT-TRC20/ETH/BNB/USDT-BSC20/USDT-ERC20/TRX)
- `sumCurrency` (DECIMAL 12,8 - for crypto precision)

**Wallet Information:**
- `fromWallet` (Sender's crypto address)
- `toWallet` (Recipient wallet address)

**Transaction Info:**
- `txid` (Blockchain transaction ID)
- `status` (pending/check/confirmed/rejected/cancelled)

**Confirmation:**
- `confirmedBy` (Admin username)
- `confirmationTime` (DateTime)
- `notes` (Text)

### 2.5 TRANSFER MODEL (`models/transfer.py`)

**Fields:**
- `transferID` (Primary Key)
- `senderUserID` (FK)
- `senderFirstname`, `senderSurname`
- `fromBalance` ('active' or 'passive')
- `amount` (DECIMAL 12,2)
- `receiverUserID` (FK)
- `receiverFirstname`, `receiverSurname`
- `toBalance` ('active' or 'passive')

**Status:**
- `status` (pending/completed/cancelled/error)
- `notes`

### 2.6 ACTIVE_BALANCE & PASSIVE_BALANCE MODELS

**Active Balance** (`models/active_balance.py`):
- Tracks active balance transactions
- `amount` (positive or negative)
- `reason` (payment=ID/transfer=ID/purchase=ID)
- `link` (Reference to source transaction)

**Passive Balance** (`models/passive_balance.py`):
- Tracks passive (bonus) balance transactions
- `amount` (positive or negative)
- `reason` (bonus=ID/transfer=ID/commission=ID)
- `link` (Reference to source bonus)

Both include:
- `userID`, `firstname`, `surname`
- `status` (pending/done/cancelled/error)
- `notes`
- Audit fields

### 2.7 NOTIFICATION MODELS (`models/notification.py`)

**Notification:**
- `notificationID` (Primary Key)
- `source` (payment_checker/bonus_processor/system)
- `text` (Content)
- `buttons` (Inline keyboard JSON)
- `targetType` (user/admin/broadcast)
- `targetValue` (userID/telegramID)
- `priority` (1-10)
- `category` (bonus/payment/purchase/system)
- `importance` (normal/high/urgent)
- `status` (pending/sent/failed/cancelled)
- `sentAt`, `failureReason`, `retryCount`
- `parseMode` (HTML/Markdown)
- `expiryAt`, `silent`, `autoDelete`

**NotificationDelivery:**
- Tracks delivery attempts
- `status` (pending/sent/failed)
- `attempts`, `errorMessage`

### 2.8 PROJECT MODEL (`models/project.py`)

**Fields:**
- `projectID`, `lang` (Composite key)
- `projectName`, `projectTitle`
- `fullText` (Description)
- `status` (Availability)
- `rate` (Float - valuation)
- `linkImage`, `linkPres`, `linkVideo` (Resources)
- `docsFolder` (Path to documentation)

### 2.9 OPTION MODEL (`models/option.py`)

**Fields:**
- `optionID` (Primary Key)
- `projectID` (No FK - flexibility)
- `projectName`
- `costPerShare` (Float)
- `packQty` (Integer - shares per pack)
- `packPrice` (Float - total per pack)
- `isActive` (Boolean)

---

## 3. BUSINESS LOGIC - MLM SYSTEM

**Directory:** `mlm_system/` - Advanced MLM implementation

### 3.1 RANK SYSTEM

**File:** `mlm_system/config/ranks.py`

**Rank Hierarchy:**
```
START (Default)
  - Commission: 4%
  - Requirements: None
  
BUILDER
  - Commission: 8%
  - Team Volume: $50,000
  - Active Partners: 2
  
GROWTH
  - Commission: 12%
  - Team Volume: $250,000
  - Active Partners: 5
  
LEADERSHIP
  - Commission: 15%
  - Team Volume: $1,000,000
  - Active Partners: 10
  
DIRECTOR
  - Commission: 18%
  - Team Volume: $5,000,000
  - Active Partners: 15
```

**Activation Criteria:**
- Monthly PV (Personal Volume) >= $200 = ACTIVE status
- isActive field indexed for performance
- Team Volume = sum of all downline volumes

### 3.2 COMMISSION TYPES

**File:** `mlm_system/services/commission_service.py`

#### A. DIFFERENTIAL COMMISSIONS (Primary)

Mechanism:
1. Walk up upline chain
2. Calculate difference between user rank % and previous rank %
3. Apply compression if inactive users in chain
4. Each active user gets differential only

Example:
```
Purchase: $1,000

User A (Director 18%) → Bonus: $1,000 × 18% = $180
User B (Growth 12%) → Bonus: $1,000 × (12% - 18%) = $0 (compressed)
User C (Builder 8%) → Bonus: $1,000 × 8% = $80
User D (Start 4%) → Bonus: $1,000 × 4% = $40

Total Distributed: $300
```

#### B. COMPRESSION MECHANISM

When upline is inactive (isActive=false):
- Skip inactive user
- Accumulate their percentage
- Pass to next active user up the chain

#### C. PIONEER BONUS

- Additional +4% for first 50 purchases in structure
- Tracked in `mlmStatus.pioneerPurchasesCount`
- Applied on top of differential commission
- Added by `_applyPioneerBonus()` method

#### D. REFERRAL BONUS (6-LEVEL SYSTEM)

**File:** `bonus_processor.py`

Configuration (`config.py`):
```python
PURCHASE_BONUSES = {
    "level_1": 10,  # 10%
    "level_2": 4,   # 4%
    "level_3": 2,   # 2%
    "level_4": 1,   # 1%
    "level_5": 1,   # 1%
    "level_6": 1    # 1%
}
```

**Legacy Referral Bonus System:**
- Direct sponsor gets $50 for purchase >= $5,000 (1%)
- Continues up 6 levels with decreasing %
- Deprecated in new differential system but maintained for compatibility
- Only processes if purchase price >= `REFERRAL_BONUS_MIN_AMOUNT` ($5,000)

### 3.3 GLOBAL POOL BONUS

**Configuration:**
- `GLOBAL_POOL_PERCENTAGE`: 2% of all transactions
- `PIONEER_BONUS_PERCENTAGE`: 4% for pioneers
- `TRANSFER_BONUS_PERCENTAGE`: 2% bonus when transferring from passive

**Service:** `mlm_system/services/global_pool_service.py`

### 3.4 VOLUME TRACKING

**File:** `mlm_system/services/volume_service.py`

**Volume Types:**

1. **Personal Volume (PV)**
   - User's own purchases
   - Field: `mlmVolumes.monthlyPV` (resets monthly)
   - Cumulative: `mlmVolumes.personalTotal`
   - Activation trigger: >= $200/month

2. **Team Volume (TV)**
   - Sum of all downline purchases
   - Field: `teamVolumeTotal` (cumulative)
   - Requirement for rank qualification

**Updates Triggered By:**
- Purchase completion
- Monthly reset (handled by time machine)

### 3.5 RANK SERVICE

**File:** `mlm_system/services/rank_service.py`

**Methods:**
- `checkRankQualification(userId)` - Check if user qualifies for promotion
- `_isQualifiedForRank(user, rank)` - Validate rank requirements
- `_countActivePartners(user)` - Count active direct referrals
- `updateUserRank(userId, newRank, method)` - Update and record change

**Rank History:**
- Tracked in separate `RankHistory` model
- Records method: 'natural'/assigned'/'promotion'

### 3.6 MONTHLY STATS & RESET

**File:** `mlm_system/models/monthly_stats.py`

Tracks monthly performance:
- Monthly volumes
- Active status
- Commission totals
- Stored separately for historical analysis

---

## 4. PAYMENT SYSTEM

### 4.1 PAYMENT FLOW

**Deposit Flow:**
1. User selects amount ($50/$100/$500/$1000/custom)
2. Selects payment method (USDT-TRC20/ETH/BNB/etc)
3. System generates invoice with wallet address
4. User sends crypto to provided wallet
5. User provides TXID for verification
6. Admin approval (2-step)
7. Balance updated (status='confirmed')

**Withdrawal Flow:**
1. User requests withdrawal from active balance
2. Creates payment with direction='out'
3. Admin reviews & approves
4. Balance deducted
5. Crypto sent to user wallet

### 4.2 SUPPORTED CURRENCIES & WALLETS

**Configuration** (`config.py`):

```python
WALLETS = {
    "USDT-TRC20": WALLET_TRC,      # TRC-20 stablecoin
    "TRX": WALLET_TRC,             # Tron
    "ETH": WALLET_ETH,             # Ethereum
    "BNB": WALLET_ETH,             # BSC
    "USDT-BSC20": WALLET_ETH,      # BSC stablecoin
    "USDT-ERC20": WALLET_ETH       # Ethereum stablecoin
}

STABLECOINS = ["USDT-ERC20", "USDT-BSC20", "USDT-TRC20"]
```

### 4.3 TRANSACTION VERIFICATION

**File:** `txid_checker.py`

**Validation Steps:**

1. **Format Validation:**
   - ETH/BNB/USDT-ERC20/USDT-BSC20: 0x + 64 hex chars (66 total)
   - TRX/USDT-TRC20: 64 hex chars
   - Regex pattern matching

2. **Blockchain Verification:**
   - Etherscan API V2 for EVM chains (ETH, BNB, USDT-ERC20, USDT-BSC20)
   - TRON API for TRX/USDT-TRC20
   - Verify transaction exists
   - Check sender & recipient addresses
   - Confirm transaction status

3. **Validation Codes:**
   ```python
   VALID_TRANSACTION
   INVALID_PREFIX/LENGTH/CHARS
   UNSUPPORTED_METHOD
   TRANSACTION_NOT_FOUND
   WRONG_RECIPIENT
   WRONG_NETWORK
   API_ERROR
   TXID_ALREADY_USED
   NEEDS_CONFIRMATION
   ```

4. **Deduplication:**
   - Check if TXID already used in Payment table
   - Prevents duplicate processing

### 4.4 PAYMENT NOTIFICATIONS

**Admin Notifications:**
- Payment check notifications (status='check')
- Amount, currency, method, user info
- Approval/rejection actions via inline buttons

**User Notifications:**
- Confirmation when approved
- Rejection with reason
- Balance update notification

---

## 5. PURCHASE FLOW

**Complete Workflow:**

```
1. START
   ↓
2. PROJECT CAROUSEL
   - View projects available for investment
   - Language-specific descriptions
   
3. PROJECT DETAILS
   - View full description
   - See investment options
   
4. OPTION SELECTION
   - Choose investment package
   - See quantity & price
   
5. PAYMENT METHOD SELECTION
   - Choose crypto method
   - Auto-calculate in selected currency
   
6. PAYMENT CONFIRMATION
   - Show payment details
   - Provide wallet address
   
7. TXID INPUT
   - User provides blockchain transaction ID
   - System validates format & blockchain
   
8. ADMIN APPROVAL
   - Two-step process:
     a) Initial review (status='check')
     b) Final approval (status='confirmed')
   
9. BONUS CALCULATION
   - Process differential commissions
   - Apply compression
   - Add pioneer bonus if applicable
   - Add referral bonuses
   
10. COMPLETION
    - Update user balance
    - Create notifications
    - Update volumes
    - Check rank qualification
```

**Purchase Model Fields Populated:**
- `purchaseID`, `userID`, `optionID`, `projectID`, `projectName`
- `packQty` (number of shares)
- `packPrice` (total investment amount)
- `createdAt`, `updatedAt` (audit)

---

## 6. TRANSFER SYSTEM

**File:** `transfer_manager.py`

### 6.1 TRANSFER TYPES

**Active Balance Transfers:**
- User-to-user only (cannot transfer to self)
- Deducts from sender's active balance
- Adds to receiver's active balance
- No bonus applied

**Passive Balance Transfers:**
- User can transfer to self or others
- Deducts from sender's passive balance
- Can be transferred to:
  - User's own active balance
  - Another user's passive balance
- **BONUS: +2% transfer bonus** (`TRANSFER_BONUS`)

### 6.2 TRANSFER FLOW

1. Select source (active/passive)
2. If passive and recipient is other user:
   - If transferring to other's passive: +2% bonus
3. Select recipient (for passive)
4. Enter amount
5. Validation:
   - Positive amount
   - Sufficient balance
   - Recipient exists
   - Not self-transfer (active only)
6. Confirmation
7. Execution:
   - Deduct from sender
   - Add to receiver (with bonus if applicable)
   - Create transfer record
   - Create balance records

---

## 7. ADMIN FEATURES

**File:** `admin_commands.py` (1,400+ lines)

### 7.1 ADMIN COMMAND ROUTING

All commands start with `&` and are checked in `handle_admin_command()`:

```python
command = message.text[1:].split()[0].lower()

if command == "import":        # &import [mode] [tables]
elif command == "restore":     # &restore [backup_file]
elif command == "object":      # &object {file_id}
elif command == "upconfig":    # &upconfig
elif command == "upro":        # &upro (update projects & options)
elif command == "ut":          # &ut (update templates)
elif command.startswith("delpurchase"):  # &delpurchase {purchaseID}
elif command == "testmail":    # &testmail [email] [provider]
elif command == "broadcast":   # &broadcast [--test] [--nomail] [--status] [--cancel]
elif command == "check":       # &check (payment verification)
elif command == "legacy":      # &legacy (legacy user migration)
```

### 7.2 &IMPORT COMMAND - GOOGLE SHEETS SYNC

**Usage:**
```
&import [mode] [tables]

Modes:
  dry    - Preview changes without applying (default)
  safe   - Apply changes with backup
  force  - Apply changes immediately

Tables:
  Users, Payments, Projects, Options, Bonuses, Purchases
  Or comma-separated: &import safe Users,Payments
```

**Features:**
- Syncs data from Google Sheets
- Creates backup before non-dry mode
- Reports changes/additions/deletions
- Supports partial imports
- Detects balance mismatches
- Shows errors with row numbers

**Implementation:**
- Uses `UniversalSyncEngine` from sync_system
- Supports SYNC_CONFIG definition
- Tracks statistics: total/updated/added/skipped/errors

### 7.3 &RESTORE COMMAND - BACKUP RESTORATION

**Usage:**
```
&restore [backup_file]

If no file specified: lists available backups
```

**Features:**
- Lists last 5 backups in `/backups/import/`
- Creates current DB backup before restore
- Replaces database with backup
- Shows success/error message

### 7.4 &UPCONFIG COMMAND - CONFIG UPDATE

**Usage:**
```
&upconfig
```

**Updates:**
- Loads config from Google Sheets "Config" sheet
- Updates Python config module
- Updates GlobalVariables:
  - PURCHASE_BONUSES
  - STRATEGY_COEFFICIENTS
  - TRANSFER_BONUS
  - SOCIAL_LINKS
  - FAQ_URL
  - REQUIRED_CHANNELS
  - PROJECT_DOCUMENTS
- Reloads email secure domains

### 7.5 &OBJECT COMMAND - MEDIA DELIVERY

**Usage:**
```
&object {file_id}
```

**Features:**
- Sends Telegram media by file_id
- Attempts multiple media types: sticker/photo/video/document/animation/audio/voice/video_note
- Reports detected media type
- Useful for testing & distribution

### 7.6 &TESTMAIL COMMAND - EMAIL TESTING

**Usage:**
```
&testmail [email] [provider]

Providers: smtp, mailgun
```

**Features:**
- Tests email configuration
- Smart provider selection
- Secure domain detection
- Fallback provider info
- Tests both SMTP and Mailgun
- Sends actual test email
- Reports success/failure with detailed status

### 7.7 &BROADCAST COMMAND - MASS MESSAGING

**Usage:**
```
&broadcast [--test] [--nomail] [--status] [--cancel]

Flags:
  --test   - Test mode (first 10 recipients)
  --nomail - Bot only, skip email
  --status - Check broadcast progress
  --cancel - Stop running broadcast
```

**Features:**
- Reads recipients from Google Sheets (configurable URL)
- Async background processing
- Progress updates every 200 recipients
- Batch email sending (50 emails per batch, 3-second delay)
- Tracks bot sends vs email sends
- Handles errors gracefully
- Cancellation support
- Detailed final report

**Implementation:**
- File: `broadcast_manager.py`
- Uses `BroadcastManager` class
- Telegram + Email delivery
- Template-based messages

### 7.8 &DELPURCHASE COMMAND - PURCHASE DELETION

**Usage:**
```
&delpurchase {purchaseID}
```

**Features:**
- Shows analysis: related bonuses, balance records, amounts
- Requires confirmation
- Deletes:
  - Purchase record
  - All related bonuses
  - Related balance transactions
- Adjusts user balances:
  - Restores active balance (purchase price)
  - Removes passive balance (bonuses paid)
- Creates audit trail
- Atomic transaction with rollback

### 7.9 &UPRO COMMAND - PROJECT UPDATE

**Usage:**
```
&upro
```

**Features:**
- Imports from Google Sheets sheets: "Projects" & "Options"
- Uses `ProjectImporter` & `OptionImporter`
- Clears BookStack template cache
- Updates project descriptions & options

### 7.10 &UT COMMAND - TEMPLATE UPDATE

**Usage:**
```
&ut
```

**Features:**
- Reloads all message templates
- Updates from BookStack or local storage
- Clears cache
- Useful for live template updates without restart

### 7.11 &CHECK COMMAND - PAYMENT VERIFICATION

**Usage:**
```
&check
```

**Features:**
- Finds all payments with status='check'
- Creates admin notifications for review
- Removes stale notifications
- Reports count & total amount pending

### 7.12 &LEGACY COMMAND - LEGACY USER PROCESSOR

**Usage:**
```
&legacy
```

**Features:**
- Triggers legacy user migration manually
- Reads from LEGACY_SHEET_ID Google Sheet
- Processes in batch
- Reports: users found, upliners assigned, purchases created
- Shows error details
- Prevention of concurrent runs

---

## 8. BACKGROUND SERVICES

### 8.1 NOTIFICATION PROCESSOR

**File:** `notificator.py`

**Features:**
- Processes pending notifications
- Supports multiple delivery methods:
  - Telegram messages
  - Email (via Mailgun/SMTP)
- Retry logic with exponential backoff
- Template variable substitution
- Keyboard button generation
- Silent notifications
- Auto-deletion
- Priority-based processing

**Notification Status Workflow:**
```
pending → sent (success) or retry → failed or cancelled
```

### 8.2 LEGACY USER PROCESSOR

**File:** `legacy_user_processor.py`

**Configuration:**
- LEGACY_SHEET_ID: "1mbaRSbOs0Hc98iJ3YnZnyqL5yxeSuPJCef5PFjPHpFg"
- Automatic run every 10 minutes
- Batch size: 50 records
- Auto-recovery on errors

**Processing Steps:**
1. Load legacy user data from Google Sheets
2. Find user by email (case-insensitive, Gmail dots removed)
3. Assign upliner from legacy data
4. Create purchase record
5. Process bonuses for purchase
6. Update sheet with results

**Error Tracking:**
- Up to 3 retries per record
- Auto-skip after 3 errors
- Detailed error logging

### 8.3 INVOICE CLEANER

**File:** `invoice_cleaner.py`

**Function:**
- Periodically cleans old/expired invoices
- Maintains payment history

### 8.4 EMAIL SENDER

**File:** `email_sender.py`

**Providers:**
- SMTP (own mail server)
- Mailgun (external service)

**Features:**
- Smart provider selection based on domain
- Secure domain list for forced SMTP
- Fallback provider support
- Async sending
- HTML + text body support
- Provider health checking

**Provider Configuration:**
```python
SMTP_HOST = mail.jetup.info
SMTP_PORT = 587
SMTP_USER = noreply@jetup.info

MAILGUN_DOMAIN = mg.jetup.info
MAILGUN_REGION = eu
MAILGUN_FROM_EMAIL = noreply@jetup.info
```

**Secure Domains (use SMTP only):**
```
@t-online.de, @gmx.de, @web.de (German providers)
```

### 8.5 MESSAGE MANAGER

**File:** `message_manager.py`

**Features:**
- Template-based message sending
- Multi-language support
- Inline keyboard generation
- Error handling & retries
- Variable substitution

---

## 9. BROADCAST SYSTEM

**File:** `broadcast_manager.py` (comprehensive broadcasting)

### 9.1 BROADCAST WORKFLOW

1. **Data Source:**
   - Google Sheets with "Recipients" sheet
   - Columns: email, first_name, telegram_id, message_key, etc.

2. **Processing:**
   - Optional test mode (first 10 recipients)
   - Optional skip email (bot-only mode)
   - Batch processing (50 per batch)
   - 3-second delay between batches
   - Progress reports every 200 recipients

3. **Delivery:**
   - **Telegram:** Message sent via bot
   - **Email:** Template-based HTML email
   - Fallback on email failure

4. **Reporting:**
   - Total recipients
   - Bot sent/failed counts
   - Email sent/failed counts
   - Detailed error log
   - Cancellation status

### 9.2 BROADCAST STATISTICS

```python
stats = {
    'total_recipients': 0,
    'bot_sent': 0,
    'bot_failed': 0,
    'email_sent': 0,
    'email_failed': 0,
    'email_skipped': 0,
    'not_found_in_db': 0,
    'errors': []
}
```

---

## 10. PAYOUT SYSTEM

### 10.1 WITHDRAWAL REQUEST FLOW

1. **Initiation:**
   - User selects withdrawal amount
   - Amount must be <= active balance
   - Select payment method

2. **Record Creation:**
   - Create Payment record
   - direction='out'
   - status='pending'

3. **Admin Approval:**
   - Two-step process (initial review + final approval)
   - Admin provides wallet address for recipient
   - Admin confirms amount

4. **Balance Deduction:**
   - Update user.balanceActive
   - Create ActiveBalance transaction record
   - Mark payment as status='confirmed'

5. **Crypto Dispatch:**
   - Manual or automated crypto transfer
   - Record TXID in payment record
   - Create notification to user

### 10.2 PAYOUT RESTRICTIONS

- Minimum payout amount (configured)
- User must have filled personal data
- Email must be verified
- Cannot exceed available balance
- Maximum per transaction (if configured)

---

## 11. REPORTS & EXPORTS

**File:** `csv_reports.py`

### 11.1 REPORT TYPES

**1. Team Full Report**
```
Headers: ID, Name, Reg Date, Level, Direct Refs, Total Team, 
         Purchases Amt, Bonus Gained, Purchase ID, P.Date, Project, Shares, Price

Data: 
- User info with team size
- Nested referrals
- Purchase details for each user
```

**2. Active Balance History**
```
Headers: Transaction ID, Date, Amount, Status, Reason, Details, Notes

Data:
- All active balance transactions
- Deposit/withdrawal/transfer records
- Sorted newest first
```

**3. Passive Balance History**
```
Headers: Transaction ID, Date, Amount, Status, Reason, Details, Notes

Data:
- All bonus/commission transactions
- Bonus payment records
- Transfer history
- Sorted newest first
```

### 11.2 REPORT GENERATION

**Function:** `generate_csv_report(session, user, report_type, params)`

**Features:**
- In-memory BytesIO generation
- UTF-8 with BOM for Excel compatibility
- Semicolon delimiter (Excel-friendly)
- User-filtered data
- Recursive team calculation

---

## 12. WEBHOOK SYSTEM

**File:** `sync_system/webhook_handler.py`

### 12.1 WEBHOOK ENDPOINTS

**Server:**
- Port: `WEBHOOK_PORT` (default 8080)
- Host: `WEBHOOK_HOST` (default 127.0.0.1)

**Security:**
- HMAC-SHA256 signature verification
- Allowed IP whitelist (Google Cloud ranges)
- Rate limiting (configurable)
- Token-based authentication

### 12.2 SECURITY FEATURES

**IP Whitelist:**
- Google Cloud IP ranges (predefined)
- Custom allowed IPs from env var

**Rate Limiting:**
- `WEBHOOK_RATE_LIMIT_REQUESTS`: 30 per window
- `WEBHOOK_RATE_LIMIT_WINDOW`: 60 seconds
- Per-client tracking

**Signature Verification:**
```python
WEBHOOK_SECRET_KEY = os.getenv("WEBHOOK_SECRET_KEY")
# HMAC signature checked on each request
```

### 12.3 DATA SYNC CAPABILITIES

**Universal Sync Engine:**
- Syncs all supported tables
- Bidirectional: DB ↔ Google Sheets
- Change tracking
- Error reporting
- Batch processing

---

## 13. EXTERNAL INTEGRATIONS

### 13.1 GOOGLE SERVICES

**File:** `google_services.py`

**APIs Used:**
- Google Sheets API (read/write)
- Google Drive API (metadata)

**Credentials:**
```python
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets"
]
```

**Purpose:**
- Import/export data
- Broadcast recipient lists
- Legacy user migration
- Config management

### 13.2 BOOKSTACK INTEGRATION

**File:** `bookstack_integration.py`, `bookstack_client.py`

**Features:**
- Document storage & retrieval
- Template management
- PDF generation
- Multi-language support

**API Endpoints:**
```python
BOOKSTACK_URL = os.getenv("BOOKSTACK_URL", "https://jetup.info")
BOOKSTACK_TOKEN_ID = os.getenv("BOOKSTACK_TOKEN_ID")
BOOKSTACK_TOKEN_SECRET = os.getenv("BOOKSTACK_TOKEN_SECRET")
```

**Standard Documents:**
```python
PROJECT_DOCUMENTS = {
    "agreement": "option-alienation-agreement",
    "cert": "option-certificate",
    "whitepaper": "project-whitepaper",
    "roadmap": "project-roadmap",
    "team": "project-team",
    "faq": "project-faq"
}
```

### 13.3 BLOCKCHAIN VERIFICATION

**Chains Supported:**
- Ethereum (Etherscan API)
- Binance Smart Chain (Etherscan API V2)
- Tron (TRON API)

**APIs:**
```python
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY")
TRON_API_KEY = os.getenv("TRON_API_KEY")
```

---

## 14. NOTIFICATION SYSTEM

### 14.1 NOTIFICATION TYPES

**Notification Categories:**
- `bonus` - Bonus received
- `payment` - Payment status
- `purchase` - Purchase confirmation
- `transfer` - Transfer completion
- `system` - System notifications

**Importance Levels:**
- `normal` - Standard notifications
- `high` - Important events
- `urgent` - Critical alerts

### 14.2 DELIVERY MECHANISMS

1. **Telegram:**
   - Direct message to user
   - Inline buttons for actions
   - HTML formatting
   - Optional silent mode
   - Auto-delete support

2. **Email:**
   - Template-based HTML emails
   - Fallback to text
   - Multiple providers (SMTP/Mailgun)
   - Secure domain handling

3. **Database:**
   - Persistent record
   - Delivery tracking
   - Retry capability
   - Status tracking

### 14.3 NOTIFICATION WORKFLOW

```
Trigger Event
   ↓
Create Notification Record (pending)
   ↓
Queue to NotificationProcessor
   ↓
Attempt Delivery (Telegram + Email)
   ↓
Update Status (sent/failed/retry)
   ↓
Retry Loop (exponential backoff)
   ↓
Final Status or Expiration
```

---

## 15. UNIQUE FEATURES

### 15.1 PORTFOLIO STRATEGY SYSTEM

**Strategies:**
```python
STRATEGY_COEFFICIENTS = {
    "manual": 1.0,      # No multiplication
    "safe": 4.50,       # Conservative - 4.5x value
    "aggressive": 11.00,# Medium risk - 11x value
    "risky": 25.00      # High risk - 25x value
}
```

**Usage:**
- User selects strategy
- Portfolio value calculated based on strategy multiplier
- Affects displayed portfolio value to user
- Stored in user.settings JSON

### 15.2 MARKETING MATERIALS SYSTEM

**Features:**
- Referral link generation
- Unique code per user
- Marketing info display
- Social links integration

**Social Links:**
```python
SOCIAL_LINKS = {
    'telegram_link': '...',
    'twitter_link': '...',
    'instagram_link': '...',
    'linkedin_link': '...',
    'facebook_link': '...'
}
```

### 15.3 CHANNEL SUBSCRIPTION REQUIREMENT

**Configuration:**
```python
REQUIRED_CHANNELS = [
    {"chat_id": "@jetnews_en", "title": "JETUP News English", ...},
    {"chat_id": "@jetnews_ru", "title": "JETUP News Русский", ...},
    {"chat_id": "@jetnews_de", "title": "JETUP News Deutsch", ...},
    {"chat_id": "@jetnews_in", "title": "JETUP News Indonesia", ...}
]
```

**Implementation:**
- Check on login/welcome screen
- Language-specific channels
- User must subscribe before access

### 15.4 MULTI-LANGUAGE SUPPORT

**Supported Languages:**
- English (en)
- Russian (ru)
- German (de)
- Indonesian (in)

**Implementation:**
- User language stored in user.lang
- Template-based messages with lang parameter
- BookStack documents translated
- Project descriptions per language

### 15.5 TIME MACHINE SYSTEM

**File:** `mlm_system/utils/time_machine.py`

**Purpose:**
- Handle month transitions
- Mock time for testing
- Track current month
- Consistent datetime across system

### 15.6 MONTHLY RESET MECHANISM

**Fields Reset Monthly:**
- `mlmVolumes.monthlyPV` → 0
- `isActive` → recalculated based on new PV
- Monthly stats recorded in separate table

**Reset Trigger:**
- Calendar month boundary
- Run by background service
- Rank recalculation

### 15.7 PDF CERTIFICATE GENERATION

**File:** `pdfconverter.py`

**Features:**
- Investment certificate PDF
- Project information inclusion
- User details embedding
- Download via Telegram

---

## CRITICAL DATA FLOWS

### Purchase → Commission Calculation

```
Purchase created
  ↓
CommissionService.processPurchase()
  ├─ _calculateDifferentialCommissions()
  │  ├─ Walk upline chain
  │  └─ Calculate differential %
  ├─ _applyCompression()
  │  └─ Skip inactive users
  ├─ _applyPioneerBonus()
  │  └─ Add +4% for pioneers
  ├─ Process referral bonuses (legacy)
  └─ Save all bonuses
  ↓
Update user balances (passive)
  ↓
Create notifications
  ↓
Check rank qualifications
```

### Payment Confirmation → Balance Update

```
User provides TXID
  ↓
TxidValidator validates format
  ↓
verify_transaction() checks blockchain
  ├─ Etherscan/Tronscan API
  └─ Verify recipient & amount
  ↓
Admin approval (2-step)
  ↓
Payment status = 'confirmed'
  ↓
User.balanceActive += amount
  ↓
Create ActiveBalance record
  ↓
Create notification
```

### Transfer Execution

```
User initiates transfer
  ├─ Select source (active/passive)
  ├─ Select recipient
  └─ Enter amount
  ↓
TransferValidator validates
  ├─ Sufficient balance
  ├─ Positive amount
  └─ Valid recipient
  ↓
Calculate bonus if passive→other
  ├─ +2% transfer bonus
  └─ Apply to receiver
  ↓
Create Transfer record
  ↓
Update both user balances
  ↓
Create balance records (ActiveBalance/PassiveBalance)
  ↓
Create notifications
```

---

## CONFIGURATION & ENVIRONMENT

**Critical .env Variables:**

```
# Database
DATABASE_URL=sqlite:///path/to/talentir.db

# Telegram
TELEGRAM_API_TOKEN=<bot_token>
ADMINS=<comma_separated_admin_ids>

# Wallets
WALLET_TRC=<tron_wallet>
WALLET_ETH=<ethereum_wallet>

# Blockchain APIs
ETHERSCAN_API_KEY=<key>
BSCSCAN_API_KEY=<key>
TRON_API_KEY=<key>

# Google Services
GOOGLE_SHEET_ID=<sheet_id>
GOOGLE_CREDENTIALS_JSON=<path_or_json>

# Email
SMTP_HOST=mail.jetup.info
SMTP_PORT=587
SMTP_USER=noreply@jetup.info
SMTP_PASSWORD=<password>

MAILGUN_API_KEY=<key>
MAILGUN_DOMAIN=mg.jetup.info
MAILGUN_REGION=eu

# BookStack
BOOKSTACK_URL=https://jetup.info
BOOKSTACK_TOKEN_ID=<id>
BOOKSTACK_TOKEN_SECRET=<secret>

# Webhook
WEBHOOK_SECRET_KEY=<key>
WEBHOOK_PORT=8080
WEBHOOK_HOST=127.0.0.1
```

---

## IMPLEMENTATION STATISTICS

**Project Structure:**
- 58 Python modules
- 12 database models
- 5 MLM rank tiers
- 6-level referral bonus system
- 3 commission types (differential/pioneer/referral)
- 2 payment providers (SMTP/Mailgun)
- 6 supported cryptocurrencies
- 4 supported languages
- 12+ admin commands
- 3 CSV report types
- 2+ webhook endpoints

**Critical Features:**
- ✅ Advanced MLM with compression
- ✅ Multi-chain crypto verification
- ✅ Google Sheets sync/export
- ✅ Email + Telegram delivery
- ✅ Admin backup/restore
- ✅ Legacy user migration
- ✅ Dynamic template system
- ✅ Rate limiting & security
- ✅ Audit trail tracking
- ✅ Multi-language support
- ✅ Error recovery & retries
- ✅ Atomic transactions

---

## MIGRATION PRIORITIES FOR JETUP-2

### PHASE 1 (CRITICAL - Must have)
1. MLM Commission System (differential + compression)
2. Payment Processing (deposit/withdrawal)
3. Purchase Flow
4. User Balance Management
5. Database Models (all 12)
6. Admin Commands (import/restore/broadcast)

### PHASE 2 (HIGH - Should have)
1. Email/Telegram Notifications
2. Bonus Processor
3. Volume Tracking
4. Rank Qualification
5. CSV Reports
6. Legacy User Migration

### PHASE 3 (MEDIUM - Nice to have)
1. Broadcast System
2. Webhook Sync
3. BookStack Integration
4. Portfolio Strategies
5. Email Provider Selection
6. Advanced Analytics

### PHASE 4 (NICE - Future)
1. Monthly reset automation
2. Advanced reporting dashboard
3. Admin analytics
4. Performance optimization
5. Caching layer

---

**END OF AUDIT REPORT**

