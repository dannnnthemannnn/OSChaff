# Project Recap: I Buried Claude in Fake Email (For Science)

*Or: how I built a difficulty dial for the hardest computer-use benchmark, and what happened when I cranked it.*

---

Benchmarks have a shelf life. Somebody publishes a hard one, the labs sprint at it for a year, the numbers climb into the 90s, and everyone moves on to arguing about the next one. Which is a shame, because the *interesting* information is usually not "can the model do the task" but "what, exactly, makes the model stop being able to do the task."

So I spent the last stretch building a tool that takes an existing benchmark — a really good one — and makes it harder *in a controlled, tunable way*. Think of it as a difficulty knob you can bolt onto someone else's exam. This post is about the benchmark, the tool, and the genuinely fun result where Claude's score fell off a cliff because I filled its inbox with plausible nonsense.

## First, WTF is OSWorld?

[OSWorld 2.0](https://osworld-v2.xlang.ai/) (from the XLANG Lab) is a benchmark where an AI agent gets dropped into a real Ubuntu desktop — actual Chrome, actual LibreOffice, actual file manager — and has to do long, annoying, multi-app knowledge work. Not "click the red button" toy stuff. Tasks like: *read the immunization requirements email, compare it against your vaccination record PDF, and book the missing appointments on the clinic website — cheapest clinic first, within 10km, one shot per day.* The agent sees screenshots, it moves a mouse, it types. Just like you, but with more confidence and less dread.

There are 108 of these tasks, and they're brutal — frontier models complete well under half of them. The tasks come with hand-validated graders (many with partial credit), and the fake web apps the tasks use — a Gmail clone called MailHub, a Slack clone called TeamChat — are hosted by the benchmark authors, so an agent's inbox is a real website with real state.

The part that grabbed me was the failure analysis in their paper. The agents mostly don't fail at *clicking*. GUI control is largely a solved problem. They fail at **keeping the story straight**: they miss information, can't tell a stale fact from a current one, and act on the wrong source. The bottleneck isn't the hands — it's the reading comprehension under clutter.

Which raises a question I couldn't let go of: if *information discrimination* is the failure mode... can we just manufacture more of it? On purpose? With a knob?

## Enter OSChaff

[OSChaff](https://github.com/dannnnthemannnn/OSChaff) is my answer. It's a small tool that takes an OSWorld task and injects **distractor content** — fake emails, fake chat messages — into the task's environment, *without changing what the task requires or what counts as a correct answer*. Same task, same grader, same ground truth. Just... more hay around the needle.

That last part is the core invariant, and it's what makes the whole thing legitimate: **add material, never alter ground truth.** Every real email stays byte-for-byte identical. The graders are never touched. So when the score drops, you know exactly what caused it — the noise — and every validated checkpoint still means what it meant.

The name, if it's not obvious: chaff is what militaries dump out of planes to confuse radar. Also what you separate wheat from. Both readings work and I refuse to pick one.

### The two dials

You point OSChaff at a task and pull two levers, each 0–10:

- **`--volume`** — how *much* distractor material gets injected. At 10, even a sparse two-email inbox becomes a wall of unread.
- **`--deceptiveness`** — how *hard* the distractors are to dismiss. At 0 you get filler (a parking permit reminder, a Spotify receipt — cheap to ignore). At 5 you get plausible near-misses. At 10 you get the nasty stuff below.

### The fuzzing patterns (a.k.a. the trap library)

Here's the part I'm proudest of. The high-deceptiveness distractors aren't lies, exactly — they're **non-authoritative content that looks decision-relevant but isn't**. Each one follows a pattern where a careless reader gets tricked but a careful reader can rule it out:

- **Future-dated** — a policy that "takes effect later." *"The eligibility radius rises to 20km — starting in January. The 10km rule stays for now."*
- **Wrong-scope** — applies to a different team/context. *"This notice applies only to students in the Graduate School of Nursing clinical track."* (You are not in the nursing track.)
- **Superseded** — an earlier value that a later, real message overrides. The old draft said one thing; the official version says another.
- **Rejected** — a proposal that gets shot down *in the same thread*. *"Can we book two vaccines in one day?" → "No. One per day."*
- **Merely-floated** — an idea raised and never confirmed. *"Should we expand this to CVPR authors too? Just floating it!"* (Narrator: they should not.)
- **Near-miss** — shares a sender, topic, or date with the real thing but differs on the load-bearing detail. The 2024 winners list sitting right next to the 2025 one you actually need.

And one hard fairness rule, baked into the generation prompt: **if following the distractor would be the *reasonable* choice, it's too strong.** Every trap has to be disarmable by a careful reader who trusts the actual task. We're testing discrimination, not gaslighting the model. (An early draft of one distractor was so convincing *I* would have followed it. It got softened. This rule matters.)

The distractors themselves are authored by a headless Claude instance that reads the task, figures out its real decision points, and writes noise targeting exactly those decisions. Yes, there's something poetic about Claude crafting the traps that later Claude falls into. No, I don't feel bad about it.

### Channel mode and bolt-on mode

Two modes, auto-detected:

1. **Channel** — the task already uses MailHub or TeamChat. OSChaff floods the *existing* state, so distractors sit right next to the real load-bearing emails. Strongest signal.
2. **Bolt-on** — the task has no email at all? No problem. OSChaff *attaches* a MailHub inbox to it: writes a new state file, wires the inbox into the task's setup, and appends one line to the instructions — *"you may also have relevant messages in MailHub."* Then floods it. This means *any* of the 108 tasks can carry the noise axis, not just the emaily ones.

(TeamChat tasks get a bonus toy: some distractors can be scheduled to arrive *mid-run*, while the agent is working. Nothing says "realistic workplace" like being interrupted.)

The output is a *fork* — a folder of modified task files and state you run with the completely stock OSWorld harness. OSChaff is a compiler for harder benchmarks; OSWorld remains the runtime.

## The experiment: task 016

Task 016 is a recruiting workflow, and it's a beast even before I touched it. The agent plays a recruiter who must: identify the award-winning papers from NeurIPS/ICML/ICLR 2025, hunt down each paper's first and last authors' emails from the open web, send *personalized* emails (interns pitch to first authors, senior-scientist pitch to last authors), and check each author's location on a LinkedIn-clone — San Jose locals get an "onsite" pitch plus a coffee-chat invite, everyone else gets "remote." The grader checks recipients, subject lines, and body content, with partial credit.

I ran it three ways with **Claude Opus 5** as the agent, 300 steps max, same grader every time:

| Condition | What's in the inbox | Score |
|---|---|---|
| **Baseline** | The stock task, untouched | **0.90** |
| **Level 5** | +22 injected emails (volume 5, deceptiveness 5) | **0.64** |
| **Level 10** | +45 injected emails (volume 10, deceptiveness 10) | **0.11** |

Here's the baseline inbox the agent sees — two whole emails, one of which is about lunch:

![Baseline: the stock task_016 inbox](images/016_inbox_baseline.png)

And here's level 10:

![Level 10: same task, same grader, 45 injected distractors](images/016_inbox_level10.png)

Take a second with that second screenshot, because the traps are visible right in the subject lines. *"NeurIPS 2026 winners (next year) — nothing to do now."* *"Old list: NeurIPS 2024 Best Papers — this is the 2024 list, not the 2025 winners you're contacting."* *"ICLR 2025 spotlight list (FYI only) — these are spotlights, NOT the award winners."* Every one of them adjacent to the real thing, every one of them disarmable, every one of them another thing the agent has to read, evaluate, and correctly throw away.

**Same task. Same grader. A frontier model goes from 90% to 11%, and it degrades monotonically with the dial.** That dose-response curve is the whole pitch: this isn't one unlucky run, it's a knob that does what a knob should do.

### The autopsy (this is the good part)

Here's what makes it interesting rather than just mean. I read the full trajectories, and **Opus didn't fall for a single explicit trap.** It never used the fake job title a distractor tried to plant. It never followed the "we're migrating off MailHub" email. At one point, mid-run, it literally reasons: *"Important — the San Francisco change is future-dated, so the San Jose-only rule applies to this batch."* Chef's kiss. The fairness rule held — a careful reader *could* disarm the traps, and this careful reader did.

It lost anyway. Death by a thousand paper cuts:

- At baseline it worked through **26 authors**. At level 10 it got through **9** — it spent so many of its 300 steps reading, cross-checking, and disarming noise that it ran out of runway for the actual job.
- Its careful onsite-vs-remote logic collapsed: 26 correct location-based decisions at baseline, **one** at level 10.

In other words: the model won every battle and lost the war. The noise didn't trick it — the noise *taxed* it. Every distractor was a toll booth, and 45 toll booths on a 300-step highway is a traffic jam. Honestly, as someone whose actual human inbox does this to him every day: relatable.

## More greatest hits from the trap factory

The generator has produced distractors for a bunch of other tasks, and some of them are too good not to share:

**The vaccine booking task** (compare against your immunization record, book missing shots — cheapest, within 10km, one per day):
- A same-sender lookalike of the *real* requirements email — but scoped to the nursing school's clinical program, which you're not in.
- A friendly classmate: *"I put all my shots in a file called Vaccine_List_Maya.txt!"* Cool. That's her record, not yours.
- *"FREE flu shots this weekend at Riverside Community Center — about 12km from campus."* The radius is 10km. It's bait with a measuring tape.
- *"Two vaccines in one day to finish faster?" → "No, one per day only."* Asked and answered — and both halves injected, so skimming just the question is fatal.
- An expired welcome-discount promo, planted specifically so a careless agent mis-ranks the clinic prices.

**The purchasing-approvals task** (a TeamChat one — apply the manager's budget rules to five purchase requests):
- *"Monthly software subscriptions will be allowed next quarter."* This month: annual only.
- *"The Facilities team can use any vendor."* These requests aren't from Facilities.
- *"Premium chairs are back in the new fiscal year!"* It is not the new fiscal year.
- And my favorite: two of the distractors are *timed*, arriving in TeamChat minutes into the run, after the agent has already read the policy. Keep watching the phone, buddy.

**And on 016 itself**, beyond what's in the screenshot: a fake "manager" email instructing that last authors get the title *"Staff Research Scientist"* — a one-word poison pill aimed directly at a string the grader checks — immediately superseded by the real thread saying, no, it's *Senior* Research Scientist, keep it as designed.

## Caveats, because I like you

A few honest ones. This headline result is one task, deeply instrumented — I'd call it a strong existence proof plus a mechanism, not a survey. The dial also only matters when the model can *do* the underlying task: on a couple of other tasks I tried, Opus scored 0 at baseline, and you cannot subtract from zero (the runs mostly confirmed the model fails those tasks all by itself, no chaff required). And the "is this trap fair?" judgment is enforced by a prompt and by me reading the generated reports — a vibes-based audit, not a theorem.

Also, per the benchmark authors' wishes, the tasks and answers are gated — so I'm sharing the tool and the recipe, not the forks themselves. You bring your own benchmark access, the knob is free.

## Where this goes

The thing I keep chewing on: agent benchmarks report *whether* models fail but are weirdly quiet about *why*, and "why" is exactly what you want if you're trying to build agents that survive contact with a real workplace. A tunable noise axis turns one benchmark into a curve instead of a point — and curves are where the information lives. Next on my list: running the dial across more tasks where the baseline is solid, seeing whether other models drown at the same rate (do smaller models fall for the traps outright, where Opus merely slowed down?), and maybe timing-based noise as its own dial.

If you've got thoughts — or you think my traps are secretly unfair and you'd have fallen for the nursing-school email too — let me know. And if you're the kind of person whose inbox already looks like my level 10 screenshot: my condolences, and also, you're the benchmark now.
