# Testing Link Wizard Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the 3-step wizard (tutor → course → exercise) down to 1 step (exercise only), auto-selecting the latest tutor and defaulting the course to Cities and Climate Change, so the testing link can be distributed more widely without asking testers to make irrelevant choices.

**Architecture:** All changes are in `test_ui/templates/index.html`. The backend already accepts `tutor_version` and `course` as POST body parameters, so no server changes are needed — the frontend will simply always send the latest tutor version and `cities_and_climate_change`. The wizard HTML for steps 1 and 2 is removed; the JavaScript auto-selects both values after fetching config.

**Tech Stack:** Vanilla JS, HTML, Flask (backend unchanged)

---

## File map

| File | Change |
|------|--------|
| `test_ui/templates/index.html` | Remove step-tutor and step-course HTML; update JS to auto-select latest tutor + course; remove dead functions and event listeners; update breadcrumb, session info, and new-conversation reset |

---

### Task 1: Remove tutor and course wizard step HTML

**Files:**
- Modify: `test_ui/templates/index.html:391-419`

The existing HTML has three `<div class="wizard-step">` blocks: `step-tutor` (lines 391–398), `step-course` (lines 400–409), and `step-exercise` (lines 411–420). Remove the first two entirely and strip the Back button from the exercise step, since there is nothing to go back to.

- [ ] **Step 1: Delete the Step 1 (tutor) block**

Remove this entire block from `index.html`:

```html
    <!-- Step 1: Tutor -->
    <div class="wizard-step active" id="step-tutor">
      <div class="wizard-heading">Choose a tutor</div>
      <div class="option-grid" id="tutor-options"></div>
      <div class="preview-box" id="tutor-preview"></div>
      <div class="wizard-nav" style="justify-content: flex-end;">
        <button class="wizard-next" id="next-from-tutor">Next &rarr;</button>
      </div>
    </div>
```

- [ ] **Step 2: Delete the Step 2 (course) block**

Remove this entire block:

```html
    <!-- Step 2: Course -->
    <div class="wizard-step" id="step-course">
      <div class="wizard-heading">Choose a course</div>
      <div class="option-grid" id="course-options"></div>
      <div class="preview-box" id="course-preview"></div>
      <div class="wizard-nav">
        <button class="wizard-back" id="back-to-course">Back</button>
        <button class="wizard-next" id="next-from-course">Next &rarr;</button>
      </div>
    </div>
```

- [ ] **Step 3: Remove the Back button from the exercise step and add `active` class**

Replace the exercise step block:

```html
    <!-- Step 3: Exercise -->
    <div class="wizard-step" id="step-exercise">
      <div class="wizard-heading">Choose an exercise</div>
      <div class="option-grid" id="exercise-options"></div>
      <div class="preview-box" id="exercise-preview"></div>
      <div class="wizard-nav">
        <button class="wizard-back" id="back-to-course">Back</button>
        <button class="wizard-next" id="start-conversation">Start conversation &rarr;</button>
      </div>
    </div>
```

With:

```html
    <!-- Exercise selection -->
    <div class="wizard-step active" id="step-exercise">
      <div class="wizard-heading">Choose an exercise</div>
      <div class="option-grid" id="exercise-options"></div>
      <div class="preview-box" id="exercise-preview"></div>
      <div class="wizard-nav" style="justify-content: flex-end;">
        <button class="wizard-next" id="start-conversation">Start conversation &rarr;</button>
      </div>
    </div>
```

---

### Task 2: Update JavaScript — auto-select defaults and remove dead code

**Files:**
- Modify: `test_ui/templates/index.html` (the `<script>` block)

- [ ] **Step 1: Update `steps` object to only reference `step-exercise`**

Replace:

```javascript
  const steps = {
    tutor: document.getElementById('step-tutor'),
    course: document.getElementById('step-course'),
    exercise: document.getElementById('step-exercise'),
  };
```

With:

```javascript
  const steps = {
    exercise: document.getElementById('step-exercise'),
  };
```

- [ ] **Step 2: Update `selections` initializer to pre-populate tutor and course**

Replace:

```javascript
  let selections = { tutor: null, course: null, exercise: null };
```

With:

```javascript
  let selections = { tutor: null, course: 'cities_and_climate_change', exercise: null };
```

- [ ] **Step 3: Update `updateBreadcrumb()` to drop the tutor chip**

Replace:

```javascript
  function updateBreadcrumb() {
    breadcrumbEl.innerHTML = '';
    const parts = [];
    if (selections.tutor) parts.push(selections.tutor);
    if (selections.course) parts.push(selections.course);
    if (selections.exercise) parts.push('exercise_' + selections.exercise);

    parts.forEach((part, i) => {
      const chip = document.createElement('span');
      chip.className = 'breadcrumb-chip';
      chip.textContent = part;
      breadcrumbEl.appendChild(chip);
      if (i < parts.length - 1) {
        const sep = document.createElement('span');
        sep.className = 'breadcrumb-sep';
        sep.textContent = '›';
        breadcrumbEl.appendChild(sep);
      }
    });
  }
```

