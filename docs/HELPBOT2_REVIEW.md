# Отчёт о проверке helpbot-2

**Репозиторий:** https://github.com/inzoddwetrust/helpbot-2
**Дата проверки:** 2025-12-04
**Базовый документ:** HELPBOT_ADAPTATION_SPEC.md

---

## 1. Выполнение ТЗ

### ✅ Выполнено корректно

| Требование | Статус | Комментарий |
|------------|--------|-------------|
| Таблица `active_balances` (мн.ч.) | ✅ | Исправлено с `active_balance` |
| Таблица `passive_balances` (мн.ч.) | ✅ | Исправлено с `passive_balance` |
| Поле `receiverUserID` | ✅ | Опечатка `recieverUserID` исправлена |
| `personalData` JSON в User | ✅ | Добавлено, kyc/isFilled перенесены |
| `kyc_status` hybrid_property | ✅ | Читает из personalData.kyc |
| `isFilled` property (совместимость) | ✅ | Делегирует в is_profile_filled |
| DECIMAL вместо Float | ✅ | Все денежные поля: DECIMAL(12,2) |
| PostgreSQL pool settings | ✅ | pool_size=5, pool_pre_ping=True |
| psycopg2-binary в requirements | ✅ | Версия 2.9.10 |
| Новые поля Bonus | ✅ | commissionType, fromRank, sourceRank, compressionApplied |

---

## 2. Найденные проблемы

### 🔴 Критические

#### 2.1 Несоответствие типа `telegramID`

**Файл:** `models/mainbot/user.py`

```python
# В helpbot-2:
telegramID = Column(Integer, unique=True, nullable=False)
upline = Column(Integer, ForeignKey('users.telegramID'), nullable=True)

# В Jetup-2:
telegramID = Column(BigInteger, unique=True, nullable=False)
upline = Column(BigInteger, nullable=True)
```

**Проблема:** Telegram ID может превышать 2^31-1 (максимум для Integer). PostgreSQL вернёт ошибку при чтении больших ID.

**Исправление:**
```python
from sqlalchemy import BigInteger

telegramID = Column(BigInteger, unique=True, nullable=False)
upline = Column(BigInteger, ForeignKey('users.telegramID'), nullable=True)
```

---

### 🟡 Средние

#### 2.2 Смешение паттернов relationship

**Файл:** `models/mainbot/user.py`

```python
# Старый паттерн (backref):
referrals = relationship('User', backref=backref('referrer', remote_side=[telegramID]))

# Новый паттерн (back_populates):
purchases = relationship('Purchase', back_populates='user')
```

**Проблема:** Смешение `backref` и `back_populates` в одной модели может вызвать путаницу и потенциальные проблемы с lazy loading.

**Рекомендация:** Унифицировать на `back_populates` везде.

---

#### 2.3 Отсутствие thread safety в db.py

**Файл:** `core/db.py`

```python
_ENGINES = {}
_SESSION_FACTORIES = {}

def get_db_session(db_type: DatabaseType = DatabaseType.HELPBOT):
    global _ENGINES, _SESSION_FACTORIES
    if db_type not in _ENGINES:
        # ... создание engine
```

**Проблема:** Глобальные словари модифицируются без блокировки. При конкурентном доступе возможны race conditions.

**Исправление:**
```python
import threading

_lock = threading.Lock()
_ENGINES = {}
_SESSION_FACTORIES = {}

def get_db_session(db_type: DatabaseType = DatabaseType.HELPBOT):
    with _lock:
        if db_type not in _ENGINES:
            # ... создание engine
```

---

#### 2.4 Hardcoded pool settings

**Файл:** `core/db.py`

```python
_ENGINES[db_type] = create_engine(
    db_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600
)
```

**Проблема:** Параметры пула жёстко закодированы, нет возможности настройки через env.

**Рекомендация:** Вынести в Config:
```python
pool_size=Config.get('DB_POOL_SIZE', 5),
max_overflow=Config.get('DB_MAX_OVERFLOW', 10),
```

---

#### 2.5 Birthday как DateTime

**Файл:** `models/mainbot/user.py`

```python
birthday = Column(DateTime, nullable=True)
```

**В Jetup-2:**
```python
birthday = Column(String, nullable=True)
```

