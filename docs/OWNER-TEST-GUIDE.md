# Trying Sangam yourself

Written for the owner, not for an engineer. About ten to fifteen minutes.
You do not need to type any commands.

---

## 1. Start it

1. Double-click **`RUN_DEMO.cmd`** in the project folder.
2. Wait. If Docker is not running, Sangam starts it for you and says so; that
   takes a couple of minutes the first time. After that it is quick.
3. When it finishes it prints a box with a web address and a password, and opens
   your browser at **http://localhost:3000**.

That is the whole procedure. You do not need to start Docker yourself, and you
do not need to type any commands. If Docker Desktop is not installed at all, the
window tells you so in plain English and gives you the download link.

Sign in as:

| Sign in as | You are | You see |
| --- | --- | --- |
| `abhishek@sangam.co.in` | The owner | Everything |
| `priya@sangam.co.in` | A sales manager | Her team's prospects |
| `kiran@sangam.co.in` | A salesperson | Only what is assigned to him |

The password is the one printed in the box.

**Start with `abhishek@sangam.co.in`.** Try the other two later — the point of
them is that they see *less*, which is how you keep a new salesperson away from
the whole customer book on their first day.

Closing the window does not delete anything. Run it again tomorrow and your
records are still there.

---

## 2. What you are looking at

This is a workspace for a fictional business: **Sangam**, an automation
consultancy in Bengaluru selling to other small businesses — the business we
ourselves are building.

The prospects in it are **invented but realistic**: a dental chain in
Indiranagar, a coaching institute in Jayanagar, a logistics operator in Peenya.
None of these people exist. Nothing has been sent to anybody. No message, no
email, no WhatsApp has left this machine.

They are there so you can judge the screens as they would look on a Tuesday
morning in a real office — including the parts that are going wrong, because a
tool for stopping enquiries falling through the cracks cannot be judged on data
with no cracks in it.

---

## 3. The ten-minute walk

### Step 1 — Today

You land on **Today**. Read the four boxes across the top.

- **Overdue follow-ups** — somebody promised to do something by a date that has
  passed.
- **Waiting for a first reply** — somebody asked about your business and nobody
  has actually got back to them.
- **Unassigned prospects** — nobody's name is against them, so everybody assumes
  somebody else is calling.
- **No next action** — the enquiry is live but nothing is scheduled.

*This is the whole product in four numbers.* Every one of them is a count of
records you can open. **Click any box** and it takes you to exactly the prospects
that make up that number — the count and the list always agree.

Underneath is a second row: **how quickly enquiries are answered**. Typical time
to first reply, the longest anyone is currently waiting, and how many of your
enquiries have been answered at all. These are worked out from the calls and
messages your team recorded, so they change when the team's behaviour changes and
at no other time.

Below, look at **Enquiries waiting for a first reply**. Shreya Bhat from
SmileCraft Dental Care has been waiting two days. Nobody has called her.

### Step 2 — Open the one nobody called

Click **Shreya Bhat**.

Read what you get before you would pick up the phone:

- what she actually asked for, in her words
- her number and email
- how big her business is
- that she is **unassigned**
- that **no follow-up is scheduled** — said in red, because that is the problem

### Step 3 — Give it an owner

Under **Ownership and next action**, pick a name from the dropdown and click
**Assign**. It now says who owns it.

This is the least impressive-looking thing on the screen and the one that
prevents the most lost business. "I thought you were calling him" is not a
software problem until somebody writes down whose job it was.

### Step 4 — Score her

Click **Score with rules**.

You get a score out of 100, a warm/hot/cold label, and — importantly — **why**,
plus what is still missing.

Note the sentence underneath: no AI is connected. This is arithmetic on what was
captured with the enquiry. It gives the same answer every time and you can argue
with it. When we do connect an AI later, this still works if the AI is down.

**Look at the red line again.** It still says she is waiting for a first reply.
You have now given her an owner and scored her, and Sangam has correctly refused
to treat either as answering her. This is the single most important behaviour in
the product: the number cannot be improved by tidying your own records.

### Step 5 — Promise a follow-up

Under **Tasks**, type what you will do next — "Call Shreya about the three
branches" — pick a date, and click **Add task**.

Look up: the red warning is gone and the next action now appears against the
record.

