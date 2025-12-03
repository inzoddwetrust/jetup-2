# ТЗ: Миграция данных из Talentir в Jetup-2

## 1. Обзор

**Источник (Source):** Talentir (SQLAlchemy/SQLite)
**Цель (Target):** Jetup-2 (SQLAlchemy/SQLite)

Обе системы используют SQLAlchemy ORM с очень похожей структурой. Основные отличия связаны с добавлением новых полей в jetup-2 и реструктуризацией некоторых JSON-полей.

---

## 2. Сопоставление таблиц

| # | Talentir | Jetup-2 | Статус |
|---|----------|---------|--------|
| 1 | users | users | Требует трансформации |
| 2 | purchases | purchases | Полное соответствие |
| 3 | options | options | Полное соответствие |
| 4 | projects | projects | Полное соответствие |
| 5 | bonuses | bonuses | Полное соответствие |
| 6 | active_balances | active_balances | Полное соответствие |
| 7 | passive_balances | passive_balances | Полное соответствие |
| 8 | payments | payments | Полное соответствие |
| 9 | transfers | transfers | Полное соответствие |
| 10 | notifications | notifications | Полное соответствие |
| 11 | notification_deliveries | notification_deliveries | Полное соответствие |
| 12 | rank_history | rank_history | Полное соответствие |
| 13 | monthly_stats | monthly_stats | Полное соответствие |
| 14 | global_pool | global_pool | Полное соответствие |
| 15 | system_time | system_time | Требует трансформации |
| 16 | — | volume_update_queue | Новая таблица (не мигрируется) |

---

## 3. Детальное сопоставление полей

### 3.1 Таблица `users` (требует трансформации)

#### Поля с полным соответствием (копируются as-is):

| Поле | Тип | Примечание |
|------|-----|------------|
| userID | Integer | PK |
| telegramID | BigInteger | UNIQUE |
| upline | BigInteger | Nullable |
| createdAt | DateTime | |
| email | String | Nullable |
| firstname | String | Nullable |
| surname | String | Nullable |
| birthday | String | Nullable |
| address | String | Nullable |
| phoneNumber | String | Nullable |
| city | String | Nullable |
| country | String | Nullable |
| passport | String | Nullable |
| lang | String | Default "en" |
| status | String | Default "active" |
| lastActive | DateTime | Nullable |
| balanceActive | DECIMAL(12,2) | Default 0.0 |
| balancePassive | DECIMAL(12,2) | Default 0.0 |
| rank | String | Default "start" |
| isActive | Boolean | Default False |
| teamVolumeTotal | DECIMAL(12,2) | Default 0.0 |
| mlmStatus | JSON | Nullable |
| mlmVolumes | JSON | Nullable |
| notes | Text | Nullable |
| stateFSM | String | Nullable |

#### Поля, требующие трансформации:

| Talentir | Jetup-2 | Трансформация |
|----------|---------|---------------|
| `kyc` (String) | `personalData.kyc` (JSON) | Обернуть в JSON: `{"kyc": value}` |
| `isFilled` (Boolean) | `personalData.dataFilled` (JSON) | Обернуть в JSON: `{"dataFilled": value}` |
| — | `personalData.eula` | Установить default: `true` |

#### Новые поля в Jetup-2 (требуют инициализации):

| Поле | Тип | Инициализация |
|------|-----|---------------|
| fullVolume | DECIMAL(15,2) | `0` |
| totalVolume | JSON | `null` |
| personalVolumeTotal | DECIMAL(12,2) | `0` |
| emailVerification | JSON | `null` |
| settings | JSON | `null` |
| ownerTelegramID | BigInteger | Копировать из `telegramID` |
| ownerEmail | String | Копировать из `email` |
| updatedAt | DateTime | Установить `now()` |

#### Правило трансформации `personalData`:

```python
def transform_personal_data(talentir_user):
    return {
        "eula": True,
        "dataFilled": talentir_user.isFilled if talentir_user.isFilled else False,
        "kyc": talentir_user.kyc if talentir_user.kyc else "none"
    }
```

---

### 3.2 Таблица `system_time` (требует трансформации)

#### Поля с полным соответствием:

| Поле | Тип |
|------|-----|
| timeID | Integer |
| realTime | DateTime |
| virtualTime | DateTime |
| isTestMode | Boolean |
| createdBy | Integer |
| notes | String |

#### Новые поля в Jetup-2:

| Поле | Тип | Инициализация |
|------|-----|---------------|
| schedulerState | JSON | `null` |

---

### 3.3 Таблицы с полным соответствием

