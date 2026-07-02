# Конкуренти: personal CRM / networking-AI (дослідження, липень 2026)

Глибоке дослідження ринку: 103 пошукові/верифікаційні агенти, кожне твердження
пройшло адверсарну перевірку 3 незалежними верифікаторами (голосування 2/3).
Мова цифр і цін — станом на середину 2026, перевіряти перед рішеннями.

## Резюме ринку

Ринок personal CRM / networking-AI 2024–2026 розшарувався: класичні "ручні" CRM (Monica — open source без AI; Dex — LinkedIn-синк за $12/міс; Covve — mobile-first зі збагаченням і nudges за ~$10/міс) задають базовий чекліст фіч, тоді як AI-native гравці змістилися до автономних агентів: Happenstance (NL-пошук по всій мережі через Gmail/LinkedIn/Twitter з ранжуванням за силою зв'язку і прозорим reasoning), Clay (пасивна інгестія контактів з iMessage/WhatsApp/Gmail/Calendar + Home Feed з job changes і днями народження), Boardy (voice-first агент без web-UI; з червня 2026 Boardy Pro за $100/міс автономно веде весь downstream: планування, підготовка, follow-up). Telegram-нативний патерн доведений комерційно двічі: 3RM (ранковий дайджест follow-up'ів о 9:00 з deep links у чати) і CRMChat (пайплайни, дайджест "застряглих" лідів, lead research по Telegram-групах, multi-account outreach з повідомленнями, що "виглядають написаними вручну"). Для нашого стеку пріоритетні запозичення: щоденний Telegram-дайджест "кому написати сьогодні" з one-tap чернетками (3RM, CRMChat); пасивна інгестія всіх взаємодій без ручного вводу (Clay); видимий warmth score і прозоре "чому саме цей контакт" (Happenstance); стрічка життєвих подій поверх facts layer (Clay Home Feed, Covve); автономний downstream-цикл follow-up'ів (Boardy Pro). Ключовий незайнятий диференціатор: жоден конкурент не має підтвердженого моделювання стилю власника з чат-експортів — наш підхід "драфт голосом користувача → one-tap approve → send-as-user" поєднує валідовану ринком автономність з людським контролем.

## Перевірені знахідки по продуктах

### 1. Happenstance — впевненість: high

Happenstance (YC, ~300-400 тис. користувачів): ядро продукту — AI-агент для natural-language пошуку людей по всіх підключених мережах користувача (Gmail, Calendar, LinkedIn, Twitter/X, Instagram, Outlook) замість ручної бази контактів; запити за посадою/локацією/скілами; групи можуть об'єднувати мережі кількох людей в один пошуковий граф. [Об'єднує claims 0, 1, 18]

> «An AI agent searches every network you're on. To get started, you connect your Gmail, LinkedIn, or Twitter accounts»; «create a group for your company, community, or team and pool everyone's connections into one searchable network». Підтверджено вендорським сайтом і 4+ незалежними оглядами 2025-2026. Нюанс: агент автономний у виконанні пошуку, але пошуки ініціюються користувачем.

Джерела: https://happenstance.ai/ · https://aloa.co/ai/resources/show-&-tell/happenstance-review · https://www.producthunt.com/products/happenstance-2 · https://www.aitoolnet.com/happenstance · https://seektool.ai/ai/happenstance-ai

### 2. Happenstance показує силу зв'язку в кожному результаті — впевненість: high

Happenstance показує силу зв'язку в кожному результаті (хто з команди знає людину і наскільки міцно; ранжування = релевантність + сила зв'язку) І розкриває reasoning: дропдаун показує точну логіку/SQL-запит, за яким згенеровано збіг — прозорість, яку рецензенти називають видатною фічею. [Об'єднує claims 2, 19]

> «Every search result shows who in your team knows this person and how strong the connection is... Results are ranked by relevance and connection strength»; «You can actually drop down a menu and see the code it ran to generate the match». Незалежний Medium-огляд підтверджує показ фільтрів, ознак і навіть SQL-запиту. Застереження: сила зв'язку виводиться AI, точність падає на широких запитах.

Джерела: https://happenstance.ai/ · https://aloa.co/ai/resources/show-&-tell/happenstance-review · https://seektool.ai/ai/happenstance-ai

### 3. Happenstance доводить zero-UI патерн — впевненість: medium

Happenstance доводить zero-UI патерн: email-агент (форвард листа на agent@happenstance.ai автоматично запускає пошук по мережі, Pro ~$24/міс) плюс Slack/Discord боти — агентні CRM-дії можуть жити повністю всередині месенджерів/пошти без окремого інтерфейсу. [Claim 3]

> «You can forward emails to agent@happenstance.ai to run searches automatically, which is perfect for intro requests and investor updates». Slack-бот підтверджений окремою сторінкою продукту; Discord — оглядами 2026 і сторінкою інтеграцій. Голосування 2-1, але верифікатор оцінив докази як сильні.

Джерела: https://happenstance.ai/email · https://happenstance.ai/slack · https://blog.zumvu.com/happenstance-review

### 4. Monica — впевненість: high

Monica (monicahq/monica, AGPL-3.0, PHP/Laravel + Vue) задає базовий чекліст персонального CRM: контакти, нагадування (авто-нагадування про дні народження), лог активностей, задачі, нотатки, журнал, life events, фото/документи, лейбли, кілька vault'ів — АЛЕ свідомо не має жодних AI/LLM-фіч: «кому написати», драфти й самаризація лишаються ручними. Це головний gap для AI-native конкурента. [Об'єднує claims 4, 5]

