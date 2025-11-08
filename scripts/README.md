# MLM Testing Scripts

Набор скриптов для тестирования MLM системы вживую.

## 📋 Содержание

1. [Популяторы БД](#популяторы-бд)
2. [Тестовые скрипты](#тестовые-скрипты)
3. [Утилиты](#утилиты)
4. [Быстрый старт](#быстрый-старт)

---

## 🗄️ Популяторы БД

### `populate_commission_test.py`

Создает линейную цепочку для тестирования дифференциальных комиссий и компрессии.

**Структура:**
```
ROOT (director, 18%)
  → Inactive1 (❌ сжимается)
    → Builder1 (✅ 10%)
      → Inactive2 (❌ сжимается)
        → Start1 (✅ 7%)
          → Зодд (покупатель)
```

**Использование:**
```bash
python scripts/populate_commission_test.py
```

**Тестирует:**
- Дифференциальные комиссии
- Компрессию неактивных пользователей
- Передачу сжатых комиссий активным upline
- Остаток комиссий в ROOT

---

## 🧪 Тестовые скрипты

### `test_commission_flow.py`

Тестирует полный цикл обработки комиссий.

**Использование:**
```bash
# Сначала создайте тестовую БД
python scripts/populate_commission_test.py

# Затем запустите тест
python scripts/test_commission_flow.py
```

**Проверяет:**
- Создание покупки
- Расчет дифференциальных комиссий
- Компрессию неактивных
- Сумму комиссий (должна = 18% от покупки)
- Создание Bonus записей в БД

**Пример вывода:**
```
Purchase amount: $1000.00
Total distributed: $180.00
Expected (18%): $180.00

Individual commissions:
Level 1: Start1       ✅ [start     ]   7.0% =   $70.00
Level 2: Builder1     ✅ [builder   ]  10.0% =  $100.00 [COMPRESSED]
Level 3: ROOT         ✅ [director  ]   1.0% =   $10.00 [SYSTEM ROOT]

✅ TEST PASSED: Commission calculation correct!
```

---

### `test_investment_bonus.py`

Тестирует кумулятивные investment bonuses.

**Использование:**
```bash
# Использует любую существующую БД с пользователем
python scripts/test_investment_bonus.py --user-id 5971989877
```

**Тестовая последовательность:**
1. Покупка $400 → нет бонуса (не достиг тира)
2. Покупка $700 → бонус $55 (достиг $1000, 5% tier)
3. Покупка $4000 → бонус $455 (достиг $5000, 10% tier)
4. Покупка $5000 → бонус $1065 (достиг $10000, 15% tier)
5. Покупка $10000 → бонус $3510 (достиг $20000, 20% tier)

**Проверяет:**
- Расчет кумулятивных бонусов
- Учет уже выданных бонусов
- Авто-покупку опционов
- Создание Bonus и Purchase записей

**Пример вывода:**
```
Purchase 1: $400
  Total invested:      $400
  Expected bonus:      $0
  Actual bonus:        $0
  ✅ No bonus expected, none granted

Purchase 2: $700
  Total invested:      $1100
  Expected bonus:      $55
  Actual bonus:        $55
  ✅ Bonus calculation correct!

...

✅ ALL TESTS PASSED!
```

---

## 🛠️ Утилиты

### `show_tree.py`

Визуализирует структуру MLM дерева.

**Использование:**
```bash
# Показать полное дерево от ROOT
python scripts/show_tree.py

# Показать поддерево от конкретного пользователя
python scripts/show_tree.py --root-id 5971989877

# Ограничить глубину вывода
python scripts/show_tree.py --max-depth 3

# Показать только статистику
python scripts/show_tree.py --stats
```

**Пример вывода:**
```
MLM STRUCTURE TREE
Legend:
  👑 = System Root (DEFAULT_REFERRER)
  ⭐️ = Real user (Telegram ID >= 1,000,000)
  🏆 = Pioneer (has pioneer bonus)
  ⏰ = Grace period active
  ✅ = Active user
  ❌ = Inactive user

└─ 👑 ⭐️ Артем (ID:526738615) ✅ [director] $100000.00
    ├─ Inactive1 (ID:100000) ❌
    │   └─ Builder1 (ID:100001) ✅ [builder]
    │       └─ Inactive2 (ID:100002) ❌
    │           └─ Start1 (ID:100003) ✅
    │               └─ ⭐️ Зодд (ID:5971989877) ✅ $10000.00

DATABASE STATISTICS
Total users:   6
Active users:  4 (66.7%)
Inactive users: 2 (33.3%)

Users by rank:
  director       1 (16.7%)
  builder        1 (16.7%)
  start          4 (66.7%)

Real users:  2
Dummy users: 4
```

---

## 🚀 Быстрый старт

### Сценарий 1: Тестирование комиссий

```bash
# 1. Создать тестовую БД
python scripts/populate_commission_test.py

# 2. Просмотреть структуру
python scripts/show_tree.py

# 3. Запустить тест комиссий
python scripts/test_commission_flow.py
```

### Сценарий 2: Тестирование Investment Bonus

```bash
# 1. Использовать существующую БД или создать новую
python populate_test_data.py

# 2. Запустить тест investment bonus
python scripts/test_investment_bonus.py --user-id 5971989877

# 3. Проверить результаты в БД
python scripts/show_tree.py --stats
```

### Сценарий 3: Ручное тестирование через телеграм

```bash
# 1. Создать полную тестовую БД
python populate_test_data.py

# 2. Посмотреть структуру и найти живых пользователей
python scripts/show_tree.py

# 3. Запустить бота
python jetup.py

# 4. Делать покупки от имени живых пользователей
# 5. Проверять результаты
python scripts/show_tree.py --stats
```

---

## 📊 Проверка результатов через SQL

### Комиссии по покупке

```sql
SELECT
    u.firstname,
    u.telegramID,
    u.isActive,
    u.rank,
    b.uplineLevel,
    b.bonusAmount,
    b.bonusRate,
    b.compressionApplied,
    b.commissionType
FROM bonus b
JOIN user u ON b.userID = u.userID
WHERE b.purchaseID = <purchase_id>
ORDER BY b.uplineLevel;
```

### Проверка суммы комиссий

```sql
SELECT
    SUM(bonusAmount) as total_commissions,
    (SELECT packPrice FROM purchase WHERE purchaseID = <purchase_id>) * 0.18 as expected,
    ABS(SUM(bonusAmount) - (SELECT packPrice FROM purchase WHERE purchaseID = <purchase_id>) * 0.18) as difference
FROM bonus
WHERE purchaseID = <purchase_id>;
```

### Investment bonuses для пользователя

```sql
SELECT
    bonusAmount,
    bonusRate,
    notes,
    createdAt
FROM bonus
WHERE userID = <user_id>
  AND projectID = <project_id>
  AND commissionType = 'investment_package'
ORDER BY createdAt;
```

### Активные пользователи в первой линии

```sql
SELECT
    firstname,
    telegramID,
    rank,
    isActive
FROM user
WHERE upline = <telegram_id>
  AND isActive = 1;
```

---

## 🔧 Кастомизация тестов

### Создание своего популятора

```python
#!/usr/bin/env python3
import sys
import os
import asyncio
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.db import get_session, setup_database, drop_all_tables
from models.user import User
from aiogram.types import User as TelegramUser

async def main():
    # Инициализация
    Config.initialize_from_env()
    drop_all_tables()
    setup_database()

    # Импорт проектов
    from services.imports import import_projects_and_options
    await import_projects_and_options()

    session = get_session()

    # Создание ROOT
    # ... ваш код ...

    # Создание тестовых пользователей
    # ... ваш код ...

    session.commit()
    session.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### Создание своего теста

```python
#!/usr/bin/env python3
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.db import get_session
from models.user import User
# ... импорты сервисов ...

async def main():
    Config.initialize_from_env()
    session = get_session()

    try:
        # Ваша тестовая логика
        # ...

    finally:
        session.close()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## ⚠️ Важные примечания

1. **Популяторы удаляют БД!** Все данные будут потеряны. Используйте только на тестовых окружениях.

2. **Живые пользователи** (⭐️) - это реальные Telegram аккаунты. Убедитесь, что у них правильные email и Telegram ID.

3. **Google Sheets** - популяторы импортируют проекты и опции из Google Sheets. Убедитесь, что Config.GOOGLE_SHEETS_URL настроен.

4. **Транзакции** - все тесты используют транзакции. В случае ошибки изменения откатываются.

5. **Время** - для тестирования месячных процессов используйте `timeMachine` из `mlm_system.utils.time_machine`.

---

## 🐛 Отладка

### Включить детальные логи

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Проверить chain integrity

```python
from mlm_system.utils.chain_walker import ChainWalker

session = get_session()
walker = ChainWalker(session)

# Проверить DEFAULT_REFERRER
if not walker.validate_default_referrer():
    print("❌ DEFAULT_REFERRER validation failed!")

# Найти orphan пользователей
orphans = walker.find_orphan_branches()
if orphans:
    print(f"❌ Found {len(orphans)} orphan users: {orphans}")
```

### Проверить объемы

```python
from mlm_system.services.volume_service import VolumeService

session = get_session()
volume_service = VolumeService(session)

user = session.query(User).filter_by(telegramID=<telegram_id>).first()
volumes = await volume_service.calculateUserVolumes(user.userID)

print(f"PV: {volumes['pv']}")
print(f"GV: {volumes['gv']}")
print(f"QV: {volumes['qv']}")
```

---

## 📚 Дополнительные ресурсы

- **MLM_TESTING_SCHEMA.md** - полная схема тестирования с описанием всех сценариев
- **populate_test_data.py** - основной популятор (в корне проекта)
- **mlm_system/** - исходный код MLM системы
- **models/** - модели данных

---

**Автор:** Claude Code
**Дата:** 2025-11-08
**Версия:** 1.0