Следующие таблицы копируются **без изменений** (все поля совпадают):

- `purchases`
- `options`
- `projects`
- `bonuses`
- `active_balances`
- `passive_balances`
- `payments`
- `transfers`
- `notifications`
- `notification_deliveries`
- `rank_history`
- `monthly_stats`
- `global_pool`

---

## 4. Порядок миграции

Из-за foreign key зависимостей, таблицы должны мигрироваться в следующем порядке:

```
1. users              (нет зависимостей)
2. projects           (нет зависимостей)
3. options            (зависит от projects - по projectID)
4. purchases          (зависит от users, options)
5. bonuses            (зависит от users, purchases)
6. active_balances    (зависит от users)
7. passive_balances   (зависит от users)
8. payments           (зависит от users)
9. transfers          (зависит от users)
10. notifications     (нет зависимостей)
11. notification_deliveries (зависит от notifications, users)
12. rank_history      (зависит от users)
13. monthly_stats     (зависит от users)
14. global_pool       (нет FK зависимостей)
15. system_time       (нет FK зависимостей)
```

---

## 5. Алгоритм миграции

### 5.1 Общий процесс

```
1. Подключение к обеим БД
2. Для каждой таблицы (в порядке из п.4):
   a. Считать все записи из Talentir
   b. Применить трансформацию (если нужна)
   c. Записать в Jetup-2
   d. Проверить количество записей
3. Верификация целостности данных
4. Отчёт о миграции
```

### 5.2 Обработка ошибок

- При ошибке на одной записи - логировать и продолжать
- Вести журнал failed records для последующего анализа
- Использовать транзакции для атомарности batch-операций

---

## 6. Спецификация скрипта

### 6.1 Входные параметры

```
--source-db       Путь к БД Talentir (или DATABASE_URL)
--target-db       Путь к БД Jetup-2 (или DATABASE_URL)
--batch-size      Размер batch для вставки (default: 1000)
--dry-run         Показать план без выполнения
--tables          Список таблиц через запятую (опционально)
--skip-verify     Пропустить верификацию
--log-file        Путь к файлу логов
```

### 6.2 Выходные данные

```
- Консольный вывод прогресса
- Файл лога с детальной информацией
- JSON-отчёт о миграции:
  {
    "status": "success|partial|failed",
    "started_at": "ISO datetime",
    "completed_at": "ISO datetime",
    "tables": {
      "users": {
        "source_count": 1000,
        "migrated_count": 1000,
        "failed_count": 0,
        "status": "success"
      },
      ...
    },
    "errors": []
  }
```

---

## 7. Структура скрипта

```
migration/
├── __init__.py
├── migrator.py           # Основной класс миграции
├── transformers/         # Трансформации для таблиц
│   ├── __init__.py
│   ├── user_transformer.py
│   └── system_time_transformer.py
├── validators/           # Валидация данных
│   ├── __init__.py
│   └── integrity_checker.py
├── utils/
│   ├── __init__.py
│   ├── db_connector.py
│   └── logger.py
└── run_migration.py      # CLI entry point
```

---

## 8. Код трансформаторов

### 8.1 UserTransformer

```python
class UserTransformer:
    """Трансформация записей таблицы users из Talentir в Jetup-2"""

    @staticmethod
    def transform(source_row: dict) -> dict:
        """
        Преобразует запись пользователя из формата Talentir в формат Jetup-2
        """
        # Копируем все совпадающие поля
        result = {
            'userID': source_row['userID'],
            'telegramID': source_row['telegramID'],
            'upline': source_row.get('upline'),
            'createdAt': source_row['createdAt'],
            'email': source_row.get('email'),
            'firstname': source_row.get('firstname'),
            'surname': source_row.get('surname'),
            'birthday': source_row.get('birthday'),
            'address': source_row.get('address'),
            'phoneNumber': source_row.get('phoneNumber'),
            'city': source_row.get('city'),
            'country': source_row.get('country'),
            'passport': source_row.get('passport'),
            'lang': source_row.get('lang', 'en'),
            'status': source_row.get('status', 'active'),
            'lastActive': source_row.get('lastActive'),
            'balanceActive': source_row.get('balanceActive', 0.0),
            'balancePassive': source_row.get('balancePassive', 0.0),
            'rank': source_row.get('rank', 'start'),
            'isActive': source_row.get('isActive', False),
            'teamVolumeTotal': source_row.get('teamVolumeTotal', 0.0),
            'mlmStatus': source_row.get('mlmStatus'),
            'mlmVolumes': source_row.get('mlmVolumes'),
            'notes': source_row.get('notes'),
            'stateFSM': source_row.get('stateFSM'),
        }

        # Трансформация personalData
        result['personalData'] = {
            'eula': True,
            'dataFilled': bool(source_row.get('isFilled', False)),
            'kyc': source_row.get('kyc', 'none')
        }

        # Новые поля Jetup-2
        result['fullVolume'] = 0
        result['totalVolume'] = None
        result['personalVolumeTotal'] = 0
        result['emailVerification'] = None
        result['settings'] = None

        # Audit fields
        result['ownerTelegramID'] = source_row['telegramID']
        result['ownerEmail'] = source_row.get('email')
        result['updatedAt'] = datetime.now(timezone.utc)

        return result
```

