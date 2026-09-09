# ТЗ: задачі в Google Календарі

Технічне завдання для агента, який працює в цьому репозиторії. Самодостатнє:
все потрібне про наші домовленості й пастки — нижче.

**Мета.** Задачі з нашого сервісу мають бути видні у Google Календарі власника
й на телефоні, а позначка «виконано» в Google має повертатися до нас.

---

## Рішення: Google Tasks, а не події календаря

Google Tasks відображаються **всередині Google Calendar** окремим шаром і
мають рідний застосунок на телефоні. Це рівно те, що просив власник, і це
дає двобічність: галочку зручно ставити з телефона, а ми її підхоплюємо.

Події календаря (`calendar.events`) — інший інструмент: вони для блокування
часу під задачу. Це можлива **друга фаза**, описана в кінці. Не роби її
разом із першою.

---

## Що робить власник (один раз, руками)

Ці кроки не автоматизуються — вони в Google Cloud Console.

1. **Google Cloud Console → APIs & Services → Library** → знайти
   **Google Tasks API** → Enable.
2. **APIs & Services → OAuth consent screen → Data access (Scopes)** →
   додати `https://www.googleapis.com/auth/tasks`.
3. Після деплою: на сайті **Integrations → Google → Disconnect → Connect**.
   На екрані згоди має зʼявитися дозвіл на керування задачами.

Крок 3 обовʼязковий: наявний токен виданий без нового скоупу, і виклики
Tasks API повертатимуть 403, доки власник не перепідключиться.

---

## Контекст репозиторію

Прочитай перед початком: `docs/ARCHITECTURE.md`.

**Як тут додається функціонал** — шість точок дотику:

1. модель у `app/modules/<домен>/models.py`;
2. реєстрація в `app/core/registry.py` + реекспорт у `app/models.py`;
3. **міграція руками** в `app/core/migrations.py` — Alembic немає. Нові
   таблиці створює `create_all`, а нові колонки в наявних таблицях треба
   дописати в `_ADDED_COLUMNS` як ідемпотентні `ALTER TABLE ADD COLUMN`;
4. `service.py` + `schemas.py` + `router.py` → підключення в `app/main.py`;
5. фронт (тут не потрібен);
6. `tests/test_smoke.py`: **`EXPECTED_ROUTES` звіряється точним порівнянням
   множин** — новий маршрут без запису туди валить CI.

**Файли, яких торкнешся:**

| Файл | Що там |
|---|---|
| `app/modules/tasks/models.py` | модель `Task` |
| `app/modules/tasks/service.py` | логіка задач, `to_utc()` |
| `app/modules/integrations/google/client.py` | OAuth, `SCOPES`, `_load_credentials(db)`, `status(db)` |
| `app/core/migrations.py` | `_ADDED_COLUMNS` |
| `app/modules/automation/scheduler.py` | реєстрація фонових задач |
| `tests/test_smoke.py` | список маршрутів і таблиць |

**Пастки, на яких тут уже спотикалися:**

- **Час.** SQLite (тести) віддає `datetime` без зони, Postgres (прод) — із
  зоною. Перед будь-яким порівнянням зводь до UTC через
  `app.modules.tasks.service.to_utc()`, інакше отримаєш
  `can't compare offset-naive and offset-aware datetimes` уже в проді.
- **Мережа не має валити фон.** Усі виклики Google обгортай так, щоб збій
  логувався і повертав порожній результат, а не піднімався в планувальник.
- **Без емодзі** в текстах, що йдуть у Telegram.
- Тести ганяються на SQLite; фікстури `client` і `db` — у `conftest.py`.

---

## Обсяг роботи

### 1. Скоуп

У `app/modules/integrations/google/client.py`, список `SCOPES`, додати:

```python
"https://www.googleapis.com/auth/tasks",
```

Поруч — коментар, що без перепідключення Google старий токен його не має.

### 2. Колонки в `Task`

`app/modules/tasks/models.py`:

```python
google_task_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
google_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
# Вимкнено, коли задачу видалили в Google: більше не пхаємо її назад.
google_sync: Mapped[bool] = mapped_column(default=True)
```

І в `app/core/migrations.py`, у `_ADDED_COLUMNS["tasks"]`:

```python
"google_task_id": "VARCHAR(120)",
"google_synced_at": "TIMESTAMP",
"google_sync": "BOOLEAN DEFAULT TRUE",
```

### 3. Клієнт Google Tasks

Дописати в `app/modules/integrations/google/client.py`:

- `_tasks(db)` — будує сервіс `build("tasks", "v1", credentials=...)` за
  зразком наявного `_gmail(db)`; повертає `None`, якщо Google не підключений.
- `ensure_tasklist(db, title: str) -> str | None` — знаходить список задач за
  назвою, створює, якщо його немає, повертає id. Id кешуй у памʼяті модуля
  (як зроблено з `cachedTab` у `sheets`-стилі — див. `_fetch_account_email`
  поруч). Назва — з нового налаштування `google_tasklist_title` у
  `app/core/config.py`, типово `"Networking AI"`.

  Окремий список навмисно: не засмічуємо стандартний список власника і в
  будь-який момент можемо його прибрати одним рухом.
- `list_google_tasks(db, tasklist_id) -> list[dict]` — усі задачі списку,
  включно з виконаними (`showCompleted=True`, `showHidden=True`).
