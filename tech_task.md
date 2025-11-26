# ТЕХНИЧЕСКОЕ ЗАДАНИЕ: Доработка jetup-2

**Версия:** 1.0  
**Дата:** 27 ноября 2025  
**Проект:** jetup-2 (замена Talentir)

---

## 1. ОБЗОР ПРОЕКТА

### 1.1 Контекст

Проект jetup-2 создаётся как замена legacy-бота Talentir. Основные изменения:

| Аспект | Talentir | jetup-2 |
|--------|----------|---------|
| Framework | aiogram 2.x | aiogram 3.x |
| Архитектура | Монолит (main.py ~3000 строк) | Модульная (handlers/, services/) |
| MLM система | Встроена в main.py | Отдельный модуль mlm_system/ |
| DI | Глобальные переменные | Middleware injection |

### 1.2 Текущий статус миграции

#### ✅ ПОЛНОСТЬЮ ПЕРЕНЕСЕНО (100%):
- Модели данных (models/)
- Core services (templates, message_manager, google_services)
- Email system (SMTP + Mailgun)
- Background processors (notification_processor, invoice_cleaner)
- Основные handlers (start, finances, payments, team, portfolio, etc.)
- MLM система (98% — см. ниже)

#### ⚠️ ЧАСТИЧНО ПЕРЕНЕСЕНО:
- Admin handlers (только &upconfig, &stats, &testmail)
- Legacy processor (есть файл, требует верификации)

#### ❌ НЕ ПЕРЕНЕСЕНО:
- Payment approval callbacks (approve/reject)
- Большинство админских команд
- Broadcast система (отложено, требует переработки)
- Autoship логика (только заглушка)

### 1.3 Критичные расхождения

#### Конфигурация рангов (ranks.py vs ТЗ)

| Ранг | ТЗ | Код | Статус |
|------|-----|-----|--------|
| Builder TV | $5,000 | $50,000 | ⚠️ ×10 |
| Growth TV | $25,000 | $250,000 | ⚠️ ×10 |
| Leadership TV | $125,000 | $1,000,000 | ⚠️ ×8 |
| Director TV | $500,000 | $5,000,000 | ⚠️ ×10 |

**Решение:** Корректируется вручную в `mlm_system/config/ranks.py`

#### Notification model — несоответствие полей

В модели `models/notification.py` используется **camelCase**:
```python
targetType = Column(String)
targetValue = Column(String)
parseMode = Column(String)
```

Но в `mlm_system/events/handlers.py` используется **snake_case** — это БАГ!

#### Active Partners — неправильный подсчёт

**Файл:** `mlm_system/services/rank_service.py`

Метод `_countActivePartners()` считает только **уровень 1**, а должен считать **по всей структуре**.

```python
# НЕПРАВИЛЬНО:
User.upline == user.telegramID  # Только прямые рефералы

# ПРАВИЛЬНО:
ChainWalker.walk_downline()  # Вся структура рекурсивно
```

**Влияние:** Пользователи не получают ранги из-за заниженного подсчёта.

---

## 2. PHASE 1: КРИТИЧНЫЕ ИСПРАВЛЕНИЯ

> **Приоритет:** БЛОКЕРЫ ЗАПУСКА  
> **Срок:** До production release

### 2.1 Payment Approval Handlers

#### Проблема
Админы получают уведомления о новых платежах, но не могут их подтвердить/отклонить — отсутствуют callback handlers.

#### Текущий flow (сломан на шаге 4)
```
1. Пользователь создаёт Payment (status="pending")
2. Пользователь вводит TXID
3. Payment.status = "check"
4. create_payment_check_notification() → Notification админам
5. ❌ Админ нажимает кнопку → НИЧЕГО НЕ ПРОИСХОДИТ
```

#### Требуемая реализация

**Файл:** `handlers/admin/payment_commands.py`

**Callbacks:**

| Callback Data | Handler | Действие |
|---------------|---------|----------|
| `approve_payment_{id}` | `handle_initial_approval` | Показать подтверждение |
| `final_approve_{id}` | `handle_final_approval` | Выполнить транзакцию |
| `reject_payment_{id}` | `handle_rejection` | Отклонить платёж |

**Логика `handle_final_approval`:**
```python
async def handle_final_approval(callback_query, user, session, message_manager):
    """
    Финальное подтверждение платежа.
    
    Транзакция:
    1. Payment.status = "paid"
    2. Payment.confirmedBy = admin_id
    3. Payment.confirmationTime = now()
    4. ActiveBalance += amount (status='done', reason=f'payment={payment_id}')
    5. user.balanceActive += amount
    6. Notification пользователю (user_payment_approved)
    """
```

**Логика `handle_rejection`:**
```python
async def handle_rejection(callback_query, user, session, message_manager):
    """
    Отклонение платежа.
    
    1. Payment.status = "failed"
    2. Notification пользователю (user_payment_rejected)
    """
```

