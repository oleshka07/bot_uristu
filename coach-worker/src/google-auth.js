/** Доступ до Google Sheets від імені сервісного акаунта.
 *
 * Воркер не має Node-крипти, тож JWT підписуємо через WebCrypto:
 * PKCS8 → RSASSA-PKCS1-v1_5 (SHA-256) → обмін на access_token.
 */

const TOKEN_URL = "https://oauth2.googleapis.com/token";
const SCOPE = "https://www.googleapis.com/auth/spreadsheets";

// Токен живе годину; тримаємо його в памʼяті ізолята, щоб не ходити за
// новим на кожен апдейт Telegram.
let cached = { token: null, expiresAt: 0 };

function b64url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function textBytes(value) {
  return new TextEncoder().encode(value);
}

function pemToPkcs8(pem) {
  const body = pem
    .replace(/-----BEGIN [^-]+-----/, "")
    .replace(/-----END [^-]+-----/, "")
    .replace(/\s+/g, "");
  const raw = atob(body);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out.buffer;
}

export function parseServiceAccount(json) {
  let sa;
  try {
    sa = typeof json === "string" ? JSON.parse(json) : json;
  } catch {
    throw new Error("GOOGLE_SA_JSON не є валідним JSON");
  }
  if (!sa?.client_email || !sa?.private_key) {
    throw new Error("GOOGLE_SA_JSON без client_email/private_key");
  }
  // wrangler secret put приймає багаторядковий текст, але якщо JSON приїхав
  // із екранованими \n у ключі — повертаємо справжні переводи рядка.
  sa.private_key = sa.private_key.replace(/\\n/g, "\n");
  return sa;
}

export async function getAccessToken(env) {
  const now = Math.floor(Date.now() / 1000);
  if (cached.token && cached.expiresAt - 60 > now) return cached.token;

  const sa = parseServiceAccount(env.GOOGLE_SA_JSON);
  const header = b64url(textBytes(JSON.stringify({ alg: "RS256", typ: "JWT" })));
  const claims = b64url(
    textBytes(
      JSON.stringify({
        iss: sa.client_email,
        scope: SCOPE,
        aud: TOKEN_URL,
        iat: now,
        exp: now + 3600,
      }),
    ),
  );
  const signingInput = `${header}.${claims}`;

  const key = await crypto.subtle.importKey(
    "pkcs8",
    pemToPkcs8(sa.private_key),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = new Uint8Array(
    await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, textBytes(signingInput)),
  );
  const assertion = `${signingInput}.${b64url(signature)}`;

  const res = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion,
    }),
  });
  if (!res.ok) {
    throw new Error(`Google OAuth ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  const data = await res.json();
  cached = {
    token: data.access_token,
    expiresAt: now + Number(data.expires_in || 3600),
  };
  return cached.token;
}
