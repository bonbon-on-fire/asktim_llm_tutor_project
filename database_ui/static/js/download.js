"use strict";
// database_ui — "Download data" wizard, mirroring the sandbox "Edit context"
// walkthrough. Page 1 multi-selects courses; then each selected course gets its
// OWN page with a sandbox-style multi-select dropdown of its exercises. Total
// pages = 1 + (number of selected courses). The final page downloads a CSV (one
// row per message) via /api/export.csv.
(function () {
  const openBtn = document.getElementById("download-open");
  const modal = document.getElementById("download-modal");
  const form = document.getElementById("download-form");
  const stepLabel = document.getElementById("download-step-label");
  const stepBody = document.getElementById("download-step-body");
  const errorBox = document.getElementById("download-error");
  const cancelBtn = document.getElementById("download-cancel");
  const backBtn = document.getElementById("download-back");
  const nextBtn = document.getElementById("download-next");
  if (!openBtn || !modal) return;

  // Total pages: the course-selection page plus one page per selected course.
  function totalSteps() {
    return 1 + selectedCourses().length;
  }

  // Downward chevron caret for the dropdown trigger (matches sandbox's wizard).
  const CHEVRON_SVG =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';

  // Wizard state, rebuilt each time the modal opens.
  let courses = []; // [{course, course_name, assignments:[{exercise_number, exercise_kind}]}]
  let courseChecked = {}; // {courseKey: bool} — Step 1 selection
  let assignChecked = {}; // {"course::exercise": bool} — per-course selection
  let step = 0;

  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.hidden = false;
  }
  function clearError() {
    errorBox.hidden = true;
    errorBox.textContent = "";
  }
  function closeModal() {
    modal.hidden = true;
  }

  // Courses picked in Step 1, in their fetched order.
  function selectedCourses() {
    return courses.filter((c) => courseChecked[c.course]);
  }

  function pairKey(courseKey, exercise) {
    return courseKey + "::" + exercise;
  }

  // A sandbox-style dropdown that lets you check multiple options. The list
  // opens DOWNWARD (a native <select> flips up when low on a centered modal)
  // and stays open while you toggle items. `checkedSet` is mutated in place;
  // `onChange` fires after every toggle so callers can persist selection.
  function buildMultiSelect(options, checkedSet, onChange) {
    const root = document.createElement("div");
    root.className = "context-dropdown download-multiselect";
    let isOpen = false;

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "context-dropdown-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    const labelSpan = document.createElement("span");
    labelSpan.className = "context-dropdown-label";
    const caret = document.createElement("span");
    caret.className = "context-dropdown-caret";
    caret.setAttribute("aria-hidden", "true");
    caret.innerHTML = CHEVRON_SVG;
    trigger.appendChild(labelSpan);
    trigger.appendChild(caret);

    const list = document.createElement("div");
    list.className = "context-dropdown-list";
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-multiselectable", "true");
    list.hidden = true;

    function summary() {
      const checked = options.filter((o) => checkedSet.has(o.value));
      if (checked.length === 0) return "None";
      if (checked.length === 1) return checked[0].label;
      if (checked.length === options.length) return "All (" + checked.length + ")";
      return checked.length + " selected";
    }
    function paintLabel() {
      labelSpan.textContent = summary();
    }

    for (const o of options) {
      const item = document.createElement("div");
      item.className = "context-dropdown-option";
      item.setAttribute("role", "option");
      item.textContent = o.label;
      const sync = () =>
        item.setAttribute("aria-selected", checkedSet.has(o.value) ? "true" : "false");
      sync();
      // Multi-select: a click toggles this option's blue highlight and keeps
      // the list open (stopPropagation) so more can be picked in one go.
      item.addEventListener("click", (e) => {
        e.stopPropagation();
        if (checkedSet.has(o.value)) checkedSet.delete(o.value);
        else checkedSet.add(o.value);
        sync();
        paintLabel();
        if (onChange) onChange();
      });
      list.appendChild(item);
    }

    function onDocClick(e) {
      if (!root.contains(e.target)) close();
    }
    function open() {
      if (isOpen) return;
      isOpen = true;
      list.hidden = false;
      root.classList.add("open");
      setTimeout(() => document.addEventListener("click", onDocClick), 0);
    }
    function close() {
      if (!isOpen) return;
      isOpen = false;
      list.hidden = true;
      root.classList.remove("open");
      document.removeEventListener("click", onDocClick);
    }
    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      isOpen ? close() : open();
    });
    trigger.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
    });

    paintLabel();
    root.appendChild(trigger);
    root.appendChild(list);
    return root;
  }

  // Both steps' dropdowns persist their selection into state as they change
  // (courseChecked / assignChecked), so navigating away needs no explicit save.
  function saveStep() {}

  function renderCourseStep() {
    const options = courses.map((c) => ({
      value: c.course,
      label: c.course_name || c.course,
    }));
    const checkedSet = new Set(
      options.filter((o) => courseChecked[o.value] !== false).map((o) => o.value)
    );
    const dd = buildMultiSelect(options, checkedSet, () => {
      for (const o of options) courseChecked[o.value] = checkedSet.has(o.value);
      clearError();
      // Picking/unpicking courses changes the page count, so refresh the chrome.
      updateChrome();
    });
    stepBody.appendChild(dd);
  }

  // Render one selected course's own page: its name as a muted subtitle plus a
  // dropdown of its exercises. Called once per per-course page (step >= 1).
  function renderCoursePage(course) {
    const title = document.createElement("p");
    title.className = "download-course-title";
    title.textContent = course.course_name || course.course;
    stepBody.appendChild(title);

    if (!course.assignments.length) {
      const none = document.createElement("p");
      none.className = "download-empty-note";
      none.textContent = "No assignments.";
      stepBody.appendChild(none);
      return;
    }

    const options = course.assignments.map((a) => ({
      value: pairKey(course.course, a.exercise_number),
      label:
        (a.exercise_kind === "practice" ? "Practice " : "Exercise ") +
        a.exercise_number,
    }));
    const checkedSet = new Set(
      options.filter((o) => assignChecked[o.value] !== false).map((o) => o.value)
    );
    const dd = buildMultiSelect(options, checkedSet, () => {
      for (const o of options) assignChecked[o.value] = checkedSet.has(o.value);
      clearError();
    });
    stepBody.appendChild(dd);
  }

  // Refresh the step label + Back/Next button text for the current step.
  function updateChrome() {
    const total = totalSteps();
    const kind = step === 0 ? "Course" : "Assignment";
    stepLabel.textContent = "Step " + (step + 1) + " of " + total + ": " + kind;
    backBtn.hidden = step === 0;
    // "Download" only on the last per-course page; the course page always
    // continues (selecting a course always adds at least one page after it).
    nextBtn.textContent = step > 0 && step === total - 1 ? "Download CSV File" : "Continue";
  }

  function renderStep() {
    clearError();
    stepBody.innerHTML = "";
    if (step === 0) {
      if (!courses.length) {
        stepBody.textContent = "No data to export yet.";
        backBtn.hidden = true;
        nextBtn.textContent = "Continue";
        stepLabel.textContent = "";
        return;
      }
      renderCourseStep();
    } else {
      // Per-course page: the (step-1)-th selected course. If the selection
      // shrank out from under us, fall back to the course page.
      const course = selectedCourses()[step - 1];
      if (!course) {
        step = 0;
        renderCourseStep();
      } else {
        renderCoursePage(course);
      }
    }
    updateChrome();
  }

  async function openModal() {
    clearError();
    stepLabel.textContent = "";
    stepBody.textContent = "Loading…";
    backBtn.hidden = true;
    nextBtn.textContent = "Continue";
    modal.hidden = false;
    try {
      const r = await fetch("/api/export/filters");
      if (!r.ok) {
        let msg = "Could not load export options";
        try {
          const body = await r.json();
          if (body && body.message) msg = body.message;
        } catch (_) {}
        stepBody.textContent = "";
        showError(msg);
        return;
      }
      const data = await r.json();
      courses = (data && data.courses) || [];
      // Courses start unselected — the reviewer opts in to what they want.
      // A course's assignments default to selected, so picking a course pulls
      // in all its work (trim individual ones in Step 2 if needed).
      courseChecked = {};
      assignChecked = {};
      for (const c of courses) {
        courseChecked[c.course] = false;
        for (const a of c.assignments) {
          assignChecked[pairKey(c.course, a.exercise_number)] = true;
        }
      }
      step = 0;
      renderStep();
    } catch (e) {
      stepBody.textContent = "";
      showError("Could not load export options");
    }
  }

  // Collect selected (course, exercise) pairs as "course::exercise" strings —
  // only assignments under a still-selected course count.
  function selectedPairs() {
    const pairs = [];
    for (const c of selectedCourses()) {
      for (const a of c.assignments) {
        if (assignChecked[pairKey(c.course, a.exercise_number)]) {
          pairs.push(pairKey(c.course, a.exercise_number));
        }
      }
    }
    return pairs;
  }

  function finish() {
    const pairs = selectedPairs();
    if (pairs.length === 0) {
      showError("Select at least one assignment to download");
      return;
    }
    const qs = pairs.map((p) => "assignment=" + encodeURIComponent(p)).join("&");
    // Plain navigation: the browser handles the file download from the
    // attachment response, then we close the modal.
    window.location = "/api/export.csv?" + qs;
    closeModal();
  }

  function goNext(event) {
    if (event) event.preventDefault();
    saveStep();
    if (step === 0 && selectedCourses().length === 0) {
      showError("Select at least one course");
      return;
    }
    if (step < totalSteps() - 1) {
      step += 1;
      renderStep();
    } else {
      finish();
    }
  }

  function goBack() {
    if (step === 0) return;
    saveStep();
    step -= 1;
    renderStep();
  }

  openBtn.addEventListener("click", openModal);
  cancelBtn.addEventListener("click", closeModal);
  backBtn.addEventListener("click", goBack);
  form.addEventListener("submit", goNext);
  // Click on the dark backdrop (outside the card) closes the modal.
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });
})();