**Шаблоны Google Sheets (лист Templates):**

| stateKey | Назначение |
|----------|------------|
| `admin_new_payment_notification` | Уведомление админам с кнопками |
| `admin_payment_confirm_action` | "Точно подтвердить?" |
| `admin_payment_approved` | "Платёж #{id} подтверждён" |
| `admin_payment_rejected` | "Платёж #{id} отклонён" |
| `admin_payment_wrong_status` | "Платёж уже обработан" |
| `user_payment_approved` | Уведомление пользователю |
| `user_payment_rejected` | Уведомление пользователю |

---

### 2.2 Admin Commands — Исправление логики

#### Текущая проблема

`&upconfig` делает НЕ ТО — импортирует Projects/Options вместо Config.

#### Правильное разделение

| Команда | Что делает | Источник |
|---------|------------|----------|
| `&upconfig` | Переменные конфигурации бота | GS лист "Config" |
| `&upro` | Projects + Options + очистка кеша BookStack | GS листы "Projects", "Options" |
| `&ut` | Шаблоны сообщений бота | GS лист "Templates" |

#### Реализация &upconfig (ИСПРАВИТЬ)

**Файл:** `handlers/admin/config_commands.py`

```python
@config_router.message(F.text == '&upconfig')
async def cmd_upconfig(message: Message, user: User, session: Session):
    """
    Обновление конфигурации бота из Google Sheets.
    
    Flow:
    1. ConfigImporter.import_config() → dict
    2. ConfigImporter.update_config_module(config_dict)
    3. Переинициализация зависимых сервисов (EmailService, etc.)
    """
    if message.from_user.id not in Config.get(Config.ADMINS):
        return
    
    reply = await message.reply("🔄 Обновляю конфигурацию...")
    
    try:
        from sync_system.config_importer import ConfigImporter
        config_dict = await ConfigImporter.import_config()
        ConfigImporter.update_config_module(config_dict)
        
        await reply.edit_text(
            f"✅ Конфигурация обновлена\n"
            f"Загружено {len(config_dict)} переменных"
        )
    except Exception as e:
        await reply.edit_text(f"❌ Ошибка: {e}")
```

#### Реализация &upro (ДОБАВИТЬ)

```python
@config_router.message(F.text == '&upro')
async def cmd_upro(message: Message, user: User, session: Session):
    """
    Обновление проектов и опционов + очистка кеша документов.
    
    Flow:
    1. TemplateCache.clear() — очистка кеша BookStack
    2. import_projects_and_options() — импорт из GS
    3. stats_service.refresh_all() — пересчёт статистики
    """
    if message.from_user.id not in Config.get(Config.ADMINS):
        return
    
    reply = await message.reply("🔄 Обновляю проекты и опционы...")
    
    try:
        # 1. Очистка кеша BookStack
        from services.document.bookstack_service import TemplateCache
        TemplateCache.clear()
        
        # 2. Импорт Projects + Options
        result = await import_projects_and_options()
        
        # 3. Пересчёт статистики
        stats_service = get_service(StatsService)
        await stats_service.refresh_all()
        
        await reply.edit_text(
            f"✅ Проекты и опционы обновлены\n"
            f"Projects: {result['projects']}\n"
            f"Options: {result['options']}\n"
            f"Кеш BookStack очищен"
        )
    except Exception as e:
        await reply.edit_text(f"❌ Ошибка: {e}")
```

#### Реализация &ut (ДОБАВИТЬ)

```python
@config_router.message(F.text == '&ut')
async def cmd_ut(message: Message, user: User, session: Session):
    """
    Обновление шаблонов сообщений из Google Sheets.
    
    Flow:
    1. MessageTemplates.load_templates() — перезагрузка кеша
    """
    if message.from_user.id not in Config.get(Config.ADMINS):
        return
    
    reply = await message.reply("🔄 Обновляю шаблоны...")
    
    try:
        from core.templates import MessageTemplates
        await MessageTemplates.load_templates()
        
        templates_count = len(MessageTemplates._cache)
        await reply.edit_text(f"✅ Шаблоны обновлены ({templates_count} записей)")
    except Exception as e:
        await reply.edit_text(f"❌ Ошибка: {e}")
```

---

### 2.3 Notification Field Names Fix

#### Проблема

В `mlm_system/events/handlers.py` используется snake_case для полей Notification, но модель использует camelCase.

#### Файлы для исправления

**mlm_system/events/handlers.py** — все вызовы Notification():

```python
# БЫЛО (неправильно):
Notification(
    source="mlm_system",
    text=text,
    buttons=buttons,
    target_type="user",        # ❌
    target_value=str(...),     # ❌
    parse_mode="HTML"          # ❌
)

# СТАЛО (правильно):
Notification(
    source="mlm_system",
    text=text,
    buttons=buttons,
    targetType="user",         # ✅
    targetValue=str(...),      # ✅
    parseMode="HTML"           # ✅
)
```

