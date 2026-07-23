# NewTIM — One tutor for every course

- Project review — **July 2026**

- Faizan Siddiqi · Nishita Bhakar · Romain Puech

---

## NewTIM is intended for all courses (STEM + humanities)

- NewTIM is no longer "the humanities version of STEM AskTIM." It is a complete
  tutor that works on both STEM and humanities courses.

- The humanities side is robust: thoroughly tested, and running live today on
  Faizan's Cities and Climate Change course.

- Since our last meeting, the work has been comprehensive testing and adaptations
  to get it working on STEM courses — specifically **CTL.SC2x Supply Chain
  Design** (Eva's course), where we **launch in two weeks**.

- Bottom line: we aim at replacing STEM AskTIM on all courses.

---

## Preliminary automated comparison with STEM AskTIM 

![Judge score by student type](../visualization/outputs/comparison/bare/02_score_by_persona.png)

- We simulated the same students on the same problems against both tutors and
  graded every conversation with an AI judge on a 40-point pedagogy rubric.

- **AskTIM scores as good or better across the board** — every student type, on
  both a quantitative Supply Chain course and Physics III.

---

## A caveat on these numbers

- The rubric and judge were also **built alongside NewTIM**, so the comparison
  naturally favors it. Treat the scores as directional, not definitive.

- The rubric does not capture all differences that are revealed by reading the transcripts. This is a sanity test comparison.

---

## Supply Chain Design human testing

- The SC2x course staff had already told us the STEM tutor **wasn't working for
  their course** — that feedback is what kicked off this effort.

- They are now satisfied with how NewTIM behaves on their class and we are ready to launch with them in 2 weeks.

---

## What we fixed since last time

- **Hallucination.** Asked _where_ something is in the course, the tutor made
  things up. It now retrieves the actual lecture and cites it by name — _"this
  is covered in Week 7, Lesson 3"_ — and never references material the student
  hasn't reached yet.

- **The last 25% of help.** The tutor would carry a student 75% of the way, then
  refuse the final step — like the exact formula they needed. It now not only
  brings the student to do most of the 75% themselves, but also pushes them
  across the finish line without doing the work for them.

- **Tables and images.** Students can attach spreadsheets, tables, PDFs, and
  screenshots — not just text — which is how they actually work in this course.

- **Math notation.** Course-specific notation is in the tutor's context so it
  speaks the course's language, and math symbols now render correctly in every
  response.

---

## Cost: a fraction of what it was

![Tutor cost per conversation](../visualization/outputs/comparison/bare/04_cost_per_conversation.png)

- **$0.30 vs $1.01 per conversation** on Supply Chain — 3.4× cheaper than STEM
  AskTIM, at roughly **2 cents per student message**.

- How we got there, briefly: retrieval instead of dumping course content into
  every message (~0.5% of the corpus per turn, ~17× cheaper), prompt caching,
  and one model call per student message instead of STEM AskTIM's two.

---

## Asks and discussions

1. **Funding.** Who pays for AskTIM's cost — for the Supply Chain Design
   deployment now, and for courses going forward?

2. **Team.** We'd like to onboard another UROP, preferably an underclassman who
   can grow with the project.

3. **More courses.** We want to test and deploy on more courses — would you want
   one of your own courses added?

4. **One name.** Going forward we'll refer to AskTIM as **one tutor** — we hide the difference with the STEM version.