### Step 6 — Actually answer her, and watch the measurement appear

This is the step the whole product is built around.

Under **Timeline**, choose **Call**, leave **Who got in touch** on *We contacted
them*, put a subject and a couple of lines of detail, and click **Log activity**.

Now look back up at the ownership panel. The red "waiting for a first reply" line
has been replaced by something like **First reply: 3 hours after the enquiry
arrived**. Sangam measured it from what you just recorded — not from anything
that was set up in advance.

Two things worth trying, because they are what make the number honest:

- Log a second call. The first-reply time **does not change**. The first response
  stays the first one; it cannot be quietly restated later to look better.
- On another waiting prospect, log a call but set **Who got in touch** to *They
  contacted us*. It stays waiting — because the customer ringing you is the
  enquiry, not your reply to it.

The activity itself appears with your name and the time on it. **You cannot edit
or delete it afterwards, and neither can anyone else.** A record of a call that
can be rewritten later is not a record. Notes are separate and *can* be edited —
but only by the person who wrote them, and a note never counts as a reply.

This history stays with the customer when they stop being a prospect and become
a customer. The context does not restart.

### Step 7 — The shared queue

Click **Follow-ups** in the menu.

This is everything anybody has promised to do, soonest first, with who owns it.
Click **Overdue**. These are the broken promises.

Click **Done** on one.

### Step 8 — Watch the number move

Click **Today**.

The **Overdue follow-ups** count has gone down by one.

That is the test of whether a dashboard is real. If closing a task does not
change the figure the owner is judged on, the figure is decoration.

### Step 9 — The duplicate

Go to **Prospects**. Notice there are two Farhans — "Farhan Qureshi" from
NestCraft Interiors and a bare "Farhan" from Nestcraft Interior Designs. Same
person, enquired twice, once by referral and once through the website chat.

Open either one and scroll to **Possible duplicates**. It is flagged with the
reason and how confident the match is, and left for a person to decide.

It is deliberately *not* merged automatically. Silently merging two customers who
turn out to be different people is much harder to undo than merging them by hand.

### Step 10 — The pipeline

Click **Deals**.

Deals by stage, in rupees. One was won. One was lost — and the lost one records
*why*, which is the only part of a lost deal worth keeping.

### Step 11 — What is and is not real

Go to **Settings**, then **Test Centre**.

This is an internal page. It lists every part of the product and says honestly
whether it is usable, half-built, or waiting on an outside account. The bottom
table is checked live each time you open it — so when it says WhatsApp cannot
send, that is the system reporting its own state, not a claim we typed in.

---

## 4. Start using Sangam for our real prospecting

The walk above uses invented businesses. This section is for putting **real** ones
in. Everything below is ready to use today.

Sample businesses are labelled **sample** in the prospect list, so your own
entries are never confused with the demonstration ones.

### 1. Add one real business

**Prospects → Add a business.** You need a business name and one way to reach
them — a phone number is enough. That is the whole required form; it takes about
fifteen seconds.

Click **More details** if you already know the contact person, the area, what they
do, or why you think they need us. If you do not, leave it. You can add it later.

### 2. Import a list

**Import** in the menu.

If you have never made one of these files, click **Download the template** first.
It has three example businesses in it. Delete them, type your own in, save, and
upload it. Columns you do not have can stay empty or be deleted entirely.

Nothing is saved until you press the button. Before that, Sangam shows you:

- **How the first rows will be saved** — the tidied-up phone numbers and names, so
  you can see it read your file correctly
- **Already in Sangam** — businesses you already have, and *why* it thinks so
- **Rows that will not be imported** — with the reason, so you can fix the file

Only CSV files work. If you have an Excel file, use *Save As → CSV UTF-8*.

### 3. Understand the duplicate warnings

If a business you are importing has the same phone number or email as one you
already have, Sangam will **not** import it again and will **not** change your
existing record. It shows you which one it matched and on what.

This is deliberate. Your existing record keeps its owner, its notes and its call
history. Nothing is ever merged automatically — two shops can genuinely share a
landline, and an unpicked merge is much harder to undo than a duplicate.

### 4. Find out who to contact today

**Today.** The four boxes at the top are your morning. Click **Waiting for a first
reply** to get the list of businesses nobody has spoken to yet.