With:

```javascript
  function updateBreadcrumb() {
    breadcrumbEl.innerHTML = '';
    const parts = [];
    if (selections.course) parts.push(selections.course);
    if (selections.exercise) parts.push('exercise_' + selections.exercise);

    parts.forEach((part, i) => {
      const chip = document.createElement('span');
      chip.className = 'breadcrumb-chip';
      chip.textContent = part;
      breadcrumbEl.appendChild(chip);
      if (i < parts.length - 1) {
        const sep = document.createElement('span');
        sep.className = 'breadcrumb-sep';
        sep.textContent = '›';
        breadcrumbEl.appendChild(sep);
      }
    });
  }
```

- [ ] **Step 4: Update `updateSessionInfo()` to drop the tutor chip**

Replace:

```javascript
  function updateSessionInfo() {
    sessionInfoEl.innerHTML = '';
    const items = [selections.tutor, selections.course, 'exercise ' + selections.exercise];
    items.forEach((val, i) => {
```

With:

```javascript
  function updateSessionInfo() {
    sessionInfoEl.innerHTML = '';
    const items = [selections.course, 'exercise ' + selections.exercise];
    items.forEach((val, i) => {
```

- [ ] **Step 5: Replace `loadConfig()` to auto-select tutor and jump to exercise step**

Replace:

```javascript
  async function loadConfig() {
    try {
      const res = await fetch('/api/config-options');
      configData = await res.json();
      populateTutorStep();
    } catch (e) {
      showToast('Failed to load config: ' + e.message);
    }
  }
```

With:

```javascript
  async function loadConfig() {
    try {
      const res = await fetch('/api/config-options');
      configData = await res.json();
      const versions = configData.tutor_versions || [];
      selections.tutor = versions[versions.length - 1] || null;
      populateExerciseStep(selections.course);
      showStep('exercise');
    } catch (e) {
      showToast('Failed to load config: ' + e.message);
    }
  }
```

- [ ] **Step 6: Update `newConvBtn` click handler to reset only exercise and return to exercise step**

Replace:

```javascript
  newConvBtn.addEventListener('click', () => {
    chatPanelEl.style.display = 'none';
    wizardEl.style.display = 'flex';
    newConvBtn.style.display = 'none';
    selections = { tutor: null, course: null, exercise: null };
    populateTutorStep();
    showStep('tutor');
  });
```

With:

```javascript
  newConvBtn.addEventListener('click', () => {
    chatPanelEl.style.display = 'none';
    wizardEl.style.display = 'flex';
    newConvBtn.style.display = 'none';
    selections.exercise = null;
    populateExerciseStep(selections.course);
    showStep('exercise');
  });
```

- [ ] **Step 7: Remove dead functions and event listeners**

Delete each of these blocks entirely from the `<script>`:

```javascript
  // ---- Step 1: Tutor ----
  function populateTutorStep() { ... }
  function selectTutor(version, btn) { ... }
  document.getElementById('next-from-tutor').addEventListener('click', () => { ... });

  // ---- Step 2: Course ----
  function populateCourseStep() { ... }
  function selectCourse(course, btn) { ... }
  document.getElementById('back-to-tutor').addEventListener('click', () => { ... });
  document.getElementById('next-from-course').addEventListener('click', () => { ... });
  document.getElementById('back-to-course').addEventListener('click', () => { ... });
```

These are dead after the HTML buttons they referenced were removed in Task 1.

---

### Task 3: Manual verification

**Files:** none

- [ ] **Step 1: Start the web UI server**

```powershell
python -m test_ui
```

Expected: server starts on port 5000, no errors.

- [ ] **Step 2: Open http://127.0.0.1:5000 and verify the wizard shows only exercise selection**

Expected:
- No "Choose a tutor" step visible
- No "Choose a course" step visible
- Exercise buttons appear immediately (e.g. `exercise_01` through `exercise_12`)
- No Back button in the exercise nav
- Breadcrumb shows `cities_and_climate_change` chip once an exercise is selected

- [ ] **Step 3: Select an exercise and start a conversation**

Expected:
- "Start conversation" button appears after selecting an exercise
- Clicking it shows the loading indicator, then opens the chat panel
- Session info chips show `cities_and_climate_change › exercise XX`
- Tutor sends an opening message

- [ ] **Step 4: Click "New conversation" and verify it returns to exercise selection**

Expected:
- Wizard reappears showing exercise selection (not tutor or course step)
- Previously selected exercise is deselected
- Can select a different exercise and start again

- [ ] **Step 5: Commit**

```powershell
git add test_ui/templates/index.html
git commit -m "feat: simplify wizard to exercise-only; auto-select latest tutor and cities_and_climate_change"
```