#### Полный список полей для замены

| snake_case (неправильно) | camelCase (правильно) |
|--------------------------|----------------------|
| `target_type` | `targetType` |
| `target_value` | `targetValue` |
| `parse_mode` | `parseMode` |
| `disable_preview` | `disablePreview` |
| `expiry_at` | `expiryAt` |
| `auto_delete` | `autoDelete` |

---

### 2.4 Autoship Implementation

#### Текущее состояние

**Файл:** `background/mlm_scheduler.py`

```python
async def processAutoship(self):
    """Process autoship purchases on Grace Day."""
    # TODO: Implement Autoship purchase logic
    pass
```

#### Спецификация

| Параметр | Значение |
|----------|----------|
| **Сумма** | Настраиваемая через Config (GS лист "Config") |
| **Проект/Опцион** | Последний купленный пользователем |
| **Источник средств** | ActiveBalance |
| **Триггер** | 1-е число месяца (Grace Day) |
| **Попытки** | 3 в течение дня |
| **При недостатке** | Notification с предложением пополнить |
| **После 3 неудач** | Notification + autoship.enabled = false |
| **Цель** | Успеть в Grace Day для сохранения бонусов |

#### Алгоритм

```python
async def processAutoship(self):
    """
    Process autoship purchases on Grace Day (1st of month).
    
    Algorithm:
    1. Проверить, что сегодня Grace Day (1-е число)
    2. Получить AUTOSHIP_AMOUNT из Config
    3. Найти пользователей с autoship.enabled = true
    4. Для каждого пользователя:
       a. Проверить autoship.attempts < 3
       b. Проверить balanceActive >= AUTOSHIP_AMOUNT
       c. Найти последнюю покупку → project_id, option_id
       d. Если баланс достаточен:
          - Создать Purchase
          - Списать с ActiveBalance
          - autoship.lastPurchaseDate = today
          - autoship.attempts = 0
          - Notification (autoship_success)
       e. Если баланс недостаточен:
          - autoship.attempts += 1
          - Если attempts >= 3:
            - autoship.enabled = false
            - Notification (autoship_disabled)
          - Иначе:
            - Notification (autoship_insufficient_balance)
    """
```

#### Структура user.settings['autoship']

```python
{
    "enabled": True/False,
    "amount": 200.00,  # или из Config если не указано
    "attempts": 0,     # счётчик неудачных попыток в этом месяце
    "lastPurchaseDate": "2025-01-01",
    "lastAttemptDate": "2025-01-01"
}
```

#### Шаблоны (Google Sheets)

| stateKey | Назначение |
|----------|------------|
| `autoship_success` | "Автопокупка выполнена успешно" |
| `autoship_insufficient_balance` | "Недостаточно средств, попытка {n}/3" |
| `autoship_disabled` | "Autoship отключён после 3 неудачных попыток" |

---

### 2.5 Active Partners Count — КРИТИЧНЫЙ БАГ

#### Проблема

Метод `_countActivePartners` считает только **прямых рефералов (уровень 1)**, а должен считать по **всей структуре**.

**Файл:** `mlm_system/services/rank_service.py`

```python
# ТЕКУЩАЯ РЕАЛИЗАЦИЯ (неправильно):
async def _countActivePartners(self, user: User) -> int:
    activeCount = self.session.query(func.count(User.userID)).filter(
        User.upline == user.telegramID,  # ❌ Только уровень 1!
        User.isActive == True
    ).scalar() or 0
    return activeCount
```

#### Влияние

Пользователи **не получают ранги**, даже если у них достаточно активных партнёров во всей структуре.

Пример:
- User A имеет 2 прямых реферала (оба active)
- Каждый из них имеет по 5 активных рефералов
- **Текущий результат:** activePartners = 2
- **Правильный результат:** activePartners = 12

#### Исправление

Использовать `ChainWalker` для рекурсивного обхода (аналогично `_countTotalTeamSize`):

```python
async def _countActivePartners(self, user: User) -> int:
    """
    Count active partners in user's ENTIRE structure.
    
    Active partner = user with isActive == True anywhere in downline.
    Uses ChainWalker for safe recursive traversal.
    """
    from mlm_system.utils.chain_walker import ChainWalker
    
    walker = ChainWalker(self.session)
    active_count = [0]  # Use list to allow modification in callback
    
    def count_active(downline_user, level):
        if downline_user.isActive:
            active_count[0] += 1
    
    walker.walk_downline(user, count_active, max_depth=50)
    
    return active_count[0]
```

#### Альтернативный вариант (без callback)

Добавить метод в `ChainWalker`:

```python
# mlm_system/utils/chain_walker.py

def count_active_downline(self, user: User, max_depth: int = 50) -> int:
    """
    Count active users in entire downline structure.
    
    Args:
        user: Starting user
        max_depth: Maximum depth for recursion
        
    Returns:
        Count of users with isActive == True
    """
    count = [0]
    
    def counter(downline_user, level):
        if downline_user.isActive:
            count[0] += 1
    
    self.walk_downline(user, counter, max_depth)
    return count[0]
```