Further down: what is overdue, what is due today, and who you have already
contacted this week — so you do not ring the same shop twice.

### 5. Make the call yourself

Ring them, send the WhatsApp message, or write the email — on your own phone or
laptop, as you do now. **Sangam does not send anything.** It is your record of
what happened, not a sending tool.

### 6. Record what happened

Open the business, go to **Record an outreach you made**, and fill in:

- what kind of contact it was
- **We contacted them** (or *They contacted us*, if they rang you)
- how it went
- a line or two of detail
- **and what happens next**, with a date

One save does all of it. The next action becomes a follow-up automatically — no
second form.

**What actually happened** is now a proper answer, not a note to yourself. Pick
*Spoke with them*, *No answer / missed*, *Meeting happened*, *Scheduled for
later*, *Sent it*, and so on.

This is the part that decides whether the business counts as answered:

- **Spoke with them**, a message you actually sent, or a meeting that took
  place — that business has been answered, and Sangam records how long it took.
- **No answer**, a meeting only booked for later, or a message that failed to
  send — the business is still waiting, and Today keeps saying so.

That is deliberate. A number nobody picked up is a real attempt and it is worth
recording, but it is not a reply, and a dashboard that treats it as one would be
telling you a comfortable lie.

One thing that surprises people: if a customer rings **you** and somebody
answers, that *does* count. Choose *They contacted us* and *Spoke with them*. A
missed call from them does not.

### 7. Come back tomorrow

Your promise is on **Today** and in **Follow-ups**. When you have done it, press
**Done** and the count drops.

If you never record the follow-up, Sangam keeps showing it as overdue. That is the
entire point of the product.

### 8. When it goes somewhere — or does not

If the business becomes a real opportunity, open **Deals** and add it, with a
rough value and a stage. Move it along as things progress, and mark it won or
lost. If it is lost, write *why* — that is the only part of a lost deal worth
keeping.

If a business is simply not for us, open it, change the status to **disqualified**
and give a reason. It leaves your daily lists but stays on record.

---

## 4b. Run a shadow pilot

A shadow pilot is one real business using Sangam alongside how they already work.
They keep making their own calls and sending their own messages. Sangam
coordinates the work and measures it. Nothing is taken away from them, so there
is nothing for them to lose by trying it.

**1. Give the business its own workspace.**
Ask for one to be set up for them by name. It is completely separate from ours:
their staff cannot see our prospects and we cannot see theirs. Nothing in their
workspace is sample data — it starts empty on purpose, because the whole value of
a pilot is that the numbers mean something.

**2. Add their people.**
The owner sees everything in their business. A manager sees their team's work. A
salesperson sees their own. Set these up before anybody starts, because "who owns
this enquiry" is most of what the product is for.

Sangam cannot email an invitation — no email account is connected — so you will
be given their sign-in details to hand over yourself. Tell them to change the
password once they are in.

**3. Put their enquiries in.**
Either add businesses one at a time, or import a spreadsheet saved as CSV. The
import shows you what it will do before it saves anything: which rows are new,
which ones they already have, and which cannot be used and why. Anything they
already have is left completely alone.

**4. Capture the Starting Baseline — before anybody starts working the list.**
On **Today**, press **Capture the starting baseline**. This records where they
are on day one: how many enquiries are waiting for a reply, how many have nobody's
name against them, how many follow-ups are already late.

Do this *first*. Once people start working, the "before" picture is gone, and
without it every later conversation is an argument about what things used to be
like.

If there is not enough history to say something honestly — nobody has been replied
to yet, so there is no typical response time — Sangam says exactly that instead of
printing a zero.

**5. Let them work the way they already do.**
Phone calls on their own phones. WhatsApp from their own handsets. Nothing about
this changes on day one.

**6. Ask them to record what happened.**
After each call or message: what it was, who got in touch, and what actually
happened. It takes seconds. This is the only habit the pilot depends on, and it
is worth saying out loud: Sangam measures what gets recorded, not what happened.
A call nobody logs leaves that customer showing as waiting.

**7. Ask them to write down what happens next.**
The same form takes the next action and a date. Most calls end with a promise, and
a promise written down ten minutes later is usually a promise not written down.

