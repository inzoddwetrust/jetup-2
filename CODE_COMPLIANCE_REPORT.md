# ОТЧЕТ О СООТВЕТСТВИИ КОДА ТЗ МАРКЕТИНГОВОЙ СИСТЕМЫ JETUP

**Дата анализа**: 2025-10-21
**Версия кода**: commit 55b1430

---

## РЕЗЮМЕ

На основе анализа кода выявлены следующие **критические несоответствия ТЗ**:

### ✅ РЕАЛИЗОВАНО КОРРЕКТНО (8/14)
1. Система рангов с корректными процентами
2. Дифференциальные комиссии
3. Compression (сжатие) при неактивных партнерах
4. Pioneer Bonus механизм
5. Referral Bonus (1% за приглашение ≥5000$)
6. Global Pool расчет и распределение
7. Назначение рангов основателями
8. Time Machine для Grace Day

### ❌ КРИТИЧЕСКИЕ ПРОБЛЕМЫ (6/14)
1. **ПРАВИЛО 50% НЕ РЕАЛИЗОВАНО** - самая критическая проблема
2. Инвестиционные пакеты с бонусами не найдены
3. Grace Day бонусы (+5% опционов) не реализованы
4. Программа лояльности (3 месяца → +10% токенов) отсутствует
5. Autoship система не реализована
6. Подсчет активных партнеров только на уровне 1 (должен быть по всей структуре)

---

## ДЕТАЛЬНЫЙ АНАЛИЗ ПО РАЗДЕЛАМ ТЗ

### 1. ОСНОВНЫЕ ПРИНЦИПЫ ✅ ЧАСТИЧНО

#### ✅ Реализовано:
- **Минимальный PV 200$**: `mlm_system/config/ranks.py:51`
  ```python
  MINIMUM_PV = Decimal("200")
  ```

- **Проверка активности**: `mlm_system/services/volume_service.py:53-57`
  ```python
  monthlyPv = Decimal(user.mlmVolumes["monthlyPV"])
  if monthlyPv >= Decimal("200"):
      user.isActive = True
  ```

- **Сохранение достигнутого ранга**: `models/user.py:41`
  ```python
  rank = Column(String, default="start", index=True)
  ```

#### ❌ КРИТИЧЕСКАЯ ПРОБЛЕМА: **ПРАВИЛО 50% НЕ РЕАЛИЗОВАНО**

**Локация**: `mlm_system/services/rank_service.py:50-68`

**Текущая реализация**:
```python
async def _isQualifiedForRank(self, user: User, rank: str) -> bool:
    # Check team volume
    teamVolume = user.teamVolumeTotal or Decimal("0")
    if teamVolume < requirements["teamVolumeRequired"]:
        return False
    # ❌ НЕТ ПРОВЕРКИ ПРАВИЛА 50%!
```

**Должно быть**:
```python
# 1. Получить все ветки (первый уровень)
branches = await volumeService.getBestBranches(userId, count=999)

# 2. Найти самую большую ветку
maxBranchVolume = max(b["volume"] for b in branches) if branches else 0

# 3. Применить правило 50%
cappedMaxBranch = min(maxBranchVolume, requiredTV * 0.5)

# 4. Суммировать остальные ветки + capped максимальная
qualifyingTV = cappedMaxBranch + sum(b["volume"] for b in other_branches)

# 5. Проверить квалификацию
if qualifyingTV >= requiredTV:
    # Квалифицирован
```

**Пример из ТЗ**:
- Требуемый TV для ранга: 250.000$
- Ветка A: 150.000$ (60% от TV) ❌ Превышает лимит 50%
- Ветка B: 50.000$ (20%)
- Ветка C: 50.000$ (20%)
- **Результат**: Только 125.000$ (50%) из ветки A засчитываются = Общий TV только 225.000$ ❌ НЕ КВАЛИФИЦИРОВАН

**Без этого правила система может эксплуатироваться!**

---

### 2. СИСТЕМА ДИФФЕРЕНЦИАЛЬНЫХ КОМИССИЙ ✅ РЕАЛИЗОВАНО КОРРЕКТНО

#### ✅ Корректная реализация:

**Конфигурация рангов**: `mlm_system/config/ranks.py:17-48`
```python
RANK_CONFIG = {
    Rank.START: {"percentage": Decimal("0.04"), ...},      # 4% ✅
    Rank.BUILDER: {"percentage": Decimal("0.08"), ...},    # 8% ✅
    Rank.GROWTH: {"percentage": Decimal("0.12"), ...},     # 12% ✅
    Rank.LEADERSHIP: {"percentage": Decimal("0.15"), ...}, # 15% ✅
    Rank.DIRECTOR: {"percentage": Decimal("0.18"), ...}    # 18% ✅
}
```

