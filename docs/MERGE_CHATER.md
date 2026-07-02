# Злиття Chater → Networking AI (одна інфраструктура)

## Рішення

**Все комунікаційне ядро переїжджає СЮДИ (bot_uristu, Python).** Тут "мозок"
(контакти, warmth, факти, досьє, Claude, дашборд, CI/CD, діагностика) — і
тепер тут же і "руки": власний Telegram-бот з підтримкою **Telegram Business**
(читає твої особисті вхідні та надсилає відповіді від твого імені).

Chater (TypeScript) лишається тільки як особистий планувальник задач
(Todoist/Notion/дайджести) до Фази B — його proxy-функції тепер живуть тут.

```
Telegram (твої особисті DM, Business)
        │ business_message / callback
        ▼
  bot-сервіс (python -m app.run_bot)        ← НОВЕ (модуль telegram_bot)
        │ контакт ← telegram_chat_id
        ▼
  Мозок: interactions + warmth + facts + Claude-чернетка (стиль, tone)
        │ прев'ю з кнопками
        ▼
  Твій чат з ботом: ✅ Надіслати · ✍️ reply (текст/голос) · ⏭ Пропустити
        │ ✅
        ▼
  sendMessage(business_connection_id) → повідомлення ВІД ТЕБЕ контакту
```

## Що вже зроблено (код у цьому репо)

- **Модуль `app/modules/telegram_bot/`** — поллер (getUpdates з
  `business_message`/`business_connection`), клієнт Bot API, диспетчер.
- **Proxy-флоу**: вхідне → контакт (по `telegram_chat_id`, авто-створення) →
  interaction (+warmth) → Claude-чернетка у твоєму стилі (історія + tone +
  факти) → прев'ю адміну з кнопками → ✅ = надсилання від твого імені +
  лог вихідної взаємодії.
- **Коригування**: reply на прев'ю текстом **або голосом** → Whisper/Gemini
  розшифровка → Claude переписує чернетку → оновлене прев'ю.
- **Твої власні повідомлення** (написані з телефона) теж логуються як
  outbound-взаємодії — історія повна з обох боків.
- **Команди**: /help, /today (=/network), /due, /find.
- **Контакт**: нові поля `telegram_chat_id`, `tone` (стиль спілкування).
- **Імпортер Chater** тепер переносить `tone`, `ai_summary` (→ досьє, якщо
  порожнє), `telegram_chat_id`, `telegram_username`.
- **docker-compose**: новий сервіс `bot` (ідлить, поки не ввімкнеш прапорець).

## Cutover — що зробити руками (один раз)

### Варіант A (рекомендую): той самий бот, повний перехід
Business-підключення прив'язане до бота, тож переймаємо токен Chater-бота —
підключення в Telegram зберігається автоматично.

1. На сервері в `.env` поряд з docker-compose додай:
   ```
   TELEGRAM_BOT_TOKEN=   ← з Chater .env (BOT_TOKEN / TELEGRAM_BOT_TOKEN)
   TELEGRAM_CHAT_ID=     ← з Chater .env (ADMIN_ID)
   TELEGRAM_POLLING_ENABLED=true
   OPENAI_API_KEY=       ← з Chater .env (для голосу; опційно)
   GEMINI_API_KEY=       ← з Chater .env (fallback голосу; опційно)
   ```
2. Зупини Chater (інакше 409 — два поллери на один токен):
   ```
   systemctl stop chater && systemctl disable chater
   ```
   (якщо він у pm2: `pm2 stop chater && pm2 save`)
3. Перезапусти наш стек: `docker compose up -d --build`
4. Напиши боту `/help` — має відповісти. Попроси когось написати тобі в
   особисті — прев'ю з чернеткою прилетить у чат з ботом.
5. У веб-UI: Integrations → Chater → **Import** (підтягне tone/ai_summary/
   chat_id + повну історію).

⚠️ Наслідок A: планувальник Chater (Todoist/Notion-дайджести) тимчасово
не працює, доки не портуємо його (Фаза B) або не даси йому окремого бота.

### Варіант B: два боти, нуль регресу
1. @BotFather → новий бот (напр. `@StepanNetworkBot`) → токен у наш `.env`
   (ті самі змінні, що вище).
2. Telegram → Налаштування → Business → Чат-боти → заміни Chater-бота на
   нового (дозволь читання і відповіді).
3. `TELEGRAM_POLLING_ENABLED=true` → `docker compose up -d --build`.
4. Chater живе далі з планувальником (його proxy просто перестане отримувати
   business-повідомлення). Дублювання ранкового networking-дайджесту вимкни,
   прибравши блок `networkingDigest` з його scheduler.ts (опційно).

## Фази далі

- **Фаза B** — вирішити долю планувальника Chater: портувати інтейк
  (текст/голос → Todoist/Notion) і дайджести сюди, або лишити окремим ботом.
- **Фаза C** — черга обходу (outreach queue): ранковий дайджест → кнопка
  «Почати» → бріф по кожному контакту з чернеткою first-touch → ✅/✍️/⏭.
  Інфраструктура вже готова (TelegramDraft.kind="outreach").
- **Фаза D** — стиль: ембединги всієї історії листування (векторний пошук),
  щоб чернетки ще точніше звучали як ти. Сюди ж — вивантаження твоїх чатів
  з Telegram (Settings → Advanced → Export) для навчання стилю.
