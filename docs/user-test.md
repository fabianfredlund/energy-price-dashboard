# Solar Advisor — user test

**One page. Six tasks, about 25 minutes.** Hand the tester the link and this sheet.

---

## Before you start (facilitator)

- **Do not demo the app first.** The whole value is watching someone meet it cold. If you
  explain it, you lose the finding.
- Ask them to **think out loud** — what they're looking for, what they expect, what confuses
  them. Remind them once if they go quiet.
- **Say nothing while they work**, even when they are stuck. Especially when they are stuck.
  Count to ten before helping.
- Note the **browser and whether their system is in dark mode** — the app pins a light
  theme and that has never been checked on someone else's machine.
- You are testing the app, not the person. If they can't do something, that is a result.

---

## For the tester

> **Your role:** you are an energy advisor at Kustsol AB, a solar installer in the
> Gothenburg area. You are sitting at a kitchen table with a customer, Anna, and her laptop
> is open in front of you both.
>
> Work through the tasks below out loud. **If something doesn't work or doesn't make sense,
> say so** — that is exactly what we're looking for. There are no wrong answers and nothing
> you can break.

### 1. The first question
*"Anna uses 18 000 kWh a year, wants 8 kWp on a south-facing roof, and has been quoted
70 000 kr for a battery. In about a minute, tell her whether the battery is worth it — and
what you'd actually say to her."*

### 2. The recommendation
*"Now find the battery size you would genuinely recommend, and say why that one."*

### 3. The neighbour
*"Anna's neighbour has the same house but an east–west roof. What changes for them?"*

### 4. Tomorrow
*"Anna asks what the battery would actually do tomorrow. Read her the answer straight off
the screen."*

### 5. The awkward question
*"Anna asks why it doesn't charge from the grid tomorrow night, when power is cheap."*

### 6. The brother-in-law
*"Anna's brother-in-law is an electrician. He says the payback figure must be wrong. Defend
it or concede it — using only what's on the screen."*

---

## Debrief — ask all three, in this order

1. **"What would you *not* show a customer on this screen?"**
2. **"Which single number would you stake your commission on?"**
3. **"What did you expect to be able to click that you couldn't?"**

Then, once: *"Did anything look broken, overlap, or render oddly?"*

---

## Observation sheet (facilitator)

| | Watch for |
|---|---|
| **1** | Do they find the inputs? Which number do they read first — a value or the payback? Do they say the payback out loud, and with what expression? Do they open Assumptions unprompted? Time to first useful answer. |
| **2** | Do they notice the yearly figures **don't** follow the date picker? Do they watch self-consumption move? Does anyone try 0 kWh to see solar alone? Does anyone treat payback as the thing to minimise? |
| **3** | Do they find the one-line orientation comparison, or do they flip the dropdown and try to hold two numbers in their head? |
| **4** | Do they read the hour ranges correctly — **does anyone say "17 to 20" when the screen says 17:00–21:00?** Do they tell "store solar" apart from "charge from the grid"? **Does anyone multiply the daily saving by 365?** |
| **5** | Does the explanation satisfy them, or do they conclude the tool is broken? Do they discover that a bigger battery makes grid charging appear? |
| **6** | Can they find the four exclusions? Do they find the *nätnytta* warning? Does anyone give up and leave the page? |

**For every task, record:** seconds to a useful answer · where they clicked first · what they
said aloud · **what they got wrong** · what they wanted that isn't there.

---

## What this test is trying to break

Written down in advance so the findings can't be rationalised afterwards:

- **Task 2** tests whether "the date picker only zooms the chart" actually reads that way, or
  whether people think they're changing the yearly figures.
- **Task 3** tests a specific design decision — putting the orientation comparison in one
  caption line rather than a fifth KPI card.
- **Task 4** tests the hour-range format and, more importantly, whether the "one day is not a
  year" guard rail holds. **If a tester multiplies by 365, that guard rail has failed** and
  needs rewriting before anyone shows this to a real customer.
- **Task 5** is the likeliest source of a real fix: an absent feature that has a good reason
  behind it still looks like a bug.
- **Task 6** tests whether the honesty is *findable*, not just present.
