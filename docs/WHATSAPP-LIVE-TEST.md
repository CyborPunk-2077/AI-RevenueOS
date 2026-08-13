# Running one real WhatsApp test

Everything Sangam can do without Meta is done. This document covers the part that
needs a person, because it genuinely does: Meta requires a human to log in, accept
legal terms, pass two-factor authentication and confirm ownership of a phone
number. None of that can or should be automated, and nothing here tries to.

Last updated: **2026-08-13** (session 5).

---

## What this test proves

One message, in each direction, through the real WhatsApp Cloud API:

```
your test phone
  → sends a WhatsApp message to the business number
  → Meta calls Sangam's webhook
  → the sender is matched to a prospect, or a new one is created
  → the message appears on that prospect's timeline, and they show as WAITING
  → an employee opens the prospect and sends a reply from Sangam
  → Meta accepts it and returns a message id, which is stored
  → only now does the prospect count as answered
  → delivery and read receipts arrive later and update the message
```

The interesting assertion is the fifth line. An inbound message is an **enquiry**,
not a reply. Until somebody genuinely answers, Today keeps saying that customer is
waiting — which is the whole product.

---

## Number policy — read this before touching anything

**Do not convert the founders' personal WhatsApp number.** Registering a number
with the Cloud API removes it from the normal WhatsApp app on that handset. That
is not recoverable in an afternoon and it is not worth it for a test.

In order of preference:

1. **Meta's own test number.** A new Meta app comes with a free test business
   number and a small allowance of test recipients. Nothing to buy, nothing to
   verify, and no real number is consumed. This is the right choice.
2. **A spare SIM the team controls** — an old handset, a second business line.
3. Never a customer's number, and never a number belonging to anybody who has not
   explicitly agreed to receive the test.

The personal phone is fine as the **customer** side: it sends the inbound message
and receives the reply. It is only the *business* side that gets registered.

---

## What a person has to do at Meta

Claude cannot do any of these, and did not attempt them. Each one is a deliberate
human gate.

1. Sign in at **developers.facebook.com** with a Facebook account, including any
   two-factor prompt.
2. Create an app of type **Business**, and add the **WhatsApp** product to it.
3. Accept the WhatsApp Business Platform terms.
4. From **WhatsApp → API Setup**, note:
   - the **Phone number ID** of the test number,
   - the **temporary access token** (24 hours — fine for a first test),
   - the **App Secret**, from *App settings → Basic*.
5. Add your own phone number to the **recipient list** on that page and confirm
   the code WhatsApp sends you. Meta will not deliver to an unlisted number while
   the app is in development.
6. Later, in **Configuration**, set the webhook URL and verify token (below) and
   subscribe to the **messages** field.

Steps 1–5 take about ten minutes. Nothing in Sangam needs to be running for them.

---

## Making the local webhook reachable

Meta will only call a public HTTPS address, and Sangam runs on a laptop. A
temporary tunnel is the honest way to bridge that for a test; it is not a
deployment and it should be shut down afterwards.

Two properties matter and neither is negotiable:

- **The tunnel exposes the API, not the whole machine.** Point it at
  `http://localhost:8000` only. The web app, the database and the workers stay
  where they are.
- **Signature verification stays on.** Every webhook call is checked with
  HMAC-SHA256 against the App Secret before a single row is written, and an
  unsigned or wrongly signed call is refused. A public URL does not weaken that,
  which is exactly why exposing it is acceptable.

Any reputable tunnel will do. `cloudflared` needs no account for a quick tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

It prints an `https://<something>.trycloudflare.com` address. **A person must
install and run this** — it is third-party software and a network exposure, so it
is not something to set up on somebody's behalf without asking.

Give Meta:

- **Callback URL**: `https://<your-tunnel>/v1/webhooks/inbound/whatsapp/whatsapp_cloud`
- **Verify token**: whatever you set as `WHATSAPP_VERIFY_TOKEN` below

Meta immediately GETs that URL with a challenge. Sangam echoes it back only when
the token matches, so a wrong token fails at this step rather than silently later.

---

## Telling Sangam the credentials

Set these where the API can read them, then restart it. They are secrets: they do
not belong in Git, in a screenshot, or in a chat message.

| Setting | Where it comes from |
| --- | --- |
| `AIREVENUEOS_WHATSAPP_PHONE_NUMBER_ID` | Meta → WhatsApp → API Setup |
| `AIREVENUEOS_WHATSAPP_ACCESS_TOKEN` | Meta → WhatsApp → API Setup |
| `AIREVENUEOS_WHATSAPP_APP_SECRET` | Meta → App settings → Basic |
| `AIREVENUEOS_WHATSAPP_VERIFY_TOKEN` | You choose it; give Meta the same string |
| `AIREVENUEOS_FEATURE_WHATSAPP_ENABLED` | `true` |

Then **claim the number for the workspace**. This is the step that is easy to
miss and produces the most confusing failure — an inbound message with no
workspace to belong to is refused, deliberately, rather than filed into whichever
tenant happened to be first:

```bash
docker compose exec api python src/scripts/claim_whatsapp_number.py --slug <workspace> --phone-number-id <id>
```

The Test Centre's **Real WhatsApp test** section reports all of this back. It will
not say `CONNECTED` until a live call to Meta with those credentials has actually
succeeded — pasting a token in is not enough to turn it green.

---

## Running the test

1. Open the Test Centre. Confirm **Connection: CONNECTED** and that the business
   number shown is the one you expect.
2. From your test phone, send a WhatsApp message to the business number.
3. Refresh **Prospects**. A new prospect appears, named from your WhatsApp profile
   and carrying your number. Open it: the message is on the timeline, and the
   prospect is marked **waiting for a first reply**.
4. Reply from the prospect page.
5. The reply arrives on your phone. The prospect is now answered, and the time to
   first reply is recorded.
6. Watch the message status move to delivered, then read, as Meta sends the
   receipts.

If step 3 does not happen, check in this order: the tunnel is still up; Meta shows
the webhook as subscribed to **messages**; the number is claimed for the
workspace. The API log names the reason for every refused event.

---

## What is deliberately not built

- No bulk sending, no campaigns, no cold messaging. One conversation at a time,
  with somebody who messaged first.
- No chatbot and no automatic replies. A person writes every reply.
- No template management. The first test uses a plain text reply inside the
  24-hour window that the customer's own message opens.

---

## After the test

Stop the tunnel. Rotate the temporary access token or let it expire. If the pilot
does not proceed to real WhatsApp use, set
`AIREVENUEOS_FEATURE_WHATSAPP_ENABLED=false` — every path then reports "not
configured" and nothing anywhere pretends a message was sent.
