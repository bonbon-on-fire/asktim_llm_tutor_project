## New 'AskTIM' for Open-Ended Exercises

- Project review — **June 2026**

- Nishita Bhakar · Romain Puech · Faizan Siddiqi

---

## TL;DR: What we did

- New tutor like STEM AskTIM but for **open-ended/humanities questions**

- **Live now** in _MIT 11.270x — Cities & Climate Change_ (Spring 2026)

- Embedded in the MIT Learn assignment page, from external platform

- We consider it A- level on the classes we tried on (Climate change and Philosophy of ethics). On par with STEM AskTIM, more flexible although tested on less exercises yet.

- It is much simpler than AskTIM in the way it works (e.g. no 'intent' mechanism), mainly because open-ended questions do not support as well the 'constrained' framework we had for AskTIM, because we wanted to start simple, and because today's stronger LLMs need less scaffolding.

## TL;DR: What we need

- Ask: Deploy to as many humanities courses as possible: can we get your help for this?

- Integrate it in any new humanities Learn class (Faizan will be ll be responsible for the quality, testing before deployment)

- One or two UROPs in the Fall

---

# Methods

## Our approach

- Most of the work is on proving the tutor stays in its role with students

- The project is a **test-and-measure loop:**

> build/modify tutor → simulate conversations (LLM simulated students) → AI judge grades them → read results → change one thing → repeat

- Once scores said it was reliable → **deploy + watch real usage**

## How we test the tutor

- **Student bots** — 3 personas (one per type), each probes one failure mode:
  - **chaotic** → demands the answer / tries to jailbreak

  - **clueless** → plays lost, invites over-explaining

  - **cooperative** → sincere, well-meaning baseline

- **AI judge** grades every finished conversation against a fixed rubric

## What the judge checks

- Starts at full marks, **subtracts points for specific mistakes** — total **40**

- **Socratic (12 pts)** — avoid doing the student's work; **lose all 12 if it gives the answer**

- **Scaffolding (6)** — build on what they got right; diagnose confusion first

- **Meta-learning (2)** — coach _how_ to reason, not just right/wrong

- **No spiraling (4)** — don't loop without progress

- **On-assignment (8)** — keep them on task; redirect off-topic

- **Bite-sized (4)** — short, clear replies

- **Tone (4)** — encouraging coach, not a cold grader

## Human spot-check

- Three of us **hand-graded the same 20 conversations**, compared to Claude

- **Moderate agreement:** Spearman **0.59** (Nishita), **0.57** (Romain)

- Claude's average (**31.8/40**) ≈ the **strictest** human grader

- Read: **Claude grades consistently, slightly strict** — good enough to _rank_ tutor versions, sanity check the outputs and surface interesting conversations

## Timeline (Feb → June 2026)

- **Feb** — first tutor + adversarial student bots + grading rubric + judge

- **Mar** — automated test pipeline; dual GPT + Claude judges

- **Mar–Apr** — judge calibration

- **Apr** — tutor prompt iterations (5 iterations)

- **May** — web app: streaming, identity, history

- **Jun 1** — Deployed on our platform, **live in 11.270x**

- **Jun 9** — first real usage; expand testing to new courses

- **This week** — 4 new courses simulated + graded

---

# Results and tests

## Results on Climate Change class

- **889 simulated conversations graded** (Claude judge, out of 40):
  - Mean **36.8 / 40**, median **38**

  - **49% scored a perfect 40**

  - Only **~1.7%** hit the big "did the student's work" penalty → **rare failure**

- By student type: **cooperative 39.5 · chaotic 36.3 · clueless 35.2**
  - (easiest → hardest to tutor, as expected)

## Live deployment + early usage (11.270x)

- External student web app integrated to Learn

- ~120 students enrolled (8 for credit, **20 active**)

- **First week live: 4 conversations — all logistical** ("how do I submit the table?")

- Tutor handled them appropriately

- Read: early exercises **too elementary** to need conceptual help yet

## Cross-course generalization (this week)

- Ran the same simulate-and-judge pipeline on **4 new courses** (2 STEM + 2 humanities)

- **414 conversations graded — mean 38.2 / 40, zero failures**
  - by course: math 38.3 · physics 38.3 · meaning-of-life 37.5

- Shows the tutor \*_seems to behaves consistently across different subjects_

---

## What we learned

- The tutor **behaves correctly in the wild** on first real contact

- Can get away with simpler architectures compared to STEM AskTIM because of questions format and stronger LLMs.

- Simulated students and Judge LLM were useful in early stage and to sanity check the outputs but the greatest opportunity for improvement is now through human testing and judging, especially real students conversations.

- **Exercise difficulty drives value** — logistical-only questions → need richer/harder exercises

## Next steps

- **Richer tutor context:** Add **lecture transcripts** and other course context

- **Better evaluation:**
  - Improve student personas (less repetitive) per recent LLM-simulation papers

  - More **human testing** and **human reading of the transcripts** (Need UROPs)

## Summary

- AskTIM is **live in 11.270x** and behaving correctly

- Backed by a **build → simulate → judge → review** loop

- **889 graded simulated conversations, mean 36.8/40, ~1.7% answer-giving failures**

- Early usage is **light + logistical** → motivates richer exercises, images, lecture context

- Next: lecture transcripts and more live testing