**Расчет дифференциала**: `mlm_system/services/commission_service.py:77-135`
```python
async def _calculateDifferentialCommissions(self, purchase: Purchase):
    lastPercentage = Decimal("0")
    while currentUser.upline:
        userPercentage = self._getUserRankPercentage(uplineUser)
        differential = userPercentage - lastPercentage  # ✅ Корректно
        if differential > 0:
            amount = purchase.packPrice * differential
```

**Compression (сжатие)**: `mlm_system/services/commission_service.py:137-164`
```python
async def _applyCompression(self, commissions, purchase):
    pendingCompression = Decimal("0")
    for commission in commissions:
        if not commission["isActive"]:
            pendingCompression += commission["percentage"]  # ✅ Накопление
        else:
            totalPercentage = commission["percentage"] + pendingCompression
            # ✅ Передается следующему активному
```

---

### 3. ИНВЕСТИЦИОННЫЕ ПАКЕТЫ ❌ НЕ НАЙДЕНЫ

#### ❌ Проблема: Конфигурация пакетов с бонусами отсутствует

**Ожидалось по ТЗ**:
```python
INVESTMENT_PACKAGES = {
    "starter": {"price": 200, "bonus_percent": 0.00, "total_options": 200},
    "basic": {"price": 1000, "bonus_percent": 0.05, "total_options": 1050},
    "professional": {"price": 5000, "bonus_percent": 0.10, "total_options": 5500},
    "premium": {"price": 25000, "bonus_percent": 0.15, "total_options": 28750},
    "vip": {"price": 125000, "bonus_percent": 0.20, "total_options": 150000}
}
```

**Найдено**: `models/option.py`
- Есть базовая модель Option, но **нет бонусной логики при покупке**
- Нет начисления дополнительных опционов

**Требуется**: Добавить логику начисления бонусных опционов при покупке пакетов.

---

### 4. AUTOSHIP И GRACE DAY ❌ ЧАСТИЧНО РЕАЛИЗОВАНО

#### ✅ Grace Day определение работает:
`mlm_system/utils/time_machine.py:37-39`
```python
@property
def isGraceDay(self) -> bool:
    return self.now.day == 1  # ✅
```

`background/mlm_scheduler.py:201-222`
```python
async def processGraceDay(self, session):
    activeUsers = session.query(User).filter(
        User.isActive == True,
        User.lastActiveMonth == timeMachine.currentMonth
    ).all()
    # ✅ Находит пользователей, активированных 1-го числа
```

#### ❌ НЕ РЕАЛИЗОВАНО:

1. **Бонус +5% опционов за оплату 1-го числа**
   - ТЗ: "200$ → 210$ опционов"
   - **Не найдено в коде**

2. **Ретроактивный зачет транзакций**
   - ТЗ: "Оплата до 23:59 первого числа = все транзакции дня засчитываются ретроактивно"
   - **Не реализовано**

3. **Программа лояльности (3 месяца подряд)**
   - ТЗ: "3 месяца подряд оплата 1-го числа = +10% в токенах JetUp (20$ ежемесячно)"
   - **Полностью отсутствует**
   - Нужен счетчик последовательных Grace Day активаций

4. **Autoship система**
   - ТЗ: "Автоматическая ежемесячная покупка на 200$"
   - **Отсутствует**
   - Есть поле в JSON: `user.mlmVolumes["autoship"]`, но логика не реализована

**Требуется**:
```python
# В mlm_scheduler.py, executeFirstOfMonthTasks():

# 1. Проверить autoship для пользователей
for user in all_users:
    if user.mlmVolumes.get("autoship", {}).get("enabled"):
        # Автоматическое списание и покупка

# 2. Бонус за Grace Day
if purchase_date.day == 1:
    bonus_options = purchase_amount * Decimal("0.05")

# 3. Программа лояльности
grace_day_streak = user.mlmStatus.get("graceDayStreak", 0)
if grace_day_streak >= 3:
    jetup_tokens = Decimal("20")
```

---

### 5. ДОПОЛНИТЕЛЬНЫЕ БОНУСЫ ✅ РЕАЛИЗОВАНО

#### ✅ Pioneer Bonus (+4%):
`mlm_system/config/ranks.py:52`
```python
PIONEER_BONUS_PERCENTAGE = Decimal("0.04")  # ✅
```

`mlm_system/services/commission_service.py:174-202`
```python
async def _applyPioneerBonus(self, commissions, purchase):
    if user.mlmStatus.get("hasPioneerBonus", False):
        pioneerAmount = purchase.packPrice * PIONEER_BONUS_PERCENTAGE
        commission["amount"] += pioneerAmount  # ✅
```

