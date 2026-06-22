# Google Cloud setup — Gmail + Calendar sync (step by step)

These instructions are written to be followed click-by-click (e.g. by a browser
agent). The goal: create an **OAuth 2.0 Web client** and enable the **Gmail API**
and **Google Calendar API**, then put the client ID/secret into the app.

> Networking AI reads your own Gmail and Calendar with **your** permission (user
> OAuth). This is different from Chater, which uses a Calendar *service account*.
> Both can coexist; they are independent credentials.

Total time: ~10 minutes.

---

## 0. Prerequisites
- A Google account: **o.stepeniev@swipescape.eu** (the account whose mail and
  calendar you want synced).
- Decide the app's public URL now. Two redirect URIs will be registered:
  - Local testing: `http://localhost:8000/api/integrations/google/callback`
  - Production: `https://YOUR_DOMAIN/api/integrations/google/callback`
    (replace `YOUR_DOMAIN`, e.g. `networking.swipescape.eu`).

---

## 1. Create / select a project
1. Go to <https://console.cloud.google.com/>.
2. Top bar → project dropdown → **New Project**.
3. Name: `Networking AI`. Click **Create**. Wait, then select it (project
   dropdown → Networking AI).

## 2. Enable the two APIs
1. Go to <https://console.cloud.google.com/apis/library>.
2. Search **Gmail API** → open it → **Enable**.
3. Go back to the Library, search **Google Calendar API** → open → **Enable**.

## 3. Configure the OAuth consent screen
1. Go to <https://console.cloud.google.com/apis/credentials/consent>.
2. User type: **External** → **Create**.
   (If a "Google Auth Platform" / "Branding" wizard appears, fill the same
   fields it asks for — app name, support email, developer email.)
3. App information:
   - App name: `Networking AI`
   - User support email: `o.stepeniev@swipescape.eu`
   - Developer contact email: `o.stepeniev@swipescape.eu`
4. **Save and Continue**.
5. **Scopes** step: you may skip adding scopes here (the app requests them at
   runtime). **Save and Continue**.
6. **Test users** step: click **Add Users**, add
   `o.stepeniev@swipescape.eu`. **Save and Continue**.
   - Leaving the app in "Testing" mode is fine for personal use. Refresh tokens
     for a Testing app can expire after 7 days; if that becomes annoying, click
     **Publish App** on the consent screen (no Google verification is required
     for personal use with your own test users, but publishing removes the
     7‑day refresh-token expiry).

## 4. Create the OAuth Client ID (Web application)
1. Go to <https://console.cloud.google.com/apis/credentials>.
2. **+ Create Credentials** → **OAuth client ID**.
3. Application type: **Web application**.
4. Name: `Networking AI Web`.
5. Under **Authorized redirect URIs**, click **+ Add URI** and add BOTH:
   - `http://localhost:8000/api/integrations/google/callback`
   - `https://YOUR_DOMAIN/api/integrations/google/callback`
     (use the real domain; you can add it later and edit the client).
6. Click **Create**.
7. A dialog shows **Client ID** and **Client secret**. Copy both
   (also downloadable as JSON). Keep them secret.

## 5. Put the credentials into the app
Add to the app's `.env` (locally) or to the `ENV_FILE` GitHub secret (prod):

```
GOOGLE_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxxxxxx
GOOGLE_REDIRECT_URI=http://localhost:8000/api/integrations/google/callback
# In production set this to: https://YOUR_DOMAIN/api/integrations/google/callback
```

`GOOGLE_REDIRECT_URI` must match **exactly** one of the URIs registered in
step 4 (scheme, host, port, path — no trailing slash differences).

## 6. Connect inside the app
1. Restart the app so it picks up the new env values.
2. Open the app → **Integrations** → **Connect Google**.
3. Choose `o.stepeniev@swipescape.eu`, approve the requested permissions
   (read email, send email, read calendar, email address).
4. You'll be redirected back; the panel shows **Connected**.
5. Click **Sync now**. Emails and meetings with contacts (that have an email on
   file) become interactions, and warmth updates.

## Scopes requested by the app
- `gmail.readonly` — read your messages (subjects/snippets/metadata).
- `gmail.send` — send the daily digest email to you.
- `calendar.readonly` — read calendar events.
- `userinfo.email` + `openid` — identify the connected account.

## Troubleshooting
- **redirect_uri_mismatch** — the `GOOGLE_REDIRECT_URI` doesn't exactly match a
  registered URI. Fix one to match the other (watch http vs https, port, path).
- **access_denied / app not verified** — make sure your account is added under
  **Test users**, or publish the app.
- **invalid_client** — wrong client ID/secret, or they belong to a different
  project than the one whose APIs you enabled.
- **Refresh token stops working after ~7 days** — publish the consent screen
  (step 3.6) to remove the Testing-mode expiry.