> README: «an open source personal relationship management system, that lets you document your life»; «Monica does not have built-in AI with integrations like ChatGPT»; «Monica is not a smart assistant». Issue #7026 про AI відкрите з 2023 без імплементації станом на грудень 2025. Нюанс: є rule-based 'stay in touch' нагадування, тобто не 100% ручне — але без AI.

Джерела: https://github.com/monicahq/monica · https://github.com/monicahq/monica/issues/7026 · https://getdex.com/blog/monica-review

### 5. Clay — впевненість: high

Clay (clay.earth) доводить пасивну інгестію з особистих месенджерів: iMessage і WhatsApp інтеграції автоматично створюють контакти з людей, яким ви писали, і показують messaging-активність на таймлайні контакту — без ручного вводу. Важливо: Clay імпортує лише метадані (хто/коли), не текст повідомлень; iMessage працює тільки на Mac. [Об'єднує claims 6, 7]

> «iMessage creates contacts for people you've texted and displays messaging-related information on cards»; «Clay's WhatsApp connection creates contacts for people you've messaged... Clay syncs messages from WhatsApp in the Timeline». Clay явно «won't import any of the content of your messages» — доведено metadata-only патерн; повноконтентна інгестія (наш Telegram-кейс) можлива лише завдяки відкритішому API Telegram.

Джерела: https://clay.earth/integrations · https://library.clay.earth/hc/en-us/articles/6819150711323-iMessage · https://library.clay.earth/hc/en-us/articles/26664834392219-WhatsApp

### 6. Clay використовує Gmail + Google Calendar як хребет історії взаємодій — впевненість: high

Clay використовує Gmail + Google Calendar як хребет історії взаємодій: авто-створення контактів з учасників подій і email-кореспондентів (аж до першого листа/події), перша/остання взаємодія на профілі; частота листування живить пріоритезацію контактів. [Claim 8]

> «Google Calendar creates contacts for event attendees and displays event-related information on cards»; «automatically creates contacts for people you've emailed, including everyone back to your first email». Обмеження: лише primary calendar, лише події з іншими учасниками, read-only.

Джерела: https://clay.earth/integrations · https://library.clay.earth/hc/en-us/articles/6823053743643 · https://clay.earth/integrations/gmail

### 7. Clay має enrichment + дайджест-шар — впевненість: high

Clay має enrichment + дайджест-шар: Twitter/X інтеграція не лише імпортує, а й збагачує контакти і пушить проактивні апдейти (зміни біо/локації, важливі пости); Home Feed показує job changes, згадки в новинах, дні народження, соцмережеві апдейти. Інтеграцію X було відключено після змін API 2023 і перезапущено. [Claim 9]

> «Twitter/X creates and enriches contacts, and provides updates and significant posts... Clay's Home Feed displays updates about your network including job changes, news mentions, and birthdays». Підтверджено офіційними help-doc'ами, актуально на 2026.

Джерела: https://clay.earth/integrations · https://library.clay.earth/hc/en-us/articles/6820188680091 · https://library.clay.earth/hc/en-us/articles/6691827190939

### 8. CRMChat — Telegram-нативний CRM — впевненість: high

CRMChat — Telegram-нативний CRM (mini-app): контакти/групи в пайплайнах з задачами, нагадуваннями, нотатками; бот шле щоденний ранковий дайджест застряглих лідів і нагадує про follow-up'и — комерційно розгорнутий доказ патерну «Telegram-дайджест 'кому написати сьогодні'» (платні тарифи від ~$28/міс, лістинги на Product Hunt і G2). [Claim 10]

> «The bot reminds your team about follow-ups and stalled deals... provides a daily digest of stalled leads»; окремо — «morning summary of pipeline activities, key tasks, and top deals». «Доводить, що працює» = комерційно продається, а не незалежно виміряна ефективність.

Джерела: https://crmchat.ai/industries/web3-crypto · https://crmchat.ai/pricing · https://www.producthunt.com/products/crm-chat

### 9. CRMChat пропонує Telegram-native lead research і outreach — впевненість: medium

CRMChat пропонує Telegram-native lead research і outreach: парсинг публічних Telegram-груп у бази проспектів, look-alike пошук за спільними групами, конвертація телефонів у TG-username (~30-50% успіху), multi-account розсилки з проксі/warmup/розтягуванням у часі, персоналізацією «під ручне написання» і єдиним inbox для відповідей. Спам-блоки все одно трапляються (визнає сам вендор). [Об'єднує claims 11, 12]

> «Lead research tools that find look-alike audiences, convert phone numbers in TG usernames, and parse Telegram groups»; «customized campaigns where messages look manually written». Механізми (проксі per-account, warmup, вікна 8-12 год) описані у вендорських доках; unified inbox — лише vendor-asserted, тому medium. Релевантно нам як доказ ризиків: навіть спеціалізований інструмент не уникає спам-блоків Telegram.

Джерела: https://crmchat.ai/industries/web3-crypto · https://crmchat.ai/telegram-lead-research · https://crmchat.ai/help-center/phone-number-to-tg-username-converter · https://crmchat.ai/blog/avoid-telegram-bans-for-outreach

### 10. Boardy — впевненість: high

Boardy: voice-first AI-агент як єдиний інтерфейс — користувач конектиться в LinkedIn, дає номер, отримує реальний дзвінок від людиноподібного AI (австралійський акцент), розповідає над чим працює; агент проактивно пропонує double-opt-in інтро email'ом; WhatsApp — альтернативний канал; web CRM-UI відсутній повністю. Доводить, що месенджер/голос працює як головний інтерфейс networking-агента. [Об'єднує claims 13, 20]

> «users share their phone number on LinkedIn, then receive a call from an AI with an Australian accent that aims to understand their needs and make relevant introductions». Підтверджено TechCrunch (pre-seed $3M + seed $8M від Creandum) і 5+ незалежними оглядами. «Автономність» = агент сам пропонує матчі; інтро double-opt-in. Відгуки фаундерів про якість інтро змішані.

Джерела: https://techcrunch.com/2025/01/14/boardy-ai-raises-8m-seed-round-months-after-closing-pre-seed/ · https://blastra.io/blog/boardy-ai-networking-guide/ · https://techcrunch.com/2024/10/24/ai-networking-startup-boardy-raises-3m-pre-seed/ · https://creandum.com/stories/backing-boardy-ai/ · https://whatsapp.boardy.ai/r/andrewemailintro

### 11. Boardy pricing/еволюція — впевненість: high

Boardy pricing/еволюція (mid-2026): база безкоштовна (необмежені розмови, до 3 інтро/день); у червні 2026 запущено Boardy Pro за $100/міс (перші 5000 — free-for-life, розібрано за 2 години) з framing'ом «інтро — лише 10% роботи»: агент бере на себе downstream — планування зустрічей, підготовку, нотатки, follow-up до закриття угоди. Валідує ринковий рух до високоавтономних (не suggestion-based) relationship-агентів і преміальну монетизацію автономності. [Об'єднує claims 21, 22]

