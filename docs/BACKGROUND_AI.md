# Фоновий AI: підписка Claude Code замість API-ключа

Усе, що система робить «сама» — чернетка на вхідне в Telegram, розбір пошти,
досьє й факти, дописи з соцмереж, питання і вердикти коуча — тепер має два
взаємозамінні бекенди. Перемикач один, `BACKGROUND_AI` у `.env`:

| Значення | Хто думає | Коли обирати |
|---|---|---|
| `api` (типово) | модель через ключ (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`), одразу | поки немає підписки, або якщо йдеш від Anthropic зовсім |
| `claude_code` | Claude Code на підписці власника, у фоні, через наш MCP | Max/Pro-підписка, хочеться не платити за токени двічі |
| `off` | ніхто; фонові AI-задачі мовчать | пауза на все |

API ніде не викорчувано: у режимі `api` код іде тим самим шляхом, що й до
цієї зміни, а в `claude_code` він же лишається відкатом
(`BACKGROUND_AI_FALLBACK=api`). Перейти на GPT чи Gemini — це вже шар
`insights/llm.py`, який фонового режиму не стосується.

Інтерактивне — команди бота, кнопки під картками, «Переформулювати», сторінка —
завжди йде через API: там відповідь потрібна зараз, а MCP працює лише «на
витяг», сам він нікого не будить.

## Як це працює

```
подія (вхідне, година, тик)          воркер (контейнер worker)
        │                                    │
  brain.<задача>(db, …)                      │ кожні 5 с: claim_next()
        │ api ────► ai.* одразу              │
        │ claude_code ─► ai_jobs (queued) ──►│ claude -p "<промпт>" \
        │              повертає None         │   --mcp-config {url?profile=…} \
        │                                    │   --allowedTools mcp__networking
   викликач живе з None:                     │
   картка «⏳ Claude пише чернетку»          │ Claude читає crm_get_*, пише
   звірка без питання                        │ crm_fill_* / crm_save_* / crm_set_*
   дописи лишаються непрочитаними            │
                                             ▼
                                   картка оновлена, питання надіслано, досьє записано
```

- `app/modules/aijobs/brain.py` — диспетчер. Одна функція на одну фонову
  потребу; у `api` робить те, що робила завжди, у `claude_code` ставить задачу
  й повертає `None`.
- `app/modules/aijobs/service.py` — черга `ai_jobs`: `enqueue` з дедупом за
  ключем (поки така задача чекає, друга не заводиться) і дебаунсом
  (`AIJOBS_DEBOUNCE_SECONDS`, щоб пачка вхідних від однієї людини стала однією
  задачею), `claim_next`, `complete`, `fail` з повторами, `requeue_stale`.
- `app/modules/aijobs/prompts.py` — промпт і профіль MCP для кожного виду.
- `app/modules/aijobs/worker.py` — `python -m app.run_worker`: бере задачу,
  пише тимчасовий `--mcp-config`, запускає `claude -p --output-format json`,
  зберігає результат і `usage` (вартість, токени, ходи).
- `app/modules/mcp/tools.py` — 15 фонових інструментів і `PROFILES`.

Сім видів задач і їхні інструменти:

| Задача | Коли ставиться | Профіль | Вхід → вихід |
|---|---|---|---|
| `draft_reply` | вхідне в Telegram (через `AIJOBS_DEBOUNCE_SECONDS`) | reply | `crm_get_pending_reply` → `crm_fill_reply_draft` (`[SKIP]` = не відповідати) |
| `triage_inbox` | синк пошти о :25, якщо є нерозмічене | inbox | `crm_list_untriaged_emails` → `crm_triage_email`, `crm_save_email_draft` |
| `consolidate` | о :35, якщо є кому | memory | `crm_list_contacts_to_consolidate` → `crm_save_dossier`, `crm_add_fact` |
| `social_digest` | після монітора соцмереж, на контакт | social | `crm_list_unprocessed_posts` → `crm_add_fact`, `crm_add_life_event`, `crm_mark_posts_processed` |
| `coach_question` | година питання коуча | coach | `crm_get_pending_coach_question` → `crm_set_coach_question` (надсилає сам) |
| `coach_review` | відповідь власника на питання | coach | `crm_get_checkin_to_review` → `crm_record_checkin_review` (надсилає реакцію) |
| `weekly_verdict` | день/година тижневого підсумку | coach | `crm_get_week_block` → `crm_send_owner_message` |

Профіль у адресі (`/mcp/<token>?profile=reply`) обрізає `tools/list` до
4–8 інструментів: менше схем у контексті — менше квоти на кожен запуск. Без
профілю (claude.ai, Claude Code у розмові) фонові інструменти не показуються.

## Скільки це їсть квоти і як не заважати

Точних цифр Anthropic не публікує; орієнтир — Max 5x ≈ 225, Max 20x ≈ 900
«повідомлень» на 5 годин, і `claude -p` з 5–8 інструментами та `sonnet`
коштує приблизно одне-два таких повідомлення. Типовий день (5–10 вхідних,
одна пошта, 1–3 консолідації, питання коуча) — 10–20 запусків. Гальма:

- **подієво, не опитуванням** — порожня черга нічого не коштує, воркер просто
  спить;
- `CLAUDE_CODE_MODEL=sonnet` (типово), `opus` лише якщо справді треба;
- `AIJOBS_MAX_PER_HOUR` (40) — стеля, далі задачі чекають наступної години;
- `AIJOBS_QUIET_HOURS=23-7` — уночі воркер спить, вранці розгрібає;
- **пауза** кнопкою в Integrations → «Фоновий AI» — на час, коли підписка
  потрібна тобі самому; черга накопичується, нічого не губиться;
- панель показує запуски, токени і `total_cost_usd` за сьогодні і за тиждень —
  це те, що повернув сам `claude -p`, а не наша оцінка.

Claude Code не впорався тричі (ліміт, таймаут, збій) — задача виконується
API-шляхом, якщо `BACKGROUND_AI_FALLBACK=api`; `none` — просто лягає у
`failed` і видно в журналі панелі.

## Увімкнути

На своєму ПК (де вже стоїть Claude Code і є підписка):

```
claude setup-token
```

Він виведе довгий токен. Це пароль до твоєї підписки — тільки в `.env` на
сервері, ніде більше. Далі на сервері:

```
cd ~/projects/networking-ai
nano .env
```

Додати (або поправити) рядки:

```
BACKGROUND_AI=claude_code
BACKGROUND_AI_FALLBACK=api
CLAUDE_CODE_OAUTH_TOKEN=<токен із setup-token>
CLAUDE_CODE_MODEL=sonnet
AIJOBS_MAX_PER_HOUR=40
AIJOBS_QUIET_HOURS=23-7
```

І перезібрати (зʼявиться контейнер `worker`):

```
docker compose up -d --build
docker compose logs -f worker
```

У логу має бути `worker up: mode=claude_code model=sonnet`, а в панелі
Integrations → «Фоновий AI» — режим Claude Code і порожня черга. Перший
запуск побачиш, коли прийде вхідне в Telegram: картка «⏳ Claude пише
чернетку» за хвилину оновиться текстом.

Повернутися на API — `BACKGROUND_AI=api` і `docker compose up -d`. Контейнер
`worker` при цьому може лишатися: він просто пише в лог «режим api» і спить.

## Безпека

- Токен підписки живе лише в env контейнера `worker`. У БД, логи, панель він
  не потрапляє.
- Воркер ходить до нашого MCP усередині docker-мережі
  (`MCP_INTERNAL_URL=http://web:8000`) тим самим токеном `/mcp/<token>`, що й
  claude.ai; токен береться з БД, у файл конфігу пишеться тимчасово й
  видаляється після запуску.
- `claude -p` запускається з `--strict-mcp-config` і без вбудованих
  інструментів (`Bash`, `Edit`, `Write`, `Read`, `WebFetch`, …): Claude бачить
  лише `crm_*` свого профілю. Файлова система й мережа контейнера йому
  недоступні.
- Усе, що воркер пише, проходить ті самі функції, що й панель (`apply_triage`,
  `fill_reply_draft`, `deliver_review`): жодного «сирого» доступу до БД.

## Тести

`tests/test_aijobs.py` — черга (дедуп, дебаунс, повтори, протухлі), диспетчер
у трьох режимах, вхідне з карткою-заглушкою і заповнення через інструмент,
профілі, пошта, досьє, дописи, коуч (питання, розбір, тиждень), команда
воркера, розбір результату, гальма, відкат на API.