Тогда в `rank_service.py`:

```python
async def _countActivePartners(self, user: User) -> int:
    from mlm_system.utils.chain_walker import ChainWalker
    walker = ChainWalker(self.session)
    return walker.count_active_downline(user)
```

#### Тестирование

После исправления проверить:
1. Пользователь с активными партнёрами только на уровне 1
2. Пользователь с активными партнёрами на уровнях 2-5
3. Смешанная структура (active/inactive на разных уровнях)
4. Проверка квалификации на ранг с новым подсчётом

---

### 2.6 Time Machine — Админская команда

#### Описание

Time Machine позволяет "перевести часы" для тестирования Grace Day, месячных задач и других time-sensitive операций без ожидания реальной даты.

#### Текущее состояние

**✅ Реализовано:**
- Класс `TimeMachine` (`mlm_system/utils/time_machine.py`)
- Методы: `setTime()`, `advanceTime()`, `resetToRealTime()`
- Свойства: `now`, `isGraceDay`, `currentMonth`, `isMonthEnd`
- Модель `SystemTime` для персистентности

**❌ Не реализовано:**
- Админская команда управления
- Синхронизация с БД (SystemTime)
- Восстановление состояния после перезапуска бота

#### Требуемая реализация

**Файл:** `handlers/admin/utils_commands.py`

**Команда `&time`:**

```
&time                      — Показать текущее время (real/virtual)
&time set 2025-01-01       — Установить виртуальную дату
&time set 2025-01-01 10:00 — Установить виртуальную дату и время
&time grace                — Перейти на 1-е число текущего месяца
&time +1d                  — Продвинуть на 1 день
&time +5d                  — Продвинуть на 5 дней
&time +1m                  — Продвинуть на 1 месяц
&time reset                — Вернуться к реальному времени
```

#### Реализация команды

```python
@utils_router.message(F.text.startswith('&time'))
async def cmd_time(message: Message, user: User, session: Session):
    """
    Time Machine control for testing Grace Day and monthly operations.
    
    Usage:
        &time              - Show current time status
        &time set DATE     - Set virtual date (YYYY-MM-DD or YYYY-MM-DD HH:MM)
        &time grace        - Jump to 1st of current month
        &time +Nd          - Advance N days
        &time +Nm          - Advance N months
        &time reset        - Return to real time
    """
    if not is_admin(message.from_user.id):
        return
    
    from mlm_system.utils.time_machine import timeMachine
    from models.mlm.system_time import SystemTime
    
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    
    # &time — показать статус
    if not args:
        status = "🕐 <b>Time Machine Status</b>\n\n"
        if timeMachine._isTestMode:
            status += f"⚠️ <b>TEST MODE ACTIVE</b>\n"
            status += f"Virtual time: {timeMachine.now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        else:
            status += f"Real time: {timeMachine.now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        status += f"\nGrace Day: {'✅ YES' if timeMachine.isGraceDay else '❌ No'}"
        status += f"\nCurrent month: {timeMachine.currentMonth}"
        
        await message.reply(status, parse_mode="HTML")
        return
    
    cmd = args[0].lower()
    
    # &time set DATE
    if cmd == 'set' and len(args) >= 2:
        date_str = ' '.join(args[1:])
        try:
            # Try with time
            if len(date_str) > 10:
                new_time = datetime.strptime(date_str, '%Y-%m-%d %H:%M')
            else:
                new_time = datetime.strptime(date_str, '%Y-%m-%d')
            
            new_time = new_time.replace(tzinfo=timezone.utc)
            timeMachine.setTime(new_time, adminId=message.from_user.id)
            
            # Save to DB
            await _save_time_state(session, new_time, message.from_user.id)
            
            await message.reply(
                f"✅ Virtual time set to: {new_time.strftime('%Y-%m-%d %H:%M')}\n"
                f"Grace Day: {'✅ YES' if timeMachine.isGraceDay else '❌ No'}"
            )
        except ValueError:
            await message.reply("❌ Invalid date format. Use: YYYY-MM-DD or YYYY-MM-DD HH:MM")
        return
    
    # &time grace — перейти на 1-е число
    if cmd == 'grace':
        now = datetime.now(timezone.utc)
        grace_day = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        timeMachine.setTime(grace_day, adminId=message.from_user.id)
        
        await _save_time_state(session, grace_day, message.from_user.id, "Testing Grace Day")
        
        await message.reply(
            f"✅ Jumped to Grace Day: {grace_day.strftime('%Y-%m-%d')}\n"
            f"Grace Day: ✅ YES"
        )
        return
    
    # &time +Nd / +Nm — продвинуть время
    if cmd.startswith('+'):
        if not timeMachine._isTestMode:
            await message.reply("❌ Enable test mode first with `&time set DATE`")
            return
        
        try:
            value = int(cmd[1:-1])
            unit = cmd[-1].lower()
            
            if unit == 'd':
                timeMachine.advanceTime(days=value)
            elif unit == 'm':
                # Approximate month as 30 days
                timeMachine.advanceTime(days=value * 30)
            else:
                await message.reply("❌ Use +Nd (days) or +Nm (months)")
                return
            
            await _save_time_state(session, timeMachine.now, message.from_user.id)
            
            await message.reply(
                f"✅ Time advanced to: {timeMachine.now.strftime('%Y-%m-%d %H:%M')}\n"
                f"Grace Day: {'✅ YES' if timeMachine.isGraceDay else '❌ No'}"
            )
        except ValueError:
            await message.reply("❌ Invalid format. Use: +1d, +5d, +1m")
        return
    
    # &time reset
    if cmd == 'reset':
        timeMachine.resetToRealTime()
        
        # Clear in DB
        await _clear_time_state(session)
        
        await message.reply(
            f"✅ Returned to real time: {timeMachine.now.strftime('%Y-%m-%d %H:%M')}"
        )
        return
    
    await message.reply("❌ Unknown command. Use: set, grace, +Nd, reset")


async def _save_time_state(session: Session, virtual_time: datetime, admin_id: int, notes: str = None):
    """Save time machine state to DB for persistence."""
    from models.mlm.system_time import SystemTime
    
    # Get or create record
    state = session.query(SystemTime).first()
    if not state:
        state = SystemTime()
        session.add(state)
    
    state.virtualTime = virtual_time
    state.isTestMode = True
    state.createdBy = admin_id
    state.notes = notes
    state.realTime = datetime.now(timezone.utc)
    
    session.commit()


async def _clear_time_state(session: Session):
    """Clear time machine state in DB."""
    from models.mlm.system_time import SystemTime
    
    state = session.query(SystemTime).first()
    if state:
        state.virtualTime = None
        state.isTestMode = False
        session.commit()
```

