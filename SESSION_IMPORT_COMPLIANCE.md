# Session Import Compliance Analysis

**Date**: 2025-10-31
**Status**: 🔥 **CRITICAL - CODE IS BROKEN**
**Purpose**: Analyze correct usage of database Session imports across the codebase

---

## Executive Summary

### 🚨 CRITICAL ISSUE: NON-EXISTENT MODULE IMPORT

**5 files import from non-existent module `init`**:
- `from init import Session` - **FILE init.py DOES NOT EXIST!**

**Impact**: These files will **FAIL AT RUNTIME** with `ModuleNotFoundError: No module named 'init'`

**Overall Compliance**: ❌ **78%** (18/23 files correct)

---

## The Problem

### Files with Broken Imports

```python
# ❌ BROKEN - init.py does not exist!
from init import Session

with Session() as session:  # This will NEVER work!
    # ...
```

**5 affected files**:
1. `background/legacy_processor.py:11`
2. `background/mlm_scheduler.py:19`
3. `sync_system/config_importer.py:13`
4. `sync_system/webhook_handler.py:18`
5. `sync_system/sync_engine.py:220` (inside function)

---

## Correct Session Usage Patterns

### Pattern 1: Type Hints (for aiogram handlers)

**Usage**: Import `Session` class for type annotations only

```python
from sqlalchemy.orm import Session

async def my_handler(
    callback_query: CallbackQuery,
    session: Session,  # ✅ Type hint only
    user: User
):
    # Session is injected by UserMiddleware
    # Don't create session here!
    user_data = session.query(User).filter_by(userID=123).first()
```

**Files using this pattern** (18 files - ✅ CORRECT):
- All handlers: `handlers/*.py` (10 files)
- All MLM services: `mlm_system/services/*.py` (4 files)
- Document services: `services/document/*.py` (2 files)
- Auth service: `services/user_domain/auth_service.py`
- Sync engine: `sync_system/sync_engine.py`

**How it works**:
- `UserMiddleware` (in `core/user_decorator.py`) creates session via `get_session()`
- Session is automatically injected into handler parameters
- Session is auto-committed and closed after handler execution

---

### Pattern 2: Context Manager (for background tasks)

**Usage**: Use `get_db_session_ctx()` for automatic commit/rollback/close

```python
from core.db import get_db_session_ctx

# ✅ CORRECT - automatic transaction management
with get_db_session_ctx() as session:
    user = session.query(User).first()
    user.balance += 100
    # Automatically commits on success, rolls back on exception, closes always
```

**Advantages**:
- ✅ Auto-commit on success
- ✅ Auto-rollback on exception
- ✅ Auto-close in finally block
- ✅ No manual error handling needed

**Should be used in** (5 files that need fixing):
- `background/legacy_processor.py`
- `background/mlm_scheduler.py`
- `sync_system/config_importer.py`
- `sync_system/webhook_handler.py`
- `sync_system/sync_engine.py`

---

### Pattern 3: Manual Session Management

**Usage**: Use `get_session()` when you need fine-grained control

```python
from core.db import get_session

# ✅ CORRECT - manual control
session = get_session()
try:
    user = session.query(User).first()
    user.balance += 100
    session.commit()
except Exception as e:
    session.rollback()
    raise
finally:
    session.close()
```

**When to use**:
- Need multiple commits in one function
- Complex transaction logic
- Need to handle specific exceptions differently

**Currently used in** (1 file):
- `core/user_decorator.py` (middleware - correct usage)

---

## Files Currently Using BROKEN Import

### ❌ 1. background/legacy_processor.py

**Line 11**:
```python
from init import Session  # ❌ BROKEN!
```

**Usage locations** (4 places):
```python
# Line 286
with Session() as session:
    for legacy_user in batch:
        # ...

# Line 625, 657, 681
with Session() as session:
    session.add(notification)
    session.commit()
```

**Fix**:
```python
# Replace line 11:
from core.db import get_db_session_ctx

# Replace all 4 usages:
with get_db_session_ctx() as session:
    # ... same code
```

---

### ❌ 2. background/mlm_scheduler.py

**Line 19**:
```python
from init import Session  # ❌ BROKEN!
```

**Usage locations** (4 places):
```python
# Lines 99, 126, 154, 178
with Session() as session:
    try:
        # ... MLM tasks
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Error: {e}")
```

