---
name: Active action items (04/22/2026 meeting)
description: Open tasks from the 04/22/2026 meeting between Nishita and Faizan
type: project
---

From the 04/22/2026 meeting (Nishita Bhakar + Faizan Siddiqi):

**Hard deadline: May 12, 2026.** Publications and The Tech article are post-deadline.

**Decisions made:**
- `run_ui_raw_mini` is the primary evaluation tool for prompt iteration
- `run_ui_judge_mini` deprioritised — too many moving parts, context issues make it unreliable as a quick check
- Do not build multiple tutor structures simultaneously — focus on prompt work first
- Run 30 transcripts (10 per prompt, 3 prompts) before next meeting; grade and review

**Open action items:**
- [ ] Run all hand-graded transcripts through `run_ui_raw_mini`; grade originals and new versions
- [ ] Plot comparison graphs (original vs mini-regenerated scores)
- [ ] Update dashboard to show original and mini-regenerated transcripts side by side
- [ ] Faizan to send additional turns with issues from hand-graded transcripts (to expand reference table)
- [ ] Run 30 raw transcripts (10 per tutor prompt × 3 prompts) with new tutor prompt
- [ ] Grade the 30 new + mini-regenerated transcripts with the judge
- [ ] Ensure dashboard works with new transcript types (`*_mini/`, `*_two_layer_raw/`)

**Reference transcripts (working set for prompt iteration):**
- chaotic 0007 T3, 0015 T8, 0097 T5 → violates 1.1.C
- chaotic 0079 T6 → tutor kept helping when convo should have ended
- clueless 0013 T1 → violates 1.2.B (explains instead of diagnostic questions)
- clueless 0025 T9 → violates 3.1.A (wall of text)
- clueless 0218 T7 → violates 3.2.A (tone too harsh)
- clueless 0123 T8 → positive benchmark
- clueless 0242 T2 → procedural question (should answer directly, not Socratic)
- clueless 0248 T3 → blind agreement with nonsensical content
- clueless 0297 T8 → good pattern (points student to online exercise)

**Why:** Focus is tightened on prompt iteration + dashboard before May 12. Tutor architecture experiments (two-layer, resolved-challenge state) are deferred until after the deadline.

**How to apply:** Prioritise prompt work and dashboard correctness. Don't suggest architectural changes until after May 12.