#### Восстановление состояния при старте бота

**Файл:** `core/system_services.py` или `jetup.py`

```python
async def restore_time_machine_state():
    """Restore time machine state from DB after bot restart."""
    from mlm_system.utils.time_machine import timeMachine
    from models.mlm.system_time import SystemTime
    
    with get_db_session_ctx() as session:
        state = session.query(SystemTime).first()
        
        if state and state.isTestMode and state.virtualTime:
            timeMachine.setTime(state.virtualTime)
            logger.warning(
                f"⚠️ Time Machine restored to TEST MODE: {state.virtualTime}"
            )
```

#### Безопасность

1. **Только для ADMINS** — проверка `is_admin()`
2. **Логирование** — все изменения записываются
3. **Предупреждение при старте** — если бот запущен в test mode
4. **Видимость** — статус отображается в `&stats`

#### Интеграция с &stats

Добавить в вывод `&stats`:

```python
if timeMachine._isTestMode:
    stats_text += f"\n\n⚠️ TIME MACHINE ACTIVE: {timeMachine.now.strftime('%Y-%m-%d')}"
```

---

## 3. PHASE 2: LEGACY & SYNC

> **Приоритет:** ВАЖНО (первые недели после запуска)

### 3.1 Legacy Processor — Верификация

#### Описание

Legacy Processor обрабатывает миграцию пользователей из внешней Google таблицы. Ограничение: **только чтение + запись в 3 колонки**.

#### Таблица миграции

**Sheet ID:** `1mbaRSbOs0Hc98iJ3YnZnyqL5yxeSuPJCef5PFjPHpFg`  
**Лист:** "Users"

| Колонка | Поле | Доступ |
|---------|------|--------|
| A | email | 🔒 Read only |
| B | upliner | 🔒 Read only |
| C | project | 🔒 Read only |
| D | qty | 🔒 Read only |
| E | — | — |
| **F** | **IsFound** | ✅ Write |
| **G** | **UplinerFound** | ✅ Write |
| **H** | **PurchaseDone** | ✅ Write |

#### Алгоритм обработки (3 независимых шага)

```
┌─────────────────────────────────────────────────────────────┐
│  ШАГ 1: _find_user()                                        │
│  ─────────────────────                                      │
│  • Найти user в БД по email (normalized)                    │
│  • Проверить emailConfirmed == '1'                          │
│  • Записать userID в колонку F (IsFound)                    │
│  • Отправить welcome notification                           │
├─────────────────────────────────────────────────────────────┤
│  ШАГ 2: _assign_upliner()                                   │
│  ─────────────────────────                                  │
│  • Найти upliner по email                                   │
│  • Проверить upliner.emailConfirmed == '1'                  │
│  • Установить user.upline = upliner.telegramID              │
│  • Записать "1" в колонку G (UplinerFound)                  │
│  • Отправить notifications обоим                            │
│  • Поддержка "SAME" — сохранить текущего аплайнера          │
├─────────────────────────────────────────────────────────────┤
│  ШАГ 3: _create_purchase()                                  │
│  ─────────────────────────                                  │
│  • Найти project по имени                                   │
│  • Найти option (packQty >= qty)                            │
│  • Создать Purchase + ActiveBalance                         │
│  • Записать "1" в колонку H (PurchaseDone)                  │
│  • Отправить purchase notification                          │
└─────────────────────────────────────────────────────────────┘
```