**Fix**:
```python
# Replace line 19:
from core.db import get_db_session_ctx

# Replace all 4 usages:
with get_db_session_ctx() as session:
    # ... same code (remove manual commit/rollback, it's automatic)
```

---

### ❌ 3. sync_system/config_importer.py

**Line 13**:
```python
from init import Session  # ❌ BROKEN!
```

**Usage locations** (2 places):
```python
# Lines 103, 163
with Session() as session:
    for idx, row in enumerate(rows, start=2):
        # ... process config
        session.commit()
```

**Fix**:
```python
# Replace line 13:
from core.db import get_db_session_ctx

# Replace all 2 usages:
with get_db_session_ctx() as session:
    # ... same code (remove manual commit)
```

---

### ❌ 4. sync_system/webhook_handler.py

**Line 18**:
```python
from init import Session  # ❌ BROKEN!
```

**Usage locations** (2 places):
```python
# Line 280
with Session() as session:
    notification = Notification(...)
    session.add(notification)
    session.commit()

# Line 466
with Session() as session:
    engine = UniversalSyncEngine(table_name)
    result = engine.export_to_json(session)
```

**Fix**:
```python
# Replace line 18:
from core.db import get_db_session_ctx

# Replace all 2 usages:
with get_db_session_ctx() as session:
    # ... same code (remove manual commit)
```

---

### ❌ 5. sync_system/sync_engine.py

**Line 11** (for type hints - ✅ CORRECT):
```python
from sqlalchemy.orm import Session  # ✅ OK for type hints
```

**Line 220** (inside function - ❌ BROKEN):
```python
def export_to_json(self, session: Session = None) -> Dict:
    """Export table data to JSON."""
    if session is None:
        from init import Session  # ❌ BROKEN!
        session = Session()
```

**Fix**:
```python
def export_to_json(self, session: Session = None) -> Dict:
    """Export table data to JSON."""
    if session is None:
        from core.db import get_session
        session = get_session()
        # Note: caller is responsible for closing!
```

**Better fix** (use context manager):
```python
def export_to_json(self, session: Session = None) -> Dict:
    """Export table data to JSON."""
    close_session = False
    if session is None:
        from core.db import get_session
        session = get_session()
        close_session = True

    try:
        # ... export logic
        return result
    finally:
        if close_session:
            session.close()
```

---

## Database Architecture

### core/db.py - The Source of Truth

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Global engine and session factory
_engine = None
_SessionFactory = None

def get_engine():
    """Get or create database engine."""
    global _engine
    if _engine is None:
        database_url = Config.get(Config.DATABASE_URL, "sqlite:///jetup.db")
        _engine = create_engine(database_url, echo=False, pool_pre_ping=True)
    return _engine

def get_session_factory():
    """Get or create session factory."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine())
    return _SessionFactory

def get_session() -> Session:
    """Get a new database session (caller must close!)."""
    factory = get_session_factory()
    return factory()

@contextmanager
def get_db_session_ctx():
    """Context manager for database sessions (auto commit/rollback/close)."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        session.close()
```

---

### core/user_decorator.py - Aiogram Middleware

```python
from core.db import get_session

class UserMiddleware(BaseMiddleware):
    """Injects user and session into aiogram handlers."""

    async def __call__(self, handler, event, data):
        session = get_session()  # Create new session
        try:
            user = session.query(User).filter_by(telegramID=...).first()
            data['user'] = user
            data['session'] = session  # Inject into handler

            result = await handler(event, data)  # Call handler

            session.commit()  # Auto-commit on success
            return result
        except Exception as e:
            session.rollback()  # Auto-rollback on error
            raise
        finally:
            session.close()  # Always close
