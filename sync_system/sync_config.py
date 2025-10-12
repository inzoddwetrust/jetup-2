"""
Конфигурация системы синхронизации БД <-> Google Sheets
Обновлено для новой структуры с JSON полями и MLM
"""

from models import User, Payment, Purchase, Bonus, Transfer, ActiveBalance, PassiveBalance
import config

SYNC_CONFIG = {
    'Users': {
        'sheet_name': 'Users',
        'model': User,
        'primary_key': 'userID',

        'readonly_fields': [
            'userID', 'telegramID', 'createdAt',
            'balanceActive', 'balancePassive',
            # MLM поля только для чтения
            'rank', 'isActive', 'teamVolumeTotal'
        ],

        'editable_fields': [
            'email', 'firstname', 'surname', 'birthday', 'address',
            'phoneNumber', 'city', 'country', 'passport',
            'lang', 'status', 'upline', 'lastActive',
            # JSON поля как строки
            'personalData', 'emailVerification', 'settings',
            'mlmStatus', 'mlmVolumes'
        ],

        'export_updates': [
            'email', 'firstname', 'surname', 'phoneNumber',
            'lastActive', 'status', 'upline',
            'balanceActive', 'balancePassive',
            # MLM поля
            'rank', 'isActive', 'teamVolumeTotal',
            # JSON поля
            'personalData', 'emailVerification', 'settings',
            'mlmStatus', 'mlmVolumes'
        ],

        'required_fields': ['userID', 'telegramID'],

        'foreign_keys': {
            'upline': ('Users', 'telegramID')  # Ссылается на telegramID
        },

        'field_validators': {
            'email': 'email',
            'phoneNumber': 'phone',
            'birthday': 'date',
            'upline': 'special_upliner',
            # JSON поля
            'personalData': 'json_string',
            'emailVerification': 'json_string',
            'settings': 'json_string',
            'mlmStatus': 'json_string',
            'mlmVolumes': 'json_string',
            # MLM поля
            'rank': ['start', 'builder', 'growth', 'leadership', 'director'],
            'isActive': 'boolean',
            'teamVolumeTotal': 'decimal',
            'balanceActive': 'decimal',
            'balancePassive': 'decimal'
        },

        'special_rules': {
            'upline': {
                'never_empty': True,
                'default_value': config.DEFAULT_REFERRER_ID,
                'no_self_reference': True,
                'check_exists': True,
                'stop_recursion_at': config.DEFAULT_REFERRER_ID
            }
        }
    },

    'Payments': {
        'sheet_name': 'Payments',
        'model': Payment,
        'primary_key': 'paymentID',

        'readonly_fields': [
            'paymentID', 'userID', 'createdAt', 'updatedAt',
            'firstname', 'surname',
            # AuditMixin поля
            'ownerTelegramID', 'ownerEmail'
        ],

        'editable_fields': [
            'direction', 'amount', 'method', 'fromWallet', 'toWallet',
            'txid', 'sumCurrency', 'status', 'confirmedBy',
            'confirmationTime', 'notes'
        ],

        'export_updates': [
            'status',
            'confirmedBy',
            'confirmationTime',
            'txid',
            'fromWallet'
        ],

        'required_fields': [
            'paymentID', 'userID', 'firstname', 'amount',
            'method', 'sumCurrency', 'status', 'direction'
        ],

        'foreign_keys': {
            'userID': ('Users', 'userID')
        },

        'field_validators': {
            'amount': 'decimal',
            'status': ['pending', 'check', 'confirmed', 'rejected', 'cancelled'],
            'direction': ['in', 'out'],  # Обновлено согласно модели
            'confirmationTime': 'datetime'
        }
    },

    'Purchases': {
        'sheet_name': 'Purchases',
        'model': Purchase,
        'primary_key': 'purchaseID',

        'readonly_fields': [
            'purchaseID', 'userID', 'projectID', 'optionID',
            'createdAt', 'updatedAt',
            # AuditMixin поля
            'ownerTelegramID', 'ownerEmail'
        ],

        'editable_fields': [
            'projectName',
            'packQty', 'packPrice'
        ],

        'export_updates': [],  # Покупки не обновляем при экспорте

        'required_fields': [
            'purchaseID', 'userID', 'projectID', 'projectName',
            'optionID', 'packQty', 'packPrice'
        ],

        'foreign_keys': {
            'userID': ('Users', 'userID')
        },

        'field_validators': {
            'packQty': 'int',
            'packPrice': 'decimal'
        }
    },

    'Bonuses': {
        'sheet_name': 'Bonuses',
        'model': Bonus,
        'primary_key': 'bonusID',

        'readonly_fields': [
            'bonusID', 'userID', 'downlineID', 'purchaseID',
            'projectID', 'optionID', 'createdAt', 'updatedAt',
            # AuditMixin поля
            'ownerTelegramID', 'ownerEmail',
            # MLM поля
            'commissionType', 'uplineLevel', 'fromRank', 'sourceRank',
            'packQty', 'packPrice'
        ],

        'editable_fields': [
            'bonusRate', 'bonusAmount', 'status', 'notes',
            'compressionApplied'
        ],

        'export_updates': ['status'],

        'required_fields': [
            'bonusID', 'userID', 'bonusRate', 'bonusAmount'
        ],

        'foreign_keys': {
            'userID': ('Users', 'userID'),
            'downlineID': ('Users', 'userID'),
            'purchaseID': ('Purchases', 'purchaseID')
        },

        'field_validators': {
            'bonusRate': 'float',
            'bonusAmount': 'decimal',
            'uplineLevel': 'int',
            'status': ['pending', 'processing', 'paid', 'cancelled', 'error'],
            'compressionApplied': 'boolean',
            'commissionType': ['differential', 'referral', 'pioneer', 'global_pool']
        }
    },

    'Transfers': {
        'sheet_name': 'Transfers',
        'model': Transfer,
        'primary_key': 'transferID',

        'readonly_fields': [
            'transferID', 'senderUserID', 'receiverUserID',
            'createdAt', 'updatedAt',
            'senderFirstname', 'receiverFirstname',
            # AuditMixin поля
            'ownerTelegramID', 'ownerEmail'
        ],

        'editable_fields': [
            'senderSurname', 'receiverSurname', 'fromBalance',
            'toBalance', 'amount', 'status', 'notes'
        ],

        'export_updates': ['status'],

        'required_fields': [
            'transferID', 'senderUserID', 'senderFirstname',
            'fromBalance', 'amount', 'receiverUserID',
            'receiverFirstname', 'toBalance', 'status'
        ],

        'foreign_keys': {
            'senderUserID': ('Users', 'userID'),
            'receiverUserID': ('Users', 'userID')
        },

        'field_validators': {
            'amount': 'decimal',
            'fromBalance': ['active', 'passive'],
            'toBalance': ['active', 'passive'],
            'status': ['pending', 'done', 'cancelled', 'error']
        }
    },

    'ActiveBalance': {
        'sheet_name': 'ActiveBalance',
        'model': ActiveBalance,
        'primary_key': 'activeBalanceID',  # Исправлено с paymentID

        'readonly_fields': [
            'activeBalanceID', 'userID', 'createdAt', 'updatedAt',
            'firstname',
            # AuditMixin поля
            'ownerTelegramID', 'ownerEmail'
        ],

        'editable_fields': [
            'surname', 'amount', 'status', 'reason', 'link', 'notes'
        ],

        'export_updates': ['status'],

        'required_fields': [
            'activeBalanceID', 'userID', 'firstname', 'status', 'reason'
        ],

        'foreign_keys': {
            'userID': ('Users', 'userID')
        },

        'field_validators': {
            'amount': 'decimal',
            'status': ['pending', 'done', 'cancelled', 'error']
        },

        'special_rules': {
            'manual_addition': {
                'allow_zero_amount': True
            }
        }
    },

    'PassiveBalance': {
        'sheet_name': 'PassiveBalance',
        'model': PassiveBalance,
        'primary_key': 'passiveBalanceID',  # Исправлено с paymentID

        'readonly_fields': [
            'passiveBalanceID', 'userID', 'createdAt', 'updatedAt',
            'firstname',
            # AuditMixin поля
            'ownerTelegramID', 'ownerEmail'
        ],

        'editable_fields': [
            'surname', 'amount', 'status', 'reason', 'link', 'notes'
        ],

        'export_updates': ['status'],

        'required_fields': [
            'passiveBalanceID', 'userID', 'firstname', 'status', 'reason'
        ],

        'foreign_keys': {
            'userID': ('Users', 'userID')
        },

        'field_validators': {
            'amount': 'decimal',
            'status': ['pending', 'done', 'cancelled', 'error']
        }
    }
}

