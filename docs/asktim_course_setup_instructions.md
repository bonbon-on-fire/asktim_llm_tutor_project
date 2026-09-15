# Setting Up Your Course in AskTIM

## What is AskTIM?

AskTIM is an AI tutor that your students use for your course. Think of it as a
teaching assistant available around the clock inside Canvas.

It helps students in two ways:

- **Understand the material** — they can ask questions about your lectures and
  readings and get explanations.
- **Get unstuck on homework** — it guides them toward the answer with hints and
  questions.

Importantly, **AskTIM never hands out answers.** It coaches students through the
work; it does not solve the assignment for them.

For AskTIM to do this well, it needs your course materials. This document
explains what to send. **You send what you already have, in whatever format you
have it** — we handle all the setup and conversion. You do not need to reformat
anything.

---

## What we need from you

### 1. The basics

- Course number and title (for example, "15.095 Machine Learning under a Modern
  Optimization Lens")
- Term and year
- Instructor and teaching assistant names and email addresses

### 2. A short course description

One paragraph describing what the course covers. Your catalog blurb is perfect.

### 3. Your syllabus

Usually your existing syllabus PDF is all we need. It should include:

- The lecture schedule (dates and topics)
- Grading breakdown and homework due dates
- Course platforms (Canvas, Piazza, Gradescope — links and join codes)
- Office hours and the collaboration / academic-honesty policy

### 4. Lecture materials

Your slides or lecture notes, **one file per lecture**. PDF or PowerPoint is
fine.

This is what AskTIM draws on to answer student questions, so the more lectures
you send, the more helpful it becomes. You can send them all at once or a few at
a time as the term goes on.

### 5. Assignments

Each homework or problem set, exactly as students receive it. Include anything
that goes with it — datasets, starter code, spreadsheets, notebooks, and so on.

### 6. Answer keys

The solution or answer key for each assignment.

- These stay **private to the tutor**. Students never see them.
- They let AskTIM check whether a student's reasoning is right and steer them in
  the correct direction — **without ever revealing the answer.**
- If an assignment has no single right answer, sample solutions work just as
  well.

---

## Optional, but helpful

- **Readings** — any papers or handouts you want the tutor to be able to
  reference.
- **Tutor guidance** — anything special you want: topics to avoid, how strict to
  be about not revealing solutions, preferred tone, and so on.

---

## A few practical notes

- **Any common format works:** PDF, PowerPoint, Word, Jupyter notebooks, CSV.
- **Easiest for us:** one file per lecture and one file per assignment, with
  clear names.
- **No reformatting needed** — send everything as-is.

---

## What happens next

1. You send us the materials above.
2. We convert everything, build your course, and make it searchable for the
   tutor.
3. We confirm when it is live for your students.

You do not need a complete course to launch. A first week is enough to get
started — the course description, the syllabus, the first lecture, and the first
homework. We add the rest as it becomes available.

---

## Adding AskTIM to your course page

Once your course is live, we send you a **link** to AskTIM. It looks like this:

```
https://asktim-beta-plus.up.railway.app/embed?course=your_course&exercise=1
```

The link already points at your course, and you can have one per assignment
(the `exercise=1`, `exercise=2`, … part) so students land on the right one. You
don't have to build these by hand — tell us which assignment goes on which page
and we'll send you the exact links.

You embed that link on a Canvas page as an **iframe** (a window that shows
AskTIM right inside Canvas). There are two easy ways:

### Option A — paste it into a page (most common)

1. In Canvas, open the page where you want AskTIM (for example a "Course Tutor"
   page, or the homework page itself) and click **Edit**.
2. In the editor toolbar, switch to the HTML view — the `</>` button (labelled
   **HTML Editor**).
3. Paste this, using the link we sent you:

   ```html
   <iframe
     src="https://asktim-beta-plus.up.railway.app/embed?course=your_course&exercise=1"
     width="100%"
     height="800"
     style="border: 1px solid #ccc;"
     allow="clipboard-write">
   </iframe>
   ```

4. Switch back and **Save**. AskTIM now appears on the page.

`height="800"` sets how tall the window is (in pixels) — raise or lower it to
taste. `width="100%"` makes it fill the page.

### Option B — add it to the course menu

If you'd rather have "AskTIM" as its own item in the left-hand course menu:

1. Go to **Settings → Navigation**, or **Settings → Apps → Redirect Tool**.
2. Add a new item / app, give it the name **AskTIM**, and paste the link we
   sent you as the URL.
3. Save. Students click **AskTIM** in the menu to open it full-screen.

This same approach works in other systems too (Brightspace, Moodle, or any page
that lets you embed an iframe) — the link is the same.

> **Tip:** students sign in to AskTIM the first time with a username and
> password (so their conversation history follows them across devices). If your
> browser blocks the embedded window from signing in, opening AskTIM in its own
> tab always works — Option B does this by default.

---

## Questions

If anything here is unclear, or you are not sure whether a file is useful, just
send it and ask. We would rather have too much than too little.