#### Ключевые особенности

1. **Email normalization:**
```python
def normalize_email(email: str) -> str:
    email = email.lower().strip()
    if '@gmail.com' in email:
        local, domain = email.split('@', 1)
        local = local.replace('.', '')  # Gmail игнорирует точки
    return f"{local}@{domain}"
```

2. **"SAME" keyword:**
```python
if user.upliner.upper() == "SAME":
    # Оставить текущего аплайнера, просто пометить как обработанного
    await self._update_sheet(user.row_index, 'UplinerFound', '1')
    return True
```

3. **Background execution:**
   - Интервал: каждые 10 минут
   - Batch size: 50 записей
   - Lock: `_processing` флаг

#### Задача верификации

Сравнить `background/legacy_processor.py` (jetup-2) с `legacy_user_processor.py` (Talentir):

- [ ] Проверить соответствие алгоритма
- [ ] Проверить имена полей Notification (camelCase!)
- [ ] Проверить работу с Google Sheets API
- [ ] Проверить шаблоны уведомлений

#### Шаблоны (Google Sheets)

| stateKey | Назначение |
|----------|------------|
| `legacy_user_welcome` | Приветствие найденному пользователю |
| `legacy_upliner_assigned_user` | "Вам назначен аплайнер {name}" |
| `legacy_upliner_assigned_upliner` | "К вам добавлен реферал {name}" |
| `legacy_purchase_created_user` | "Покупка {qty} шт. создана" |

---

### 3.2 Sync System — Команда &import

#### Архитектура синхронизации

```
┌─────────────────────────────────────────────────────────────────┐
│                    ДВУНАПРАВЛЕННАЯ СИНХРОНИЗАЦИЯ                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐     EXPORT (DB → GS)      ┌──────────────┐   │
│  │              │  ←───────────────────────  │              │   │
│  │   Google     │     code.gs вызывает      │   PostgreSQL │   │
│  │   Sheets     │     webhook /sync/export   │   Database   │   │
│  │              │  ───────────────────────→  │              │   │
│  └──────────────┘     IMPORT (GS → DB)      └──────────────┘   │
│                       команда &import                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Компоненты

| Файл | Назначение |
|------|------------|
| `code.gs` | Google Apps Script — PULL (DB → GS) |
| `sync_system/webhook_handler.py` | HTTP сервер `/sync/export` |
| `sync_system/sync_engine.py` | UniversalSyncEngine |
| `sync_system/sync_config.py` | SYNC_CONFIG — поля и валидаторы |

#### SYNC_CONFIG структура

```python
SYNC_CONFIG = {
    'Users': {
        'sheet_name': 'Users',
        'model': User,
        'primary_key': 'userID',
        
        'readonly_fields': [
            'userID', 'telegramID', 'createdAt',
            'balanceActive', 'balancePassive'
        ],
        
        'editable_fields': [
            'email', 'firstname', 'surname', 'upline', ...
        ],
        
        'export_updates': [
            'email', 'status', 'balanceActive', ...
        ],
        
        'foreign_keys': {
            'upline': ('Users', 'telegramID')
        },
        
        'field_validators': {
            'email': 'email',
            'upline': 'special_upliner'
        }
    },
    # ... Payments, Purchases, Bonuses, Transfers, ActiveBalance, PassiveBalance
}
```

#### Режимы импорта

| Режим | Описание | Commit | Валидация |
|-------|----------|--------|-----------|
| `dry` | Проверка без изменений | ❌ | ✅ Полная |
| `safe` | Импорт безопасных полей | ✅ | ✅ Полная |
| `force` | Полный импорт | ✅ | ⚠️ Минимальная |

#### Реализация &import

**Файл:** `handlers/admin/import_commands.py`

```python
@import_router.message(F.text.startswith('&import'))
async def cmd_import(message: Message, user: User, session: Session):
    """
    Импорт данных из Google Sheets в БД.
    
    Usage:
        &import --table Users --mode dry
        &import --table Users --mode safe
        &import --table Payments --mode force
        &import --all --mode safe
    
    Tables: Users, Payments, Purchases, Bonuses, Transfers, 
            ActiveBalance, PassiveBalance
    
    Modes:
        dry   - только анализ, без изменений
        safe  - импорт с валидацией
        force - импорт без валидации (требует подтверждения)
    """