#### ✅ Referral Bonus (1%):
`mlm_system/config/ranks.py:53-54`
```python
REFERRAL_BONUS_PERCENTAGE = Decimal("0.01")  # ✅
REFERRAL_BONUS_MIN_AMOUNT = Decimal("5000")  # ✅
```

`mlm_system/services/commission_service.py:270-330`
```python
async def processReferralBonus(self, purchase):
    if purchase.packPrice < REFERRAL_BONUS_MIN_AMOUNT:
        return None  # ✅ Проверка минимума
    bonusAmount = purchase.packPrice * REFERRAL_BONUS_PERCENTAGE  # ✅
```

#### ⚠️ Неясности по ТЗ:
- **Pioneer Bonus**: ТЗ не уточняет, это разовая выплата или постоянная надбавка
- **Первые 50**: По всей компании или в структуре партнера?
- Константа `PIONEER_MAX_COUNT = 50` есть, но логика подсчета не реализована

---

### 6. GLOBAL POOL ✅ РЕАЛИЗОВАНО КОРРЕКТНО

#### ✅ Расчет 2% от оборота:
`mlm_system/services/global_pool_service.py:47-50`
```python
totalVolume = await self._calculateCompanyMonthlyVolume()
poolSize = totalVolume * GLOBAL_POOL_PERCENTAGE  # 2% ✅
```

#### ✅ Квалификация (2 Директора в разных ветках):
`mlm_system/services/global_pool_service.py:132-149`
```python
async def _checkGlobalPoolQualification(self, user):
    branches = await self.volumeService.getBestBranches(user.userID, 2)
    directorsCount = sum(1 for b in branches if b.get("hasDirector"))
    return directorsCount >= 2  # ✅
```

#### ✅ Распределение поровну:
`mlm_system/services/global_pool_service.py:56-59`
```python
if qualifiedCount > 0:
    perUserAmount = poolSize / qualifiedCount  # ✅ Поровну
```

#### ⚠️ Потенциальная проблема:
ТЗ: "Директора должны быть на первом уровне или могут быть глубже в структуре?"
- Код проверяет наличие Директора **где угодно в ветке** (рекурсивно)
- ТЗ: "Если я приглашаю тебя и Алекса - это две ветки. Если довожу обоих до Директора"
- **Вероятно корректно**, но требует уточнения

---

### 7. НАЗНАЧЕНИЕ РАНГОВ ОСНОВАТЕЛЯМИ ✅ РЕАЛИЗОВАНО

`mlm_system/services/rank_service.py:113-153`
```python
async def assignRankByFounder(self, userId, newRank, founderId):
    if not founder.mlmStatus.get("isFounder", False):
        logger.error(f"User {founderId} is not a founder")
        return False  # ✅ Проверка прав

    user.rank = newRank
    user.assignedRank = newRank  # ✅ Сохранение назначенного ранга
```

`mlm_system/services/rank_service.py:165-167`
```python
async def getUserActiveRank(self, userId):
    if user.assignedRank:
        return user.assignedRank  # ✅ Приоритет назначенному
```

---

### 8. ПОДСЧЕТ АКТИВНЫХ ПАРТНЕРОВ ❌ ОШИБКА

#### ❌ ПРОБЛЕМА: Подсчет только на уровне 1
`mlm_system/services/rank_service.py:70-78`
```python
async def _countActivePartners(self, user: User) -> int:
    activeCount = self.session.query(func.count(User.userID)).filter(
        User.upline == user.telegramID,  # ❌ Только прямые рефералы!
        User.isActive == True
    ).scalar()
```

#### ТЗ неоднозначен:
> ❓ "Активные партнёры должны быть на первом уровне или могут быть во всей структуре?"

**Интерпретация A** (текущая реализация): Только уровень 1
- Проще
- Стимулирует личное приглашение

**Интерпретация B** (по всей структуре):
- Логичнее для командного объема
- Более справедливо для больших структур

**Рекомендация**: Уточнить в ТЗ. Вероятно, должен быть **по всей структуре**, аналогично TV.

---

## СВОДНАЯ ТАБЛИЦА СООТВЕТСТВИЯ

