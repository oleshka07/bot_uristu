/** Мінімум від Telegram Bot API: надіслати повідомлення власнику. */

export async function sendMessage(env, text, { chatId } = {}) {
  const target = chatId || env.ALLOWED_CHAT_ID;
  if (!target) throw new Error("ALLOWED_CHAT_ID не заданий");
  const res = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        chat_id: String(target),
        text,
        disable_web_page_preview: true,
      }),
    },
  );
  if (!res.ok) {
    throw new Error(`Telegram ${res.status}: ${(await res.text()).slice(0, 200)}`);
  }
  return res.json();
}