```

#### Категории таблиц

```python
SUPPORT_TABLES = [
    'Users', 'Payments', 'Purchases', 'Bonuses', 
    'Transfers', 'ActiveBalance', 'PassiveBalance'
]

ADMIN_ONLY_TABLES = ['Projects', 'Options']  # Только через &upro
```

---

### 3.3 Команда &addbalance

#### Описание

Ручная корректировка баланса пользователя админом.

#### Синтаксис

```
&addbalance <user_id> <amount> [reason]
```

#### Примеры

```
&addbalance 123 500 "Компенсация за техническую ошибку"
&addbalance 456 -100 "Корректировка дубля"
```

#### Реализация

**Файл:** `handlers/admin/balance_commands.py`

```python
@balance_router.message(F.text.startswith('&addbalance'))
async def cmd_addbalance(message: Message, user: User, session: Session):
    """
    Ручная корректировка ActiveBalance.
    
    Flow:
    1. Парсинг аргументов (user_id, amount, reason)
    2. Поиск пользователя
    3. Создание ActiveBalance record (status='done')
    4. Обновление user.balanceActive
    5. Notification пользователю (если amount > 0)
    6. Лог действия
    """
```

---

## 4. PHASE 3: ADMIN ARCHITECTURE

> **Приоритет:** Рефакторинг для maintainability

### 4.1 Модульная структура

#### Текущая проблема

`handlers/admin.py` в Talentir — это ~400+ строк монолитного кода, с которым невозможно работать.

#### Новая структура

```
handlers/
├── admin/
│   ├── __init__.py              # Router + dispatcher
│   ├── config_commands.py       # &upconfig, &upro, &ut
│   ├── import_commands.py       # &import, &legacy
│   ├── payment_commands.py      # approve/reject callbacks
│   ├── balance_commands.py      # &addbalance, &delpurchase
│   ├── stats_commands.py        # &stats, &checkpayments
│   └── utils_commands.py        # &restore, &object, &help, &user
```

#### __init__.py — Точка входа

```python
"""
Admin commands module.
Single entry point with specialized sub-modules.
"""
from aiogram import Router

from .config_commands import config_router
from .import_commands import import_router
from .payment_commands import payment_router
from .balance_commands import balance_router
from .stats_commands import stats_router
from .utils_commands import utils_router

# Main admin router
admin_router = Router(name="admin")

# Include all sub-routers
admin_router.include_router(config_router)
admin_router.include_router(import_router)
admin_router.include_router(payment_router)
admin_router.include_router(balance_router)
admin_router.include_router(stats_router)
admin_router.include_router(utils_router)

__all__ = ['admin_router']
```

#### Общий паттерн для sub-router

```python
# handlers/admin/config_commands.py

from aiogram import Router, F
from aiogram.types import Message
from config import Config

config_router = Router(name="admin_config")


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    admins = Config.get(Config.ADMINS) or []
    return user_id in admins


@config_router.message(F.text == '&upconfig')
async def cmd_upconfig(message: Message, ...):
    if not is_admin(message.from_user.id):
        return
    # ... implementation