- `upsert_google_task(db, tasklist_id, *, task_id, title, notes, due, completed) -> str | None`
  — `insert`, якщо `task_id` порожній, інакше `patch`. Повертає id.
- `delete_google_task(db, tasklist_id, task_id) -> bool`.

**Формат полів Google Tasks:**

- `due` — RFC3339, але Google **ігнорує час** і бере лише дату. Передавай
  `f"{due_date.isoformat()}T00:00:00.000Z"`. Не намагайся класти туди час —
  він мовчки загубиться.
- `status` — `"needsAction"` або `"completed"`.

### 4. Логіка синхронізації

Новий файл `app/modules/tasks/gsync.py`.

**Що синхронізуємо:** задачі, де `deleted_at is None`, `google_sync is True`.
Задачі без `due_date` теж штовхаємо в список — вони будуть у застосунку
Google Tasks, але **в календарі не зʼявляться**: календар показує лише
задачі з датою. Це очікувано, не баг.

**Правило конфліктів — головне рішення цього ТЗ:**

> Наш сервіс — джерело правди для назви, дати й нотаток.
> Google — джерело правди для **виконання**.

Причина: назви й дати редагуються у нас, а галочку зручно ставити з телефона.
Двобічний last-write-wins тут не годиться — він мовчки затирає правки.

**Алгоритм `sync(db) -> dict`:**

1. `tasklist_id = ensure_tasklist(...)`; якщо `None` — повернути
   `{"skipped": "google not connected"}`.
2. Прочитати всі задачі списку з Google → мапа `{google_id: item}`.
3. **Google → ми:** для кожної нашої задачі з `google_task_id`:
   - немає в мапі (видалили в Google) → `google_task_id = None`,
     `google_sync = False`. **Нашу задачу не видаляти.**
   - `status == "completed"`, а в нас не `done` → перевести в
     `TaskStatus.done`, порахувати в `completed_from_google`.
4. **Ми → Google:** для кожної задачі, що підлягає синку:
   - немає `google_task_id` → `insert`, зберегти id;
   - є → `patch` назви, нотаток, дати і статусу
     (`done` → `completed`, інакше `needsAction`).
   - проставити `google_synced_at`.
5. Задача стала `done` **у нас** → лишається в Google як `completed`
   (не видаляємо: історія має бути видима в обох місцях).
6. Повернути `{"pushed": n, "completed_from_google": m, "unlinked": k}`.

Кожну задачу обробляй в окремому `try/except`: одна помилка не має спиняти
решту синку.

### 5. Планувальник

У `app/modules/automation/scheduler.py`, поруч із наявними `add_job`:

```python
from app.modules.tasks.gsync import run_sync as run_gtasks_sync

_scheduler.add_job(
    run_gtasks_sync,
    "cron",
    minute=45,
    id="gtasks_sync",
    replace_existing=True,
    misfire_grace_time=1800,
)
```

Хвилина 45 — щоб не збігтися з наявними задачами (:05 коуч, :25 пошта).

`run_sync()` сам відкриває сесію через `SessionLocal()` — за зразком
`app/modules/inbox/service.py::run_sync`.

### 6. API

У `app/modules/tasks/router.py`:

```
POST /api/tasks/gsync   -> {"pushed": n, "completed_from_google": m, "unlinked": k}
```

Не забудь додати `("POST", "/api/tasks/gsync")` у `EXPECTED_ROUTES`.

### 7. Бот

У `app/modules/telegram_bot/handlers.py`, у `_handle_command`, гілка
`elif cmd == "gsync":` — запускає синк і відповідає одним рядком із
цифрами. Додати рядок у текст `/help`. У меню команд
(`app/modules/telegram_bot/poller.py`) **не** додавати — це службова команда.

---

## Тести

Новий файл `tests/test_tasks_gsync.py`. Google підміняється через
`monkeypatch.setattr` на функціях модуля
`app.modules.integrations.google.client` — за зразком фікстури `gmail`
у `tests/test_inbox.py`.

Обовʼязкові випадки:

1. нова задача з датою створюється в Google, `google_task_id` зберігається;
2. зміна назви/дати у нас доїжджає до Google наступним синком;
3. `completed` у Google переводить нашу задачу в `done`;
4. `done` у нас доїжджає до Google як `completed`, задача **не видаляється**;
5. задача, видалена в Google, вимикає `google_sync` і **не воскресає**
   наступним синком, а наша задача лишається жива;
6. `deleted_at` у нас виключає задачу з синку;
7. Google не підключений → синк повертає `skipped` і нічого не ламає;
8. помилка на одній задачі не спиняє обробку решти;
9. задача без `due_date` синкається без поля `due` (і не падає).

Уся сюїта має лишитися зеленою: `pytest` з кореня репозиторію.

---

## Готово, коли

- `pytest` зелений, включно з новими тестами;
- `POST /api/tasks/gsync` повертає цифри;
- у `docs/` є короткий `TASKS_CALENDAR.md`: що синкається, правило
  конфліктів, що робити власнику при 403 (перепідключити Google);
- зміни закомічені в гілку `claude/networking-ai-contact-service-o73dse`
  зрозумілими комітами українською.

---

## Фаза 2 (не робити зараз)

Блокування часу: для задач із `duration_min` створювати **події** в календарі
через уже наявний `google.create_event`, на окремому календарі «Задачі».
Це інший інструмент і інша поведінка — обговорити з власником окремо, чи
потрібно, після того як запрацює фаза 1.
