# TALENTIR FEATURE MIGRATION CHECKLIST

## Critical Features (MUST MIGRATE)

### MLM Commission System
- [x] 5-Tier Rank System (START/BUILDER/GROWTH/LEADERSHIP/DIRECTOR)
  - Commission percentages: 4%/8%/12%/15%/18%
  - Requirements: team volume + active partners count
- [x] Differential Commission Calculation
  - Walk upline chain
  - Calculate percentage differences
  - Apply compression for inactive users
- [x] Pioneer Bonus (+4% for first 50 purchases)
- [x] Referral Bonus System (6-level: 10%/4%/2%/1%/1%/1%)
- [x] Volume Tracking (Personal + Team)
  - Monthly PV reset
  - Activation threshold: $200/month
- [x] Rank Qualification & Promotion
- [x] Monthly Stats & Reset

### Payment System
- [x] Deposit Flow (Crypto)
  - 6 supported cryptocurrencies
  - 2 blockchain networks (EVM + TRON)
  - 2-step admin approval
- [x] Withdrawal Flow
  - Balance deduction
  - Payout processing
- [x] Transaction Verification
  - TXID format validation
  - Blockchain API verification (Etherscan/TRON)
  - Wallet address validation
- [x] Payment Notifications
  - Admin notifications
  - User confirmations

### Purchase Flow
- [x] Project Selection (Carousel)
- [x] Investment Options
- [x] Payment Method Selection
- [x] Crypto Transaction Handling
- [x] Admin Approval (2-step)
- [x] Bonus Calculation & Distribution
- [x] Certificate Generation

### User Management
- [x] User Model with JSON fields
  - Personal data (KYC)
  - MLM status & volumes
  - Email verification
  - Settings & preferences
- [x] Profile Completion Flow
  - 9 data fields required
  - Email verification
  - Email + Passport + Personal ID

### Balance Management
- [x] Dual Balance System (Active/Passive)
- [x] Balance Transaction History
- [x] Balance Transfer System
  - Active→Active (no bonus)
  - Passive→Own/Other (with +2% bonus)

### Admin Commands
- [x] &import - Google Sheets sync (dry/safe/force modes)
- [x] &restore - Backup restoration
- [x] &upconfig - Config update from Google Sheets
- [x] &upro - Projects & options update
- [x] &ut - Template update
- [x] &delpurchase - Purchase deletion with rollback
- [x] &testmail - Email provider testing
- [x] &broadcast - Mass messaging (Telegram + Email)
- [x] &check - Payment verification
- [x] &legacy - Legacy user migration
- [x] &object - Media delivery by file_id

### Database Models (12 total)
- [x] User
- [x] Purchase
- [x] Bonus
- [x] Payment
- [x] Transfer
- [x] ActiveBalance
- [x] PassiveBalance
- [x] Notification
- [x] NotificationDelivery
- [x] Project
- [x] Option
- [x] RankHistory
- [x] MonthlyStats (implied)

## High-Priority Features (SHOULD MIGRATE)

### Email & Notifications
- [x] Notification Processor
  - Database persistence
  - Retry logic
  - Status tracking
- [x] Email Providers
  - SMTP integration
  - Mailgun integration
  - Provider selection logic
  - Secure domain handling
- [x] Message Templates
  - Multi-language support (4 languages: en/ru/de/in)
  - Variable substitution
  - Inline keyboards
- [x] Message Manager
  - Template-based sending
  - Error handling

### Reporting & Analytics
- [x] CSV Report Generation
  - Team full report
  - Active balance history
  - Passive balance history
- [x] Report Filters & Customization
- [x] PDF Certificate Generation

### Background Services
- [x] Legacy User Processor
  - Automatic (every 10 minutes)
  - Email matching (case-insensitive, Gmail dots)
  - Batch processing (50 records)
- [x] Invoice Cleaner

### Broadcast System
- [x] BroadcastManager
  - Google Sheets source
  - Async processing
  - Progress tracking
  - Batch email sending
  - Test mode

### Webhook System
- [x] Webhook Handler
  - IP whitelist (Google Cloud)
  - Rate limiting
  - HMAC signature verification
  - Data sync capability

### External Integrations
- [x] Google Sheets API (import/export)
- [x] Google Drive API
- [x] BookStack Integration
  - Document retrieval
  - PDF generation
  - Multi-language support
- [x] Blockchain APIs
  - Etherscan (ETH/BSC)
  - TRON API
  - Transaction verification

## Medium-Priority Features (NICE TO HAVE)

### Advanced Features
- [x] Portfolio Strategy System (4 strategies)
  - manual (1.0x)
  - safe (4.5x)
  - aggressive (11.0x)
  - risky (25.0x)
- [x] Transfer Bonus System (2% on passive transfers)
- [x] FSM State Management
  - UserDataDialog
  - ProjectCarouselState
  - PurchaseFlow
  - TxidInputState
  - TransferDialog

### UI/UX Features
- [x] Multi-language Support (en/ru/de/in)
- [x] Channel Subscription Enforcement
- [x] EULA Management
- [x] Referral Link Generation
- [x] Marketing Materials
- [x] Dashboard Templates

## Supported Cryptocurrencies

- [x] USDT (Tron: USDT-TRC20)
- [x] TRX (Tron)
- [x] ETH (Ethereum)
- [x] BNB (Binance Smart Chain)
- [x] USDT (Ethereum: USDT-ERC20)
- [x] USDT (BSC: USDT-BSC20)

## Database Fields & Relationships

### User Fields (Key JSON)
- mlmStatus: rankQualifiedAt, assignedRank, isFounder, lastActiveMonth, pioneerPurchasesCount, hasPioneerBonus
- mlmVolumes: personalTotal, monthlyPV, autoship
- personalData: eulaAccepted, eulaVersion, dataFilled, kyc
- emailVerification: confirmed, token, sentAt, confirmedAt, attempts
- settings: strategy, notifications, display

### Payment Fields
- direction: 'in'|'out'
- method: USDT-TRC20|ETH|BNB|USDT-BSC20|USDT-ERC20|TRX
- status: pending|check|confirmed|rejected|cancelled

### Bonus Fields
- commissionType: differential|referral|pioneer|global_pool
- uplineLevel: 1-N
- compressionApplied: 0|1
- status: pending|processing|paid|cancelled|error

### Transfer Fields
- fromBalance: active|passive
- toBalance: active|passive
- status: pending|completed|cancelled|error

## Configuration Parameters

### Commission & Bonuses
- PURCHASE_BONUSES: level_1-6 (10%/4%/2%/1%/1%/1%)
- PIONEER_BONUS_PERCENTAGE: 4%
- GLOBAL_POOL_PERCENTAGE: 2%
- TRANSFER_BONUS: 2%
- REFERRAL_BONUS_MIN_AMOUNT: $5,000

### Rank Requirements
- BUILDER: $50K TV, 2 active partners
- GROWTH: $250K TV, 5 active partners
- LEADERSHIP: $1M TV, 10 active partners
- DIRECTOR: $5M TV, 15 active partners

### Activation
- MINIMUM_PV: $200/month

### Portfolio Strategies
- manual: 1.0x
- safe: 4.5x
- aggressive: 11.0x
- risky: 25.0x

### Required Channels
- @jetnews_en (English)
- @jetnews_ru (Russian)
- @jetnews_de (German)
- @jetnews_in (Indonesian)

## Integration Points

### Google Services
- Project & Option data import
- User & Payment data sync
- Broadcast recipient lists
- Legacy user migration
- Config management

### Email Providers
- SMTP (mail.jetup.info)
- Mailgun (mg.jetup.info)
- Fallback logic
- Secure domains: @t-online.de, @gmx.de, @web.de

### Blockchain APIs
- Etherscan API V2 (ETH/BSC)
- TRON API
- Transaction hash validation
- Address verification

### BookStack
- Document management
- Multi-language support
- PDF generation
- FAQ & resources

## Admin Operations

### Data Management
- Import from Google Sheets (dry/safe/force modes)
- Restore from database backup
- Update configuration
- Update templates
- Update projects & options

### Monitoring
- Check pending payments
- Monitor notifications
- View payment status

### User Management
- Delete purchases (with rollback)
- Trigger legacy migration
- Send test emails
- Execute broadcasts

## Error Handling & Recovery

### Transaction Safety
- Atomic transactions
- Rollback on error
- Audit trail (createdAt/updatedAt/owner fields)

### Payment Verification
- TXID deduplication
- Format validation
- Blockchain confirmation
- Admin 2-step approval

### Bonus Processing
- Error tracking
- Notification failures with retry
- Compression logic for inactive users

### Email Delivery
- Multiple provider fallback
- Retry logic
- Provider health checking
- Domain-based routing

### Broadcast Processing
- Batch processing with delays
- Progress tracking
- Cancellation support
- Error logging

## Statistics & Summary

- **Total Database Models:** 12
- **Admin Commands:** 12+
- **Commission Types:** 3 (differential + pioneer + referral)
- **Rank Tiers:** 5
- **Crypto Methods:** 6
- **Report Types:** 3
- **Languages Supported:** 4
- **Email Providers:** 2
- **Blockchain Networks:** 2
- **FSM State Groups:** 5
- **User JSON Fields:** 5

## Timeline Estimate

| Phase | Duration | Complexity |
|-------|----------|-----------|
| Phase 1 (Critical) | 4-6 weeks | HIGH |
| Phase 2 (High) | 3-4 weeks | HIGH |
| Phase 3 (Medium) | 2-3 weeks | MEDIUM |
| Phase 4 (Nice) | 1-2 weeks | LOW |

**Total Estimated:** 10-15 weeks for full feature parity