> Офіційний пост Boardy: «I'm done making intros. Boardy Pro is here... 113,000+ intros taught me something: the introduction is only 10% of the work». Застереження: «autonomously until deal closes» — маркетингове формулювання; задокументовані фічі радше heavily assistive (допомога з плануванням, преп, nudges).

Джерела: https://blastra.io/blog/boardy-ai-networking-guide/ · https://x.com/boardyai/status/2066539651502895129 · https://slavakurilyak.com/posts/boardy-pro

### 12. 3RM — crypto-native CRM, де Telegram є першокласним джерелом даних і поверхнею взаємодії — впевненість: high

3RM — crypto-native CRM, де Telegram є першокласним джерелом даних і поверхнею взаємодії (170K+ імпортованих Telegram-розмов, нативний Chrome extension у Telegram web): бот щоранку о 9:00 шле дайджест follow-up'ів з deep links назад у відповідні Telegram-чати або в апку — робочий прецедент патерну «дайджест 'кому написати сьогодні' в Telegram з deep links». [Об'єднує claims 14, 15]

> «The Telegram bot sends daily updates at 9 a.m. saying 'good morning here are your follow ups', providing links to Telegram chats or opening the context in 3RM». Продукт живий у 2026 як «3RM — AI CRM for Telegram, Google Calendar, X». Деталь «9 a.m.» — з 2023, не перевірена в поточних доках; сам патерн (щоденний дайджест + deep links) підтверджений продуктовою документацією.