# Вспомогательные функции
def validate_upliner(upline_value: int, user_telegram_id: int, session) -> int:
    """
    Валидация uplinerID с учетом бизнес-логики
    """
    # Пустой upline - ОШИБКА
    if not upline_value:
        raise ValueError(f"Empty upline for user {user_telegram_id}")

    # DEFAULT_REFERRER может ссылаться сам на себя - это ОК!
    if user_telegram_id == config.DEFAULT_REFERRER_ID and upline_value == config.DEFAULT_REFERRER_ID:
        return upline_value

    # Остальные не могут ссылаться на себя
    if upline_value == user_telegram_id:
        raise ValueError(f"User {user_telegram_id} has self-reference as upline")

    # Проверяем существование
    from models import User
    upliner = session.query(User).filter_by(telegramID=upline_value).first()
    if not upliner:
        raise ValueError(f"Invalid upline {upline_value}: does not exist")

    return upline_value

def get_editable_fields(table_name: str) -> list:
    """Получить список полей, которые можно редактировать"""
    return SYNC_CONFIG.get(table_name, {}).get('editable_fields', [])

def get_readonly_fields(table_name: str) -> list:
    """Получить список полей только для чтения"""
    return SYNC_CONFIG.get(table_name, {}).get('readonly_fields', [])

def is_field_editable(table_name: str, field_name: str) -> bool:
    """Проверить, можно ли редактировать поле"""
    return field_name in get_editable_fields(table_name)

def get_table_model(table_name: str):
    """Получить модель SQLAlchemy для таблицы"""
    return SYNC_CONFIG.get(table_name, {}).get('model')

def validate_foreign_key(table_name: str, field_name: str, value: any, session) -> bool:
    """Проверить существование foreign key"""
    fk_config = SYNC_CONFIG.get(table_name, {}).get('foreign_keys', {}).get(field_name)
    if not fk_config:
        return True

    ref_table, ref_field = fk_config
    ref_model = get_table_model(ref_table)
    if not ref_model:
        return False

    exists = session.query(ref_model).filter(
        getattr(ref_model, ref_field) == value
    ).first() is not None

    return exists

# Категории таблиц
SUPPORT_TABLES = ['Users', 'Payments', 'Purchases', 'Bonuses', 'Transfers', 'ActiveBalance', 'PassiveBalance']
ADMIN_ONLY_TABLES = ['Projects', 'Options']  # Только через &upro

# Режимы импорта
IMPORT_MODES = {
    'dry': {
        'description': 'Проверка без изменений',
        'commit': False
    },
    'safe': {
        'description': 'Импорт только безопасных полей',
        'commit': True,
        'skip_critical': True
    },
    'force': {
        'description': 'Полный импорт',
        'commit': True,
        'require_confirmation': True
    }
}