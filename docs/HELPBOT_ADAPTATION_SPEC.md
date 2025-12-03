# ТЗ: Адаптация Helpbot для работы с Jetup-2

## 1. Обзор

**Текущее состояние:** Helpbot подключается к БД Talentir (SQLite) для чтения данных пользователей
**Целевое состояние:** Helpbot подключается к БД Jetup-2 (PostgreSQL)

### 1.1 Ключевые изменения

| Аспект | Talentir (было) | Jetup-2 (стало) |
|--------|-----------------|-----------------|
| СУБД | SQLite | PostgreSQL |
| Драйвер | sqlite3 / aiosqlite | psycopg2 / asyncpg |
| Типы данных | Float | DECIMAL |
| Структура User | Плоская (kyc, isFilled) | JSON-поля (personalData) |

---

## 2. Используемые таблицы и поля

Helpbot использует следующие таблицы из основного бота **только для чтения**:

### 2.1 Таблица `users`

| Поле в Helpbot | Тип (Talentir) | Тип (Jetup-2) | Изменения |
|----------------|----------------|---------------|-----------|
| userID | Integer | Integer | — |
| telegramID | Integer | BigInteger | — |
| upline | Integer | BigInteger | — |
| firstname | String | String | — |
| surname | String | String | — |
| email | String | String | — |
| phoneNumber | String | String | — |
| country | String | String | — |
| city | String | String | — |
| lang | String | String | — |
| status | String | String | — |
| lastActive | DateTime | DateTime | — |
| createdAt | DateTime | DateTime | — |
| balanceActive | Float | DECIMAL(12,2) | Тип изменён |
| balancePassive | Float | DECIMAL(12,2) | Тип изменён |
| **isFilled** | Boolean | — | **УДАЛЕНО** → personalData.dataFilled |
| **kyc** | Boolean | — | **УДАЛЕНО** → personalData.kyc.status |
| notes | Text | Text | — |
| settings | String | JSON | Тип изменён |

#### Вычисляемые свойства (hybrid_property):
- `full_name` — без изменений
- `total_balance` — без изменений
- `kyc_status` — **ТРЕБУЕТ ИЗМЕНЕНИЙ** (новая логика)
- `profile_completeness` — без изменений
- `days_since_registration` — без изменений
- `referral_count` — без изменений

### 2.2 Таблица `purchases`

| Поле | Тип (Talentir) | Тип (Jetup-2) | Изменения |
|------|----------------|---------------|-----------|
| purchaseID | Integer | Integer | — |
| userID | Integer | Integer | — |
| createdAt | DateTime | DateTime | — |
| projectID | Integer | Integer | — |
| projectName | String | String | — |
| optionID | Integer | Integer | — |
| packQty | Integer | Integer | — |
| packPrice | Float | DECIMAL(12,2) | Тип изменён |

### 2.3 Таблица `payments`

| Поле | Тип (Talentir) | Тип (Jetup-2) | Изменения |
|------|----------------|---------------|-----------|
| paymentID | Integer | Integer | — |
| userID | Integer | Integer | — |
| createdAt | DateTime | DateTime | — |
| firstname | String | String | — |
| surname | String | String | — |
| direction | String | String | — |
| amount | Float | DECIMAL(12,2) | Тип изменён |
| method | String | String | — |
| fromWallet | String | String | — |
| toWallet | String | String | — |
| txid | String | String | — |
| sumCurrency | Float | DECIMAL(12,8) | Тип изменён |
| status | String | String | — |
| confirmedBy | String | String | — |
| confirmationTime | DateTime | DateTime | — |

### 2.4 Таблица `bonuses`

| Поле | Тип (Talentir) | Тип (Jetup-2) | Изменения |
|------|----------------|---------------|-----------|
| bonusID | Integer | Integer | — |
| userID | Integer | Integer | — |
| downlineID | Integer | Integer | — |
| purchaseID | Integer | Integer | — |
| createdAt | DateTime | DateTime | — |
| projectID | Integer | Integer | — |
| optionID | Integer | Integer | — |
| packQty | Integer | Integer | — |
| packPrice | Float | DECIMAL(12,2) | Тип изменён |
| uplineLevel | Integer | Integer | — |
| bonusRate | Float | Float | — |
| bonusAmount | Float | DECIMAL(12,2) | Тип изменён |
| status | String | String | — |
| notes | Text | Text | — |
| **commissionType** | — | String | **НОВОЕ ПОЛЕ** |
| **fromRank** | — | String | **НОВОЕ ПОЛЕ** |
| **sourceRank** | — | String | **НОВОЕ ПОЛЕ** |
| **compressionApplied** | — | Integer | **НОВОЕ ПОЛЕ** |

### 2.5 Таблицы `active_balances` / `passive_balances`

**КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ:** Имена таблиц изменились!

| Helpbot (Talentir) | Jetup-2 |
|--------------------|---------|
| `active_balance` | `active_balances` |
| `passive_balance` | `passive_balances` |

| Поле | Тип (Talentir) | Тип (Jetup-2) | Изменения |
|------|----------------|---------------|-----------|
| paymentID | Integer | Integer | — |
| userID | Integer | Integer | — |
| createdAt | DateTime | DateTime | — |
| firstname | String | String | — |
| surname | String | String | — |
| amount | Float | DECIMAL(12,2) | Тип изменён |
| status | String | String | — |
| reason | String | String | — |
| link | String | String | — |
| notes | Text | String | Тип изменён |

### 2.6 Таблица `transfers`

**КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ:** Опечатка в имени поля исправлена!

| Поле (Helpbot/Talentir) | Поле (Jetup-2) | Изменения |
|-------------------------|----------------|-----------|
| transferID | transferID | — |
| senderUserID | senderUserID | — |
| **recieverUserID** | **receiverUserID** | **ИСПРАВЛЕНА ОПЕЧАТКА** |
| senderFirstname | senderFirstname | — |
| senderSurname | senderSurname | — |
| receiverFirstname | receiverFirstname | — |
| receiverSurname | receiverSurname | — |
| fromBalance | fromBalance | — |
| toBalance | toBalance | — |
| amount | amount | DECIMAL(12,2) |
| status | status | — |
| notes | notes | — |
| createdAt | createdAt | — |

---

## 3. Необходимые изменения

### 3.1 Файл `config.py`

#### Изменения:
1. Переименовать переменную окружения:
   - `MAINBOT_DATABASE_URL` → поддержка PostgreSQL connection string

```python
# Было (SQLite):
MAINBOT_DATABASE_URL = "sqlite:///path/to/talentir.db"

# Стало (PostgreSQL):
MAINBOT_DATABASE_URL = "postgresql://user:pass@host:5432/jetup2"
```

---

### 3.2 Файл `core/db.py`

#### Изменения:

1. **Убрать SQLite-специфичные настройки:**

```python
# УДАЛИТЬ:
if 'sqlite' in url:
    connect_args = {"check_same_thread": False}
```

2. **Добавить PostgreSQL pool settings:**

```python
# ДОБАВИТЬ для PostgreSQL:
engine = create_engine(
    url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Проверка живости соединения
    pool_recycle=3600    # Переподключение каждый час
)
```

3. **Обновить imports:**

```python
# Добавить:
# pip install psycopg2-binary
# или для async: pip install asyncpg
```

---

### 3.3 Файл `models/mainbot/base.py`

Без изменений — `MainbotBase = declarative_base()` работает для любой СУБД.

---

### 3.4 Файл `models/mainbot/user.py`

#### Изменения:

1. **Изменить типы данных:**

```python
# Было:
balanceActive = Column(Float, default=0.00)
balancePassive = Column(Float, default=0.00)

# Стало:
from sqlalchemy import DECIMAL
balanceActive = Column(DECIMAL(12, 2), default=0.00)
balancePassive = Column(DECIMAL(12, 2), default=0.00)
```

2. **Добавить JSON поле и изменить hybrid_property для KYC:**

```python
# Было:
isFilled = Column(Boolean, default=False)
kyc = Column(Boolean, default=False)

# Стало:
from sqlalchemy import JSON

personalData = Column(JSON, nullable=True)
# Убрать: isFilled, kyc как отдельные колонки

# Изменить hybrid_property:
@hybrid_property
def kyc_status(self):
    """Returns KYC status from personalData JSON"""
    if self.personalData:
        kyc_data = self.personalData.get('kyc', {})
        if isinstance(kyc_data, dict):
            status = kyc_data.get('status', 'not_started')
            return "✅ Verified" if status == 'verified' else "❌ Not verified"
        # Обратная совместимость со старым форматом
        return "✅ Verified" if kyc_data else "❌ Not verified"
    return "❌ Not verified"

@hybrid_property
def is_profile_filled(self):
    """Check if profile data is filled"""
    if self.personalData:
        return self.personalData.get('dataFilled', False)
    return False

# Для обратной совместимости добавить property:
@property
def isFilled(self):
    return self.is_profile_filled

@property
def kyc(self):
    if self.personalData:
        kyc_data = self.personalData.get('kyc', {})
        if isinstance(kyc_data, dict):
            return kyc_data.get('status') == 'verified'
    return False
```

3. **Обновить profile_completeness:**

```python
@hybrid_property
def profile_completeness(self):
    """Calculate profile completion percentage"""
    fields = ['firstname', 'surname', 'email', 'phoneNumber',
              'country', 'city', 'address', 'birthday', 'passport']
    filled = sum(1 for f in fields if getattr(self, f, None))
    return int((filled / len(fields)) * 100)
```

---

### 3.5 Файл `models/mainbot/balance.py`

#### Изменения:

1. **Изменить имена таблиц:**

```python
# Было:
class ActiveBalance(MainbotBase):
    __tablename__ = 'active_balance'

class PassiveBalance(MainbotBase):
    __tablename__ = 'passive_balance'

# Стало:
class ActiveBalance(MainbotBase):
    __tablename__ = 'active_balances'  # Множественное число!

class PassiveBalance(MainbotBase):
    __tablename__ = 'passive_balances'  # Множественное число!
```

2. **Изменить типы данных:**

```python
# Было:
amount = Column(Float, nullable=False)

# Стало:
from sqlalchemy import DECIMAL
amount = Column(DECIMAL(12, 2), nullable=False)
```

---

### 3.6 Файл `models/mainbot/transfer.py`

#### Изменения:

1. **Исправить опечатку в имени поля:**

```python
# Было:
recieverUserID = Column(Integer, ForeignKey('users.userID'))

# Стало:
receiverUserID = Column(Integer, ForeignKey('users.userID'))
```

2. **Обновить relationship:**

```python
# Было:
receiver = relationship('User', foreign_keys=[recieverUserID], ...)

# Стало:
receiver = relationship('User', foreign_keys=[receiverUserID], ...)
```

3. **Обновить computed properties:**

```python
# Везде заменить recieverUserID на receiverUserID
```

---

### 3.7 Файл `models/mainbot/purchase.py`

#### Изменения:

```python
# Было:
packPrice = Column(Float, nullable=False)

# Стало:
from sqlalchemy import DECIMAL
packPrice = Column(DECIMAL(12, 2), nullable=False)
```

---

### 3.8 Файл `models/mainbot/payment.py`

#### Изменения:

```python
# Было:
amount = Column(Float, nullable=False)
sumCurrency = Column(Float, nullable=False)

# Стало:
from sqlalchemy import DECIMAL
amount = Column(DECIMAL(12, 2), nullable=False)
sumCurrency = Column(DECIMAL(12, 8), nullable=True)  # Nullable в Jetup-2!
```

---

### 3.9 Файл `models/mainbot/bonus.py`

#### Изменения:

1. **Типы данных:**

```python
# Было:
packPrice = Column(Float, nullable=True)
bonusAmount = Column(Float, nullable=False)

# Стало:
from sqlalchemy import DECIMAL
packPrice = Column(DECIMAL(12, 2), nullable=True)
bonusAmount = Column(DECIMAL(12, 2), nullable=False)
```

2. **Новые поля (опционально, для полноты):**

```python
# Добавить новые поля Jetup-2:
commissionType = Column(String, nullable=True)  # differential/referral/pioneer/global_pool
fromRank = Column(String, nullable=True)
sourceRank = Column(String, nullable=True)
compressionApplied = Column(Integer, nullable=True)
```

3. **Обновить bonus_type property:**

```python
@hybrid_property
def bonus_type(self):
    """Returns human-readable bonus type"""
    # Сначала проверяем новое поле commissionType
    if self.commissionType:
        type_map = {
            'differential': 'Differential Bonus',
            'referral': f'Referral Level {self.uplineLevel}',
            'pioneer': 'Pioneer Bonus',
            'global_pool': 'Global Pool'
        }
        return type_map.get(self.commissionType, self.commissionType)

    # Fallback на старую логику
    if self.downlineID:
        return f"Referral Level {self.uplineLevel}" if self.uplineLevel else "Referral"
    return "System Bonus"
```

---

### 3.10 Файл `services/mainbot_service.py`

#### Изменения:

1. **Обновить импорты моделей:**

```python
# Убедиться что импортируются обновленные модели
from models.mainbot.user import User as MainbotUser
from models.mainbot.balance import ActiveBalance, PassiveBalance
from models.mainbot.transfer import Transfer
# ... остальные
```

2. **Обновить методы работы с KYC:**

```python
# В методе get_user_summary():
def get_user_summary(self, telegram_id: int) -> Optional[dict]:
    # ...
    return {
        # ...
        'kyc_status': user.kyc_status,  # Уже использует обновленный property
        'profile_filled': user.isFilled,  # Property для обратной совместимости
        # ...
    }
```

3. **Проверить все места использования recieverUserID:**

```python
# Поиск и замена во всех запросах:
# recieverUserID → receiverUserID
```

---

### 3.11 Файл `requirements.txt`

#### Добавить:

```
psycopg2-binary>=2.9.0
# или для async:
asyncpg>=0.27.0
```

---

## 4. Сводка изменений по файлам

| Файл | Тип изменений | Приоритет |
|------|---------------|-----------|
| `config.py` | Конфигурация PostgreSQL | Высокий |
| `core/db.py` | Подключение к PostgreSQL | Высокий |
| `models/mainbot/user.py` | JSON поля, типы данных | Высокий |
| `models/mainbot/balance.py` | Имена таблиц, типы | Критический |
| `models/mainbot/transfer.py` | Исправление опечатки | Критический |
| `models/mainbot/purchase.py` | Типы данных | Средний |
| `models/mainbot/payment.py` | Типы данных | Средний |
| `models/mainbot/bonus.py` | Типы данных, новые поля | Средний |
| `services/mainbot_service.py` | Адаптация запросов | Средний |
| `requirements.txt` | Зависимости | Высокий |

---

## 5. Порядок внесения изменений

```
1. requirements.txt        # Добавить psycopg2-binary
2. config.py               # Обновить конфигурацию
3. core/db.py              # Подключение к PostgreSQL
4. models/mainbot/base.py  # Проверить (без изменений)
5. models/mainbot/balance.py  # КРИТИЧНО: имена таблиц
6. models/mainbot/transfer.py # КРИТИЧНО: receiverUserID
7. models/mainbot/user.py     # JSON поля
8. models/mainbot/*.py        # Остальные модели - типы данных
9. services/mainbot_service.py # Адаптация логики
10. Тестирование
```

---

## 6. Тестирование

### 6.1 Unit-тесты

- [ ] Проверить подключение к PostgreSQL
- [ ] Проверить чтение User с personalData JSON
- [ ] Проверить hybrid_properties (kyc_status, isFilled)
- [ ] Проверить чтение из active_balances/passive_balances
- [ ] Проверить Transfer с receiverUserID

### 6.2 Integration-тесты

- [ ] `MainbotService.get_user_by_telegram_id()`
- [ ] `MainbotService.get_user_summary()`
- [ ] `MainbotService.get_user_purchases()`
- [ ] `MainbotService.get_user_payments()`
- [ ] `MainbotService.get_user_bonuses()`
- [ ] `MainbotService.get_user_balance_history()`
- [ ] `MainbotService.get_user_transfers()`
- [ ] `MainbotService.search_payment_by_txid()`

### 6.3 Checklist

- [ ] Helpbot запускается без ошибок
- [ ] Поиск пользователя по telegram_id работает
- [ ] Отображается правильный KYC статус
- [ ] История балансов загружается
- [ ] Трансферы отображаются корректно
- [ ] Нет ошибок типов данных (Float vs Decimal)

---

## 7. Риски и митигация

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Ошибки подключения к PostgreSQL | Средняя | Высокое | Тестирование на staging |
| Несовместимость типов Decimal | Средняя | Среднее | Явное приведение типов |
| Ошибки из-за переименования таблиц | Высокая | Критическое | Тщательная проверка имён |
| Ошибки из-за receiverUserID | Высокая | Критическое | Grep по всему коду |
| JSON parsing errors | Низкая | Среднее | Fallback значения |

---

## 8. Обратная совместимость

Для минимизации изменений в бизнес-логике добавлены:

1. **Property-алиасы в User модели:**
   - `user.isFilled` → читает из `personalData.dataFilled`
   - `user.kyc` → читает из `personalData.kyc.status`

2. **Гибридные свойства:**
   - `user.kyc_status` — возвращает строку с emoji
   - `user.is_profile_filled` — булево значение

Это позволяет существующему коду работать без изменений.

---

## 9. Переменные окружения

### Новые/изменённые:

```bash
# PostgreSQL connection string
MAINBOT_DATABASE_URL=postgresql://user:password@host:5432/jetup2

# Опционально: отдельные параметры
MAINBOT_DB_HOST=localhost
MAINBOT_DB_PORT=5432
MAINBOT_DB_NAME=jetup2
MAINBOT_DB_USER=helpbot_reader
MAINBOT_DB_PASSWORD=secure_password
```

### Рекомендация по безопасности:

Создать read-only пользователя PostgreSQL для helpbot:

```sql
CREATE USER helpbot_reader WITH PASSWORD 'secure_password';
GRANT CONNECT ON DATABASE jetup2 TO helpbot_reader;
GRANT USAGE ON SCHEMA public TO helpbot_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO helpbot_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO helpbot_reader;
```

---

## 10. Оценка трудозатрат

| Задача | Оценка |
|--------|--------|
| Изменения в моделях | 2-3 часа |
| Изменения в db.py и config.py | 1 час |
| Изменения в mainbot_service.py | 1-2 часа |
| Unit-тесты | 2-3 часа |
| Integration-тесты | 2-3 часа |
| Тестирование на staging | 2-3 часа |
| **Итого** | **10-15 часов** |

---

*Документ создан: 2025-12-03*
*Версия: 1.0*
*Связанный документ: MIGRATION_SPEC.md*