### 8.2 SystemTimeTransformer

```python
class SystemTimeTransformer:
    """Трансформация записей таблицы system_time"""

    @staticmethod
    def transform(source_row: dict) -> dict:
        result = dict(source_row)
        result['schedulerState'] = None  # Новое поле
        return result
```

---

## 9. Верификация

### 9.1 Проверки после миграции

1. **Количество записей** - должно совпадать в обеих БД
2. **Целостность FK** - все foreign keys должны быть валидны
3. **Суммы балансов** - SUM(balanceActive), SUM(balancePassive) должны совпадать
4. **Уникальность** - telegramID должны быть уникальны
5. **Referral chain** - upline должны ссылаться на существующих пользователей

### 9.2 Скрипт верификации

```python
def verify_migration(source_session, target_session):
    checks = []

    # Check 1: Record counts
    for table in TABLES:
        source_count = source_session.query(table).count()
        target_count = target_session.query(table).count()
        checks.append({
            'table': table.__tablename__,
            'check': 'record_count',
            'passed': source_count == target_count,
            'source': source_count,
            'target': target_count
        })

    # Check 2: Balance sums
    source_active = source_session.query(
        func.sum(User.balanceActive)
    ).scalar()
    target_active = target_session.query(
        func.sum(User.balanceActive)
    ).scalar()
    checks.append({
        'check': 'balance_active_sum',
        'passed': source_active == target_active,
        'source': source_active,
        'target': target_active
    })

    return checks
```

---

## 10. Риски и митигация

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Несовместимость типов данных | Низкая | Высокое | Тестирование на копии БД |
| Потеря данных при трансформации | Средняя | Высокое | Backup + dry-run режим |
| Нарушение FK constraints | Средняя | Среднее | Порядок миграции + отключение FK |
| Timeout на больших таблицах | Средняя | Низкое | Batch-обработка |
| Дубликаты telegramID | Низкая | Высокое | Pre-migration validation |

---

## 11. План тестирования

### 11.1 Unit-тесты

- Тесты трансформаторов для каждой таблицы
- Тесты валидации данных
- Тесты обработки edge cases (NULL, пустые строки, спец.символы)

### 11.2 Integration-тесты

- Миграция тестового dataset'а (100 записей)
- Проверка всех FK relationships
- Проверка JSON-полей

### 11.3 Приёмочные тесты

- Полная миграция на копии production БД
- Сравнение результатов с ожидаемыми
- Тест rollback-процедуры

---

## 12. Checklist перед запуском

- [ ] Backup исходной БД Talentir
- [ ] Backup целевой БД Jetup-2 (если есть данные)
- [ ] Проверить доступ к обеим БД
- [ ] Проверить дисковое пространство
- [ ] Запустить dry-run
- [ ] Проверить логи dry-run
- [ ] Получить approval на миграцию
- [ ] Запустить миграцию
- [ ] Проверить отчёт о миграции
- [ ] Запустить верификацию
- [ ] Проверить работу приложения на новых данных

---

## 13. Rollback план

В случае критической ошибки:

1. Остановить миграционный скрипт
2. Очистить целевую БД: `DELETE FROM <table>` для всех таблиц в обратном порядке
3. Или восстановить из backup
4. Анализировать логи ошибок
5. Исправить проблему
6. Повторить миграцию

---

## 14. Оценка времени

| Этап | Оценка |
|------|--------|
| Разработка скрипта | 4-6 часов |
| Unit-тесты | 2-3 часа |
| Integration-тесты | 2-3 часа |
| Тестовая миграция | 1-2 часа |
| Production миграция | Зависит от размера БД |
| Верификация | 1 час |

---

## 15. Контакты и ответственные

- **Разработчик**: [TBD]
- **Владелец данных**: [TBD]
- **DBA/DevOps**: [TBD]

---

*Документ создан: 2025-12-03*
*Версия: 1.0*