```

---

## Summary Table

| File | Import | Pattern | Status | Fix Required |
|------|--------|---------|--------|--------------|
| handlers/*.py (10 files) | `sqlalchemy.orm.Session` | Type hints | ✅ GOOD | No |
| mlm_system/services/*.py (4 files) | `sqlalchemy.orm.Session` | Type hints | ✅ GOOD | No |
| services/document/*.py (2 files) | `sqlalchemy.orm.Session` | Type hints | ✅ GOOD | No |
| services/user_domain/auth_service.py | `sqlalchemy.orm.Session` | Type hints | ✅ GOOD | No |
| sync_system/sync_engine.py | `sqlalchemy.orm.Session` | Type hints | ✅ GOOD | No |
| core/user_decorator.py | `core.db.get_session` | Manual | ✅ GOOD | No |
| **background/legacy_processor.py** | **init.Session** | **BROKEN** | ❌ **CRITICAL** | **YES** |
| **background/mlm_scheduler.py** | **init.Session** | **BROKEN** | ❌ **CRITICAL** | **YES** |
| **sync_system/config_importer.py** | **init.Session** | **BROKEN** | ❌ **CRITICAL** | **YES** |
| **sync_system/webhook_handler.py** | **init.Session** | **BROKEN** | ❌ **CRITICAL** | **YES** |
| **sync_system/sync_engine.py:220** | **init.Session** | **BROKEN** | ❌ **CRITICAL** | **YES** |

**Statistics**:
- Total files with Session imports: **23**
- ✅ Correct: **18** (78%)
- ❌ Broken: **5** (22%)

---

## Required Fixes (All High Priority)

### Fix 1: background/legacy_processor.py

```diff
- from init import Session
+ from core.db import get_db_session_ctx

  # ... (4 locations)
- with Session() as session:
+ with get_db_session_ctx() as session:
      # ... same code
-     session.commit()  # Remove - auto-committed
```

**Lines to change**: 11, 286, 625, 657, 681

---

### Fix 2: background/mlm_scheduler.py

```diff
- from init import Session
+ from core.db import get_db_session_ctx

  # ... (4 locations)
- with Session() as session:
+ with get_db_session_ctx() as session:
      try:
          # ... same code
-         session.commit()  # Remove - auto-committed
      except Exception as e:
-         session.rollback()  # Remove - auto-rollback
          logger.error(f"Error: {e}")
```

**Lines to change**: 19, 99-111, 126-138, 154-166, 178-190

---

### Fix 3: sync_system/config_importer.py

```diff
- from init import Session
+ from core.db import get_db_session_ctx

  # ... (2 locations)
- with Session() as session:
+ with get_db_session_ctx() as session:
      for idx, row in enumerate(rows, start=2):
          # ... same code
-     session.commit()  # Remove - auto-committed
```

**Lines to change**: 13, 103-112, 163-172

---

### Fix 4: sync_system/webhook_handler.py

```diff
- from init import Session
+ from core.db import get_db_session_ctx

  # Location 1 (line 280)
- with Session() as session:
+ with get_db_session_ctx() as session:
      notification = Notification(...)
      session.add(notification)
-     session.commit()  # Remove - auto-committed

  # Location 2 (line 466)
- with Session() as session:
+ with get_db_session_ctx() as session:
      engine = UniversalSyncEngine(table_name)
      result = engine.export_to_json(session)
```

**Lines to change**: 18, 280-293, 466-468

---

### Fix 5: sync_system/sync_engine.py

```diff
  def export_to_json(self, session: Session = None) -> Dict:
      """Export table data to JSON."""
+     close_session = False
      if session is None:
-         from init import Session
+         from core.db import get_session
-         session = Session()
+         session = get_session()
+         close_session = True

      try:
          # ... export logic
          return result
+     finally:
+         if close_session:
+             session.close()
```

**Lines to change**: 218-222

---

## Testing Recommendations

### Test 1: Import Test

```python
def test_all_imports():
    """Verify all Session imports work."""
    try:
        # This should work
        from sqlalchemy.orm import Session
        from core.db import get_session, get_db_session_ctx

        # This should FAIL
        from init import Session
        assert False, "init.Session should not exist!"
    except ModuleNotFoundError:
        pass  # Expected
```

### Test 2: Session Context Manager Test

```python
def test_session_context_manager():
    """Test get_db_session_ctx works correctly."""
    from core.db import get_db_session_ctx
    from models.user import User

    # Success case - should commit
    with get_db_session_ctx() as session:
        user = session.query(User).first()
        if user:
            user.firstname = "Test"
        # Auto-commits here

    # Error case - should rollback
    try:
        with get_db_session_ctx() as session:
            user = session.query(User).first()
            user.firstname = "Test"
            raise ValueError("Test error")
    except ValueError:
        pass  # Should rollback

    # Verify rollback worked
    with get_db_session_ctx() as session:
        user = session.query(User).first()
        assert user.firstname != "Test"
