/** Мозок коуча: Claude Messages API з tool use. */

const URL = "https://api.anthropic.com/v1/messages";
const VERSION = "2023-06-01";

// Параметр effort підтримують не всі моделі; якщо API його не приймає —
// знімаємо один раз на весь ізолят і далі шлемо без нього.
let effortSupported = true;

async function post(env, body) {
  const res = await fetch(URL, {
    method: "POST",
    headers: {
      "x-api-key": env.ANTHROPIC_API_KEY,
      "anthropic-version": VERSION,
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
  return res;
}

export async function messages(env, { system, messages: msgs, tools, maxTokens = 700 }) {
  const base = {
    model: env.CLAUDE_MODEL || "claude-opus-5",
    max_tokens: maxTokens,
    system,
    messages: msgs,
  };
  if (tools?.length) base.tools = tools;

  const effort = env.CLAUDE_EFFORT || "low";
  let res = await post(env, effortSupported && effort ? { ...base, effort } : base);
  if (!res.ok && res.status === 400 && effortSupported && effort) {
    const detail = await res.text();
    if (detail.includes("effort")) {
      effortSupported = false;
      res = await post(env, base);
    } else {
      throw new Error(`Claude 400: ${detail.slice(0, 300)}`);
    }
  }
  if (!res.ok) {
    throw new Error(`Claude ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  return res.json();
}

export function textOf(reply) {
  return (reply?.content || [])
    .filter((block) => block.type === "text")
    .map((block) => block.text)
    .join("\n")
    .trim();
}

export function toolUses(reply) {
  return (reply?.content || []).filter((block) => block.type === "tool_use");
}

/**
 * Проганяє діалог, поки Claude просить інструменти. `handlers` — мапа
 * назва → async (input) => текст результату для моделі.
 */
export async function runWithTools(
  env,
  { system, messages: msgs, tools, handlers, maxSteps = 3, maxTokens = 700 },
) {
  const history = [...msgs];
  const used = [];
  let reply = await messages(env, { system, messages: history, tools, maxTokens });

  for (let step = 0; step < maxSteps; step++) {
    const calls = toolUses(reply);
    if (!calls.length) break;
    history.push({ role: "assistant", content: reply.content });

    const results = [];
    for (const call of calls) {
      const handler = handlers[call.name];
      let output;
      if (!handler) {
        output = `Невідомий інструмент ${call.name}`;
      } else {
        try {
          output = await handler(call.input || {});
          used.push({ name: call.name, input: call.input || {} });
        } catch (err) {
          output = `Помилка: ${err.message}`;
        }
      }
      results.push({
        type: "tool_result",
        tool_use_id: call.id,
        content: String(output ?? "ok"),
      });
    }
    history.push({ role: "user", content: results });
    reply = await messages(env, { system, messages: history, tools, maxTokens });
  }

  return { text: textOf(reply), used };
}