**8. Have them start each day on Today.**
What is overdue, who has never been replied to, who has no owner, who has nothing
scheduled. That screen is the product.

**9. Watch for the work that is slipping.**
The useful conversation in week one is not about the numbers going up. It is
"these four people enquired and nobody has got back to them" — which is usually
news, and usually fixable the same afternoon.

**10. Only compare later, after real use.**
Come back to the Starting Baseline after several weeks of genuine use. Both
columns are counts of records you can open and read.

**11. Do not turn any of this into a revenue claim.**
Not to them, not to anybody else. We can say fewer enquiries went unanswered, and
we can show which ones. We cannot say we increased their sales — nobody has
measured that, and the first person to ask a hard question about it will find out
in about a minute.

---

## 5. The isolation check — worth doing once

This is the one that matters if you ever sell this.

1. Sign in as `abhishek@sangam.co.in` and open any prospect.
2. Copy the web address from the browser bar.
3. Sign out. Sign in as `ravi@globex.test`.
4. You see none of Sangam's records.
5. Paste the address you copied. You get **Not found** — not the record.

That is not the screen hiding things. It is enforced three separate times,
including inside the database itself, so even a mistake in our own code cannot
show one business another business's customers.

---

## 6. What is deliberately not there yet

Being blunt is the point of this section.

- **WhatsApp, email and SMS cannot send.** The plumbing exists; no account is
  connected. Nothing will ever say "sent" when it was not.
- **No AI.** Qualification is rules-based. Everything above works without it.
- **No file uploads or payments.** Both need external accounts we have not opened.
- **Appointments** can be recorded but no calendar is connected.
- **Reports** draw charts, but the numbers behind them have not been checked
  against the records yet. Do not quote them to anybody.
- **Importing a spreadsheet** exists but has not been run on real data. Treat it
  as untested.
- **Automations** run underneath, but there is no screen to build a rule.

The trustworthy part today is: **enquiry → owner → score → next action →
follow-up → history → deal**, and the measurements that come out of it — who is
waiting, how long they waited, what is overdue, what has no owner and what has no
next action. That path has been walked end to end in a browser, and the
screenshots are in `artifacts/visual-evidence/`.

One caution worth stating plainly: Sangam measures **what your team records**. If
somebody phones a customer and never logs it, Sangam will keep saying that
customer is waiting. That is the honest behaviour — the alternative is a system
that guesses — but it does mean the numbers are only as good as the habit of
writing things down.

---

## 6b. Your password after a restart

Starting Sangam again **never changes anybody's password**. Whatever you signed in
with yesterday still works today.

That was not always true: an earlier version reset every password each time the
stack started, so starting it without setting one first quietly locked the
founders out of their own workspace. If you ever genuinely want to reset
everybody's password, it is now a deliberate command rather than a side effect of
starting up — ask for it by name.

## 7. If something goes wrong

**It says Docker is not installed.** That is the one thing Sangam cannot do for
you. Install Docker Desktop from the link in the message, restart the computer if
it asks, then double-click `RUN_DEMO.cmd` again.

**It sat at "waiting for Docker to finish starting" and then gave up.** Docker was
part-way through an update. Wait a minute and double-click `RUN_DEMO.cmd` again.

**"Too many attempts."** Sign-in allows five tries per fifteen minutes from one
computer. Wait a quarter of an hour. This is on purpose — it is what stops
somebody guessing passwords.

**You want a clean slate.** Double-click `RESET_DEMO.cmd`. It deletes *everything*,
including any real businesses you have entered. It now checks first: if you have
real prospects it tells you how many, points you at the safe alternative, and
makes you type a different phrase to go ahead. It also takes a backup first.

**You only want the sample businesses put back.** That is the safe refresh, and it
cannot touch anything you entered yourself. Ask for it rather than using
`RESET_DEMO.cmd`.

**Where backups live.** Before anything destructive, Sangam writes a snapshot into
the `backups` folder in the project. Ten are kept. If a snapshot cannot be written,
the destructive action does not run at all.

**You want the demo prospects back the way they started** (with the overdue items
freshly overdue), without deleting your own records elsewhere — ask for the
workspace to be refreshed; it is one command and it only touches the Sangam
workspace.