```

### Test 3: Background Process Test

```python
async def test_background_processes():
    """Test that background processes can create sessions."""
    from background.mlm_scheduler import MLMScheduler
    from background.legacy_processor import LegacyUserProcessor

    # Should not raise ModuleNotFoundError
    scheduler = MLMScheduler()
    processor = LegacyUserProcessor()

    # Should be able to run without errors
    # (after fixes are applied)
```

---

## Why This Happened

**Probable scenario**:

1. Original code had `init.py` with Session factory
2. Refactoring created `core/db.py` with proper session management
3. Handlers were updated to use `sqlalchemy.orm.Session` (type hints only)
4. Background processes were NOT updated - still import from `init`
5. Someone deleted `init.py` thinking it was unused
6. Background processes became broken (but maybe not run frequently in dev?)

**Evidence**:
- Handlers use modern pattern (dependency injection)
- Background processes use old pattern (direct Session creation)
- `core/db.py` has proper session management functions
- `init.py` doesn't exist but is still imported in 5 places

---

## Migration Plan

### Phase 1: Fix Imports (15 minutes)

1. Replace `from init import Session` with `from core.db import get_db_session_ctx` in 4 files
2. Fix `sync_engine.py` special case (conditional import)

### Phase 2: Update Usage (30 minutes)

1. Replace `with Session() as session:` with `with get_db_session_ctx() as session:`
2. Remove manual `session.commit()` calls (auto-committed)
3. Remove manual `session.rollback()` calls (auto-rollback on exception)

### Phase 3: Testing (30 minutes)

1. Run background processes (legacy processor, MLM scheduler, etc.)
2. Verify no `ModuleNotFoundError`
3. Verify database operations work correctly
4. Check logs for any session-related errors

### Phase 4: Cleanup (15 minutes)

1. Search for any remaining `init` imports
2. Add test to prevent `from init import` in future
3. Update documentation

**Total estimated time**: 1.5 hours

---

## Best Practices Going Forward

### For Aiogram Handlers

```python
from sqlalchemy.orm import Session  # For type hints only!

@router.callback_query(F.data == "something")
async def my_handler(
    callback_query: CallbackQuery,
    session: Session,  # Injected by middleware
    user: User         # Injected by middleware
):
    # Just use session - don't create, commit, or close
    data = session.query(Model).all()
    # ...
```

### For Background Processes

```python
from core.db import get_db_session_ctx  # Context manager

async def my_background_task():
    with get_db_session_ctx() as session:
        # Do database work
        # Auto-commits on success, auto-rollback on exception
        pass
```

### For Services/Utilities

```python
from sqlalchemy.orm import Session  # For type hints

def my_service_function(session: Session, user_id: int):
    # Session is passed in - caller manages lifecycle
    user = session.query(User).filter_by(userID=user_id).first()
    return user
```

### DON'T DO THIS

```python
# ❌ WRONG - init doesn't exist
from init import Session

# ❌ WRONG - creates session but doesn't close
from core.db import get_session
session = get_session()
# ... use session ...
# Forgot to close!

# ❌ WRONG - imports Session class and tries to instantiate
from sqlalchemy.orm import Session
session = Session()  # This won't work! Need sessionmaker.
```

---

## Conclusion

### 🚨 Critical Issues

**5 files import from non-existent module** → **CODE IS BROKEN**

All 5 files will fail at runtime with:
```
ModuleNotFoundError: No module named 'init'
```

**Affected functionality**:
- ❌ Legacy user migration (background/legacy_processor.py)
- ❌ MLM monthly tasks (background/mlm_scheduler.py)
- ❌ Config import from Google Sheets (sync_system/config_importer.py)
- ❌ Webhook security notifications (sync_system/webhook_handler.py)
- ❌ Data export to Google Sheets (sync_system/sync_engine.py)

### Priority: 🔥 URGENT

These are critical background processes. If they're not running, it may not be immediately obvious, but:
- Legacy users won't be migrated
- MLM tasks won't execute on schedule
- Config won't sync from Google Sheets
- Security alerts won't be sent
- Data export will fail

### Recommendation

**Fix immediately** - estimated 1.5 hours total

All fixes are straightforward:
- Replace import statement
- Replace context manager usage
- Remove manual commit/rollback (now automatic)

After fixing, test all background processes to ensure they work correctly.

---

**Next Steps**:
1. Apply fixes from this document
2. Test each background process
3. Add integration test to catch future import errors
4. Document proper Session usage patterns