Джерела: https://www.theblock.co/post/213238/3rm-raises-from-distributed-global · https://3rm.co · https://support.3rm.co

### 13. Dex — впевненість: medium

Dex (getdex.com) — найкращий personal CRM для LinkedIn-важких мереж: синк LinkedIn (до 10 000 конекшенів, оновлення кожні 3-5 днів) + авто-підтягування email-контактів; Premium $12/міс, дуже обмежений free tier; keep-in-touch нагадування — ядро продукту; немає in-person lead capture (цифрової візитки, лід-форм, автоматичних nurture-послідовностей). [Claim 16]

> «Dex wins for LinkedIn-heavy networkers... no digital card to share, no lead forms, no automated follow-ups». Джерело — блог конкурента (Wave Connect, вендор цифрових візиток), але факти незалежно підтверджені сторінками Dex і оглядами 2026. «No automated follow-ups» = немає nurture-секвенцій; нагадування про follow-up у Dex якраз є.

Джерела: https://wavecnct.com/blogs/personal-crm · https://getdex.com/product/linkedin · https://getdex.com/docs/faq/linkedin · https://softwarefinder.com/crm/dex

### 14. Covve — mobile-first personal CRM за $9.99/міс — впевненість: medium

Covve — mobile-first personal CRM за $9.99/міс (при річній оплаті; помісячно $12.99): авто-збагачення контактів (посади, компанії, локації — у поточній версії більше через AI research assistant і news alerts зі 150+ джерел), плюс проактивні 'stay in touch' nudges коли втрачаєш контакт — валідує зв'язку auto-enrichment + проактивні нагадування як ядро personal-CRM UX. [Claim 17]

> «automatically enriches your phone contacts with up-to-date job titles, companies, and locations and nudges you to stay in touch». Застереження верифікатора: масове збагачення всієї телефонної книги — це радше legacy-версія (її scraped-база спричинила витік db8151dd 2020 року, ~23M людей); сьогодні enrichment центрований на лідах/AI-research/новинах. Урок для нас: обережно з provenance даних збагачення.

Джерела: https://wavecnct.com/blogs/personal-crm · https://covve.com · https://crm.org (огляд, оновлений 04/2026)

## Пріоритезовані рекомендації — що беремо собі

РЕКОМЕНДАЦІЇ (пріоритезовано) для нашого 99%-автономного single-user networking-AI (FastAPI + Postgres + Claude opus-4-8 + Telegram Business + Gmail/Calendar + warmth + facts): 1) Ранковий Telegram-дайджест «кому написати сьогодні» з deep links і one-tap діями — доведено 3RM (9:00, links у чати) і CRMChat (daily digest застряглих лідів); у нас: cron у FastAPI, warmth score ранжує кандидатів, бот шле картки з inline-кнопками [чернетка / відкласти / пропустити] і tg:// deep links. 2) Пасивна інгестія 100% взаємодій — доведено Clay (iMessage/WhatsApp/Gmail/Calendar авто-створюють контакти й таймлайн); у нас: Telegram Business updates + Gmail/Calendar webhooks → таблиця interactions, авто-створення контактів з першого дотику, причому ми можемо повний контент (Clay лише метадані). 3) Видимий connection/warmth score + прозоре «чому цей контакт» — доведено Happenstance (сила зв'язку в кожному результаті, дропдаун з логікою/SQL); у нас: показувати warmth і 1-рядкове пояснення (Claude) у кожній картці дайджесту — це будує довіру до автономії. 4) Enrichment-стрічка життєвих подій (job changes, дні народження, новини) — доведено Clay Home Feed і Covve news alerts; у нас: facts layer з validity-періодами + періодичний enrichment pipeline, тригерні події потрапляють у дайджест як привід написати. 5) NL-пошук по власній мережі — доведено Happenstance; у нас: pgvector embeddings по facts/interactions + Claude tool-use, що генерує SQL, з показом reasoning. 6) Драфт «голосом власника» + one-tap approve — ринок валідує рівень автономії з людським підтвердженням (Boardy: double-opt-in інтро; CRMChat: «messages look manually written»), але НІХТО не робить підтвердженого style-learning з чат-експортів — наш Telegram-export few-shot + style profile у Postgres є диференціатором. 7) Автономний downstream-цикл (планування, преп, follow-up до результату) — напрям валідовано Boardy Pro ($100/міс, черга з 5000 за 2 години = попит); у нас: follow-up state machine у Postgres + Calendar sync + агентні цикли Claude. 8) Zero-UI: весь продукт живе в Telegram-боті + email, без web-UI — доведено Boardy (телефон/WhatsApp) і Happenstance (agent@, Slack-бот); forward повідомлення боту = команда. 9) Заповнити AI-gap Monica: її чекліст (life events, нотатки, ДН-нагадування, журнал) — це table stakes, які наш facts layer вже покриває; AI зверху — те, чого open-source лідер свідомо не дає. 10) Ризик-менеджмент send-as-user: навіть CRMChat з проксі/warmup визнає спам-блоки — наш send-as-user через офіційний Telegram Business API з людським approve на кожне повідомлення структурно безпечніший за userbot-розсилки, і це варто зберегти як принцип. Ціновий бенчмарк: $10-24/міс assistive, $100/міс автономний агент.

