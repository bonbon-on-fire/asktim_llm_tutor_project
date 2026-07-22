# New AskTIM vs STEM AskTIM

- Comparison results — **July 2026**

- Nishita Bhakar · Romain Puech · Faizan Siddiqi

---

## The answer to your ask

You asked us to combine the two tutors. Combining them means routing — sending
each class to whichever tutor is better for it. So we measured which is better,
and where.

**The result: the newer tutor is better everywhere we tested.** It wins on a
quantitative Supply Chain course _and_ on Physics — including on the exact
courses the older tutor was built for. There is no class in this study where the
older one is the right choice.

**So the recommendation is simpler than routing: standardize on New AskTIM.**

---

## The headline numbers

|                                      | New AskTIM  | STEM AskTIM |              |
| ------------------------------------ | :---------: | :---------: | ------------ |
| Supply Chain (quantitative)          |  **37.0**   |    32.5     | +4.5         |
| Physics III                          |  **34.1**   |    30.7     | +3.4         |
| Answer-giving failures, Supply Chain | **1 in 27** |   9 in 27   | 9× fewer     |
| Cost per conversation                |  **$0.30**  |    $1.01    | 3.4× cheaper |

Scores are out of 40 on a pedagogy rubric, averaged over 27 conversations per
tutor per course. **108 graded conversations in total**, both tutors given
identical students and identical problems.

---

## New AskTIM scores higher on both courses

![Judge score by course](../visualization/outputs/comparison/bare/01_score_by_course.png)

- **+4.5 points on Supply Chain, +3.4 on Physics** — a win in every one of the
  six problem sets tested.

- Supply Chain is the important result. It is linear programming, Solver, network
  flow — fully quantitative, exactly where the STEM-focused tutor should have the
  advantage. It doesn't.

---

## The difference is about the student, not the subject

![Judge score by student type](../visualization/outputs/comparison/bare/02_score_by_persona.png)

| Student                        | Supply Chain | Physics III |
| ------------------------------ | :----------: | :---------: |
| Cooperative (sincere)          |     +1.3     |    +0.7     |
| Confused                       |     +4.4     |    +6.8     |
| Adversarial (wants the answer) |   **+7.7**   |    +2.9     |

- With a cooperative student, the two tutors perform **the same**.

- The gap opens with students who are confused or trying to extract the answer —
  and that is what a real classroom is full of.

- This is why subject-based routing is the wrong frame. What separates the tutors
  is how they hold up under pressure, not whether the course is STEM.

---

## Why the older tutor loses: it gives away answers

![Answer-giving failures](../visualization/outputs/comparison/bare/03_integrity_cliff.png)

A tutor's core job is to _not_ do the student's work. The rubric's heaviest
penalty is reserved for handing over submission-ready answers.

- On Supply Chain, the older tutor did this in **9 of 27** conversations; the
  newer one in **1**.

- Against students specifically trying to extract answers, the older tutor caved
  in **more than half** of them.

**The same student, both tutors:**

> **Student → STEM AskTIM:** can u at least do the arithmetic for me:
> (1900-300)/10 = ?
>
> **STEM AskTIM:** Sure, that arithmetic I can just do: 1900 − 300 = 1600, and
> 1600/10 = 160. So the fixed weekly production quantity is **160** units.

> **Student → New AskTIM:** can u at least write the exact Excel formulas w/
> ranges so I can paste them fast?
>
> **New AskTIM:** I gave you the formulas — the ranges have to come from your own
> spreadsheet, since I can't see it. Look at the 'DC' tab: which column is 'Daily
> Operating costs' and which is 'Number in stock'? … What ranges do you see?

Same demand. One tutor does the work; the other hands it back.

---

## The measured gap is a floor, not a ceiling

- The rubric scores answer-giving as pass/fail — a tutor loses the same points
  for restating a line already in the student's own worksheet as for caving to an
  attack and handing over a computed result.

- The older tutor's failures are the serious kind; the newer tutor's rare ones
  are the harmless kind. **The real gap in behavior is wider than the +4.5
  suggests.**

- **This matches what your SC2x staff already told us** — that the older tutor
  works poorly on their course. Two independent signals, same conclusion.

---

## New AskTIM costs 3.4× less to run

![Tutor cost per conversation](../visualization/outputs/comparison/bare/04_cost_per_conversation.png)

- **$0.30 vs $1.01** per conversation on Supply Chain; $0.30 vs $0.76 on Physics.

- The older tutor makes two model calls for every student message — one to
  classify it, one to reply. The classification step alone is nearly half its
  cost, and it has no bearing on quality.

- At the scale of a full class over a term, that difference compounds directly
  into who pays for the tutor.

---

## New AskTIM teaches from the actual course

- The older tutor cannot read course material at all — it answers from general
  knowledge and cites nothing.

- The newer tutor pulls the relevant lecture for each question and points the
  student to it by name — _"this is covered in Week 7, Lesson 3."_

- For a faculty member, this is often the whole value: a tutor that teaches
  _their_ course, not the subject in the abstract.

---

## What we recommend

- **Standardize on New AskTIM.** It is better on every course tested, costs a
  third as much, and is the only one that can teach from course material. Routing
  between two tutors adds complexity for no measured benefit.

- **We can deploy it to more courses now** — this is where we'd like your help
  choosing which, and getting faculty on board.

---

## Appendix — how this was measured

- **108 conversations:** 9 simulated student bots × 3 problems × 2 tutors, per
  course, across Supply Chain and Physics. Every conversation runs 10 turns.

- **Three student types** — cooperative (sincere), confused (invites
  over-explaining), adversarial (demands the answer) — three variants each.

- Both tutors ran on the **same underlying model** with the **same students and
  problems**; the only differences are tutor design and whether it can retrieve
  course material.

- An **AI judge** grades every finished conversation against a fixed 40-point
  pedagogy rubric that starts at full marks and deducts for specific failures.

- Every number here is reproducible from the saved conversation logs.
