"""telegram_bot module — the service's Telegram "hands".

Owns the bot itself (long polling), the Telegram Business proxy flow
(incoming DMs → AI draft → admin approval → send as the user), and voice
transcription. Ported from the Chater bot so brain and hands live in one
infrastructure.
"""