## Застереження

1) Більшість фіче-claims спираються на вендорські сторінки/доки — коректно для «що продукт вміє», але заяви про ефективність («без ризику банів», «make deals happen», unified inbox CRMChat) — маркетинг без незалежної верифікації. 2) Кілька первинних сайтів (happenstance.ai, clay.earth, crmchat.ai, aloa.co) блокували прямий fetch (403), верифікація йшла через пошуковий індекс + незалежні огляди. 3) Часова чутливість: ціни (Dex $12, Covve $9.99 annual, Boardy Pro $100, CRMChat ~$28) — станом на середину 2026; Boardy Pro запущено лише в червні 2026, реальна автономність не перевірена в полі; Clay після поглинання Automattic може змінити продукт. 4) Дві claim відхилено верифікацією: масштабні метрики Boardy (10K+ дзвінків → «demonstrably works at scale») і деталі Clay (cadence-нагадування + ціна ~$10) — не використовуйте їх. 5) Нюанси, що звужують висновки: Clay інгестить лише метадані повідомлень (не контент), iMessage — Mac-only; enrichment Covve у поточній версії слабший, ніж у legacy (яка спричинила витік 23M записів у 2020); connection strength у Happenstance — AI-інференція зі спадною точністю на широких запитах; «9:00» у 3RM — деталь 2023 року. 6) Джерела для Dex і Covve — блог конкурента (Wave Connect), хоч і корпусно підтверджений; голосування 2-1 по Happenstance email-агенту, Clay iMessage і Dex.

## Відкриті питання (варто дослідити далі)

- Чи моделює хоч один конкурент стиль письма власника (style-learning з переписок) для драфтів «його голосом»? У верифікованих даних — ні; варто окремо перевірити нові фічі Clay Nexus, Dex AI briefs та нішеві AI-outreach інструменти (Postsync тощо), які не потрапили у підтверджені claims.
- Які enrichment-провайдери (People Data Labs, Clearbit тощо) стоять за Clay/Covve/Happenstance і які юридичні/приватнісні межі збагачення для single-user сервісу в ЄС (урок Covve db8151dd)?
- Реальні метрики залучення й утримання: чи діють користувачі на щоденні дайджести (3RM/CRMChat/Clay Home Feed) і яка конверсія Boardy-інтро в реальні угоди — жодних незалежних цифр не знайдено.
- Межі Telegram Business API для send-as-user на масштабі: за яких обсягів/патернів навіть офіційний API з approve-flow ризикує обмеженнями, з огляду на те, що CRMChat визнає спам-блоки навіть з проксі й warmup?

## Спростовані твердження (НЕ спиратися на них)

- The autonomous-agent approach demonstrably works at scale: within roughly three months of its October 2024 launch, Boardy had conducted more than 10,000 phone calls and facilitated thousands of connections that led to real partnerships and investments for startups.
- Clay (clay.earth) automatically enriches contacts (job titles, companies, LinkedIn data) and syncs email contacts, and supports cadence-style 'soft reminders' (e.g. follow up in 3 months / check in quarterly) that are modeled as relationship rhythms rather than to-dos — but has no in-person capture mechanism (no QR code, NFC, or shareable link), costing roughly $10/month after a free trial.
