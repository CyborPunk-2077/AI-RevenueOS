# Demo checklist

Ten minutes before showing Sangam to somebody. Not a runbook — see
`docs/OWNER-TEST-GUIDE.md` for the long version.

**No passwords in this file.** The launcher prints what you need, and says
plainly which accounts it applies to.

---

## Before the demo

1. Docker Desktop is running. Check the whale icon is steady, not animating —
   the launcher will stop with a clear message if the daemon is not up.
2. Double-click `RUN_DEMO.cmd`.
3. Wait for the green `Sangam is ready` banner. A clean finish means: Docker
   found, images built, migrations at head, reference data seeded, demo tenants
   seeded, Sangam workspace seeded, API healthy, all four worker pools and the
   scheduler healthy, and the web app answering on `/login`.
4. Open **http://localhost:3000**.

**About the password line.** On a first run the launcher creates the accounts and
prints the password it set. On every run after that the accounts already exist,
**keep the passwords they already had**, and the launcher says so instead of
printing a credential it did not set. That is correct behaviour, not a fault, and
it does not need `RESET_DEMO`. If you have genuinely lost the demo password:

```bash
docker compose exec -e DEMO_PASSWORD=your-passphrase api python src/scripts/seed_sangam.py --reset-passwords
```

That rotates only the seeded demo accounts. It touches no business records.

**Accounts** (Sangam workspace):

| Account | Role | Sees |
| --- | --- | --- |
| `abhishek@sangam.co.in` | Owner | Everything |
| `priya@sangam.co.in` | Manager | Her team's prospects |
| `kiran@sangam.co.in` | Member | Only his own |

`asha@acme.test` and `ravi@globex.test` exist for the tenant-isolation check and
use the password the launcher printed for the demo tenants.

**Optional, and fine to skip:** the WhatsApp provider. The product demonstrates
fully without it. See the WhatsApp section below before deciding.

---

## Owner path — 5 to 8 minutes

Sign in as `abhishek@sangam.co.in`.

1. **Today** — open on this. One sentence: *"this is what needs a call before the
   day ends."* Point at the five figures across the top, then at the grouped
   table: businesses waiting for a first reply, oldest first; follow-ups already
   overdue; who owns what. On a large monitor the At-risk rail sits to the right.
2. **Open one overdue business** from the table. The prospect record: who they
   are, who owns them, what was promised, what has actually happened.
3. **Prospects** — the whole book. Show that the business, the contact person and
   the internal owner are three different columns; a row with no contact shows an
   em dash rather than repeating the business name.
4. **Follow-ups** — the promise queue, overdue first.
5. **Inbox** — a real WhatsApp conversation. Customer messages on the left, ours
   on the right, grouped by run, with the delivery state under our own messages
   in the provider's own words. This is the strongest screen; give it time.
6. **Import** — drag in a CSV and stop on the review step. Nothing is written
   until Confirm, and the screen says what it would do, including duplicates.
   This is the "we will not mangle your list" moment.

   Related, and worth turning into a feature rather than apologising for: the
   prospect list deliberately contains **NestCraft Interiors** and **Nestcraft
   Interior Designs**, same phone number, unmerged. That is what a real
   prospecting list looks like. Both are flagged as duplicate candidates —
   open either record and scroll to **Record maintenance → Possible
   duplicates** to show the match and the merge.
7. **Analytics** — say out loud that the figures are unreconciled against the
   underlying records, because the screen does.
8. **Settings → Integrations** — the honesty screen. Each capability reports on
   four separate axes; nothing shows a green tick it has not earned.

Toggle dark mode once, from the utility bar. It is a real theme, not an inversion.

---

## Manager check — 1 minute

Sign in as `priya@sangam.co.in`.

- Today and Prospects show her team's work, not the whole workspace.
- She can assign and reassign within her team.
- Owner-only administration is not offered to her as a button that then errors.

---

## Member check — 1 minute

Sign in as `kiran@sangam.co.in`.

- Today and Prospects show only his own prospects. This is the "clear ownership"
  claim, demonstrated rather than asserted.
- He can work a customer: log activity, complete a follow-up, reply in the Inbox.
- Administration and configuration are simply not there.

---

## WhatsApp

**If the provider is connected** (tunnel up, token valid): open the Inbox thread
and show a live exchange. Send from the phone and let it appear without a
refresh — that is the demonstration worth making.

**If it is offline** — which is the normal state, because the Cloudflare quick
tunnel is temporary by design and the Meta test token expires every 24 hours —
do **not** try to fix it during a demo. Instead:

- Show the existing conversation. The history is real and reads correctly.
- Open **Settings → Integrations** and show that Sangam says what is actually
  true: runtime connection, when the webhook last received something, what the
  provider said about the last send, and that production activation is not
  claimed.
- The line to use: *"the product does not pretend a message was delivered when it
  was not — that is the whole point."*

Never edit a message status to make a demo look better. A failed message is
evidence the product is honest.

---

## Developer tooling

The **Test Centre** is not in the Settings menu, deliberately — it is internal
tooling and should not read as a product feature during a demo. The route still
works if you open `/test-center` directly. To list it again while developing, set
`SHOW_TEST_CENTRE=true` for the web container.

---

## If something looks wrong

- `docker compose logs -f api web` — the two that matter.
- A blank screen after sign-in usually means the web container is still compiling
  the route on first request. Wait and reload once.
- Do **not** run `RESET_DEMO` during or shortly before a demo. It is destructive,
  it refuses while a pilot workspace exists, and nothing in the list above needs
  it.