```

---

### 4.2 Полный список админских команд

#### Config Commands (`config_commands.py`)

| Команда | Описание | Статус |
|---------|----------|--------|
| `&upconfig` | Обновить Config из GS | ⚠️ Исправить |
| `&upro` | Обновить Projects + Options + BookStack | ❌ Добавить |
| `&ut` | Обновить шаблоны сообщений | ❌ Добавить |

#### Import Commands (`import_commands.py`)

| Команда | Описание | Статус |
|---------|----------|--------|
| `&import` | Синхронизация таблиц GS → DB | ❌ Добавить |
| `&legacy` | Ручной запуск legacy processor | ❌ Добавить |

#### Payment Commands (`payment_commands.py`)

| Callback/Команда | Описание | Статус |
|------------------|----------|--------|
| `approve_payment_{id}` | Первый шаг подтверждения | ❌ Добавить |
| `final_approve_{id}` | Финальное подтверждение | ❌ Добавить |
| `reject_payment_{id}` | Отклонение платежа | ❌ Добавить |
| `&checkpayments` | Проверка необработанных | ❌ Добавить |

#### Balance Commands (`balance_commands.py`)

| Команда | Описание | Статус |
|---------|----------|--------|
| `&addbalance` | Корректировка баланса | ❌ Добавить |
| `&delpurchase` | Удаление покупки с рефандом | ❌ Добавить |

#### Stats Commands (`stats_commands.py`)

| Команда | Описание | Статус |
|---------|----------|--------|
| `&stats` | Статистика бота | ✅ Есть |
| `&testmail` | Тест email провайдеров | ✅ Есть |

#### Utils Commands (`utils_commands.py`)

| Команда | Описание | Статус |
|---------|----------|--------|
| `&time` | Time Machine — управление виртуальным временем | ❌ Добавить |
| `&restore` | Бэкап/восстановление БД | ❌ Добавить |
| `&object` | Отправка объекта по file_id | ❌ Добавить |
| `&user` | Поиск пользователя | ❌ Добавить |
| `&help` | Справка по командам | ❌ Добавить |

---

## 5. PHASE 4: ОТЛОЖЕНО

### 5.1 Broadcast System

**Причина отложения:** Текущая реализация содержит костыли и hardcoded значения. Требуется полная переработка.

**Что нужно переделать:**
- Универсальная структура Recipients листа
- Конфигурируемые шаблоны (не hardcoded)
- Улучшенная обработка ошибок
- Dashboard для мониторинга

### 5.2 Loyalty Program (+10% JetUp Tokens)

**Причина отложения:** Пока нет (по решению заказчика).

**Текущий статус:**
- Grace Day streak tracking: ✅ Реализовано
- Награда за 3 месяца: ❌ Помечено "for future implementation"

---

## 6. ПРИЛОЖЕНИЯ

### 6.1 Система шаблонов — Две подсистемы

#### A. Google Sheets "Templates" — Сообщения бота

| Аспект | Значение |
|--------|----------|
| **Источник** | GS лист "Templates" |
| **Кеш** | `MessageTemplates._cache` |
| **Команда обновления** | `&ut` |
| **Использование** | Все тексты бота, кнопки, медиа |

**Структура записи:**

| Колонка | Описание |
|---------|----------|
| `stateKey` | Идентификатор шаблона |
| `lang` | Язык (en, ru) |
| `text` | Текст с плейсхолдерами `{variable}` |
| `buttons` | JSON кнопок |
| `parseMode` | HTML / Markdown |
| `disablePreview` | Флаг |
| `mediaType` | photo / video / document / None |
| `mediaID` | file_id в Telegram |
| `preAction` | Действие ДО отправки |
| `postAction` | Действие ПОСЛЕ отправки |

#### B. BookStack — PDF Документы

| Аспект | Значение |
|--------|----------|
| **Источник** | BookStack API |
| **Кеш** | `TemplateCache._cache` (TTL 10 мин) |
| **Команда очистки** | `&upro` (включает clear) |
| **Использование** | Purchase Agreement, Certificate |

---

### 6.2 Структура данных Autoship

```python
# user.settings['autoship']
{
    "enabled": bool,           # Включён ли autoship
    "amount": float,           # Сумма (или из Config)
    "attempts": int,           # Неудачных попыток в этом месяце
    "lastPurchaseDate": str,   # ISO date последней покупки
    "lastAttemptDate": str     # ISO date последней попытки
}
```

---

### 6.3 Notification Model — Правильные поля

```python
class Notification(Base):
    __tablename__ = 'notifications'
    
    notificationID = Column(Integer, primary_key=True)
    createdAt = Column(DateTime)
    
    source = Column(String)       # "payment_checker", "mlm_system", etc.
    text = Column(Text)
    buttons = Column(Text)        # JSON
    
    targetType = Column(String)   # "user", "broadcast"
    targetValue = Column(String)  # userID или criteria
    
    priority = Column(Integer)    # 1-10
    category = Column(String)     # "payment", "mlm", "legacy"
    importance = Column(String)   # "critical", "high", "normal", "low"
    
    status = Column(String)       # "pending", "sent", "failed"
    sentAt = Column(DateTime)
    failureReason = Column(Text)
    retryCount = Column(Integer)
    
    parseMode = Column(String)    # "HTML", "Markdown"
    disablePreview = Column(Boolean)
    
    expiryAt = Column(DateTime)
    silent = Column(Boolean)
    autoDelete = Column(Integer)  # Seconds
```

---

### 6.4 Checklist перед запуском

#### PHASE 1 (блокеры):
- [ ] Payment Approval handlers добавлены
- [ ] &upconfig исправлен (только Config)
- [ ] &upro добавлен (Projects + Options + BookStack)
- [ ] &ut добавлен (Templates)
- [ ] Notification fields исправлены на camelCase
- [ ] **Active Partners count исправлен (по всей структуре)**
- [ ] Autoship реализован

#### PHASE 2 (первые недели):
- [ ] Legacy Processor верифицирован
- [ ] &import добавлен
- [ ] &addbalance добавлен
- [ ] &legacy добавлен
- [ ] **&time добавлен (Time Machine для тестирования)**

#### PHASE 3 (рефакторинг):
- [ ] Admin handlers разбиты на модули
- [ ] &delpurchase добавлен
- [ ] &checkpayments добавлен
- [ ] &restore добавлен
- [ ] &user добавлен
- [ ] &help добавлен

---

## 7. ИСТОРИЯ ИЗМЕНЕНИЙ

| Версия | Дата | Изменения |
|--------|------|-----------|
| 1.0 | 27.11.2025 | Первоначальная версия |

---

*Документ подготовлен на основе аудита кодовой базы Talentir и jetup-2*