**Проблема:** Несоответствие типов. В Jetup-2 birthday хранится как String (формат даты), а в helpbot-2 ожидается DateTime.

**Исправление:**
```python
birthday = Column(String, nullable=True)  # Формат: "YYYY-MM-DD" или произвольный
```

---

### 🟢 Незначительные / Рекомендации

#### 2.6 Отсутствие SQL expression для hybrid_property

**Файл:** `models/mainbot/user.py`

```python
@hybrid_property
def kyc_status(self):
    if self.personalData:
        kyc_data = self.personalData.get('kyc', {})
        # ...
```

**Проблема:** Нет `@kyc_status.expression` — невозможно фильтровать на уровне БД.

**Рекомендация:** Для read-only модели это допустимо, но если потребуется фильтрация — добавить expression.

---

#### 2.7 Дублирование formatted_amount логики

Во всех моделях (Balance, Transfer, Payment, Bonus, Purchase) одинаковый код:

```python
@property
def formatted_amount(self):
    return f"${self.amount:,.2f}"
```

**Рекомендация:** Вынести в mixin или utility функцию:

```python
# utils/formatters.py
def format_currency(amount, currency='$'):
    return f"{currency}{amount:,.2f}"
```

---

#### 2.8 Нет типизации (type hints)

Файлы моделей не используют type hints для параметров методов.

**Рекомендация:**
```python
def get_user_by_telegram_id(self, telegram_id: int) -> Optional[dict]:
```

---

#### 2.9 settings как String вместо JSON

**Файл:** `models/mainbot/user.py`

```python
settings = Column(String, nullable=True)
```

**В Jetup-2:**
```python
settings = Column(JSON, nullable=True)
```

**Проблема:** Если settings в Jetup-2 хранится как JSON, а в helpbot-2 ожидается String — будет ошибка при чтении.

**Исправление:**
```python
settings = Column(JSON, nullable=True)
```

---

## 3. Сводка по файлам

| Файл | Статус | Критичные проблемы |
|------|--------|-------------------|
| `core/db.py` | ⚠️ | Thread safety |
| `config.py` | ✅ | — |
| `requirements.txt` | ✅ | — |
| `models/mainbot/user.py` | ⚠️ | telegramID Integer, birthday DateTime, settings String |
| `models/mainbot/balance.py` | ✅ | — |
| `models/mainbot/transfer.py` | ✅ | — |
| `models/mainbot/purchase.py` | ✅ | — |
| `models/mainbot/payment.py` | ✅ | — |
| `models/mainbot/bonus.py` | ✅ | — |
| `services/mainbot_service.py` | ✅ | — |

---

## 4. Приоритетный список исправлений

### Критические (блокеры):

1. **`telegramID`** — изменить `Integer` → `BigInteger` в user.py
2. **`birthday`** — изменить `DateTime` → `String` в user.py
3. **`settings`** — изменить `String` → `JSON` в user.py

### Рекомендуемые:

4. Добавить `threading.Lock()` в db.py
5. Унифицировать relationships на `back_populates`
6. Вынести pool settings в конфигурацию

### Опциональные:

7. Добавить type hints
8. Вынести format_currency в utility
9. Добавить SQL expressions для hybrid properties

---

## 5. Checklist для исправлений

- [ ] `models/mainbot/user.py`: telegramID → BigInteger
- [ ] `models/mainbot/user.py`: upline → BigInteger
- [ ] `models/mainbot/user.py`: birthday → String
- [ ] `models/mainbot/user.py`: settings → JSON
- [ ] `core/db.py`: добавить threading.Lock
- [ ] `models/mainbot/user.py`: унифицировать relationships

---

## 6. Вывод

**Общая оценка:** 85% выполнения ТЗ

Основные требования по адаптации к Jetup-2 выполнены:
- ✅ Имена таблиц исправлены
- ✅ Опечатка receiverUserID исправлена
- ✅ DECIMAL типы применены
- ✅ PostgreSQL подключение настроено
- ✅ personalData JSON реализован

**Критические недоработки:**
- ❌ telegramID остался Integer (должен быть BigInteger)
- ❌ birthday остался DateTime (должен быть String)
- ❌ settings остался String (должен быть JSON)

После исправления этих 3 проблем helpbot-2 будет полностью совместим с Jetup-2.

---

*Документ создан: 2025-12-04*
*Ревизия: 1.0*