| № | Функция | Статус | Критичность | Файл |
|---|---------|--------|-------------|------|
| 1 | Минимальный PV 200$ | ✅ | Высокая | ranks.py:51 |
| 2 | Система рангов | ✅ | Высокая | ranks.py:17-48 |
| 3 | Дифференциальные комиссии | ✅ | Высокая | commission_service.py:77-135 |
| 4 | **Правило 50%** | ❌ | **КРИТИЧЕСКАЯ** | rank_service.py:50-68 |
| 5 | Compression | ✅ | Средняя | commission_service.py:137-164 |
| 6 | **Инвестиционные пакеты с бонусами** | ❌ | **Высокая** | - |
| 7 | **Grace Day бонус +5%** | ❌ | **Высокая** | - |
| 8 | **Программа лояльности 3 месяца** | ❌ | **Средняя** | - |
| 9 | **Autoship** | ❌ | **Средняя** | - |
| 10 | Pioneer Bonus | ✅ | Средняя | commission_service.py:174-202 |
| 11 | Referral Bonus | ✅ | Средняя | commission_service.py:270-330 |
| 12 | Global Pool | ✅ | Средняя | global_pool_service.py |
| 13 | Назначение рангов | ✅ | Низкая | rank_service.py:113-153 |
| 14 | **Подсчет активных партнеров** | ⚠️ | **Средняя** | rank_service.py:70-78 |

---

## КРИТИЧЕСКИЕ РИСКИ

### 🔴 ВЫСОКИЙ РИСК: Отсутствие правила 50%

**Сценарий эксплуатации**:
1. Партнер создает одну "супер-ветку" с TV = 5.000.000$
2. Без правила 50% он квалифицируется на ранг "Директор"
3. **С правилом 50%**: максимум 2.500.000$ из этой ветки → НЕ квалифицирован

**Финансовые последствия**:
- Неконтролируемая выплата высоких комиссий
- Дисбаланс структуры
- Демотивация построения нескольких веток

### 🟡 СРЕДНИЙ РИСК: Отсутствие бонусов за пакеты

**Последствия**:
- Партнеры не получают обещанные бонусы
- Нарушение обязательств по ТЗ
- Демотивация покупок больших пакетов

### 🟡 СРЕДНИЙ РИСК: Autoship не реализован

**Последствия**:
- Ручная активация каждый месяц
- Потеря пассивных партнеров
- Снижение ретеншна

---

## РЕКОМЕНДАЦИИ ПО ПРИОРИТЕТАМ

### 🔥 КРИТИЧЕСКИЙ ПРИОРИТЕТ (НЕМЕДЛЕННО):
1. **Реализовать правило 50% для TV**
   - Файл: `rank_service.py`, метод `_isQualifiedForRank`
   - Время: 2-3 часа
   - Тестирование: обязательно

### 🔴 ВЫСОКИЙ ПРИОРИТЕТ (В ТЕЧЕНИЕ НЕДЕЛИ):
2. **Добавить бонусы за инвестиционные пакеты**
   - Создать конфигурацию пакетов
   - Логика начисления опционов
   - Время: 4-6 часов

3. **Реализовать Grace Day бонус +5%**
   - Проверка даты покупки
   - Начисление дополнительных опционов
   - Время: 2-3 часа

### 🟡 СРЕДНИЙ ПРИОРИТЕТ (В ТЕЧЕНИЕ МЕСЯЦА):
4. **Программа лояльности 3 месяца**
   - Счетчик последовательных активаций
   - Начисление JetUp токенов
   - Время: 3-4 часа

5. **Autoship система**
   - Автоматическое списание
   - Обработка ошибок
   - Время: 6-8 часов

6. **Уточнить подсчет активных партнеров**
   - Связаться с заказчиком
   - Уточнить: уровень 1 или вся структура?
   - При необходимости переписать `_countActivePartners`

---

## ВОПРОСЫ ДЛЯ УТОЧНЕНИЯ У ЗАКАЗЧИКА

1. **Правило 50%**: Подтвердить необходимость реализации
2. **Активные партнеры**: Только Level 1 или вся структура?
3. **Pioneer Bonus**: Разовая выплата или постоянная надбавка?
4. **Первые 50**: По всей компании или в структуре каждого партнера?
5. **TV**: Считается за текущий месяц или накопительно?
6. **Включение PV в TV**: Входит ли собственный PV в расчет Team Volume?
7. **Global Pool Директора**: Должны быть на Level 1 или могут быть глубже?

---

## ЗАКЛЮЧЕНИЕ

**Общая оценка соответствия ТЗ: 57% (8 из 14 функций реализованы корректно)**

**Критические блокеры для продакшена**:
1. ❌ Правило 50% (КРИТИЧНО!)
2. ❌ Бонусы за пакеты
3. ❌ Grace Day бонус

**Код хорошо структурирован**, использует современные практики (async/await, dependency injection, event bus), но **не реализованы ключевые бизнес-требования**.

**Рекомендация**: НЕ ЗАПУСКАТЬ в продакшен до исправления критических проблем.

---

**Анализ проведен**: Claude AI
**Контакт для вопросов**: см. issue tracker проекта
