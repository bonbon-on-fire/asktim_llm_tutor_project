"use strict";
// database_ui — "Download data" wizard. Two steps, mirroring the sandbox
// "Edit context" walkthrough: Step 1 multi-selects courses, then Step 2
// multi-selects each selected course's exercises via one sandbox-style
// dropdown per course. The final step downloads a CSV (one row per message)
// via /api/export.csv.
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

  const TOTAL_STEPS = 2; // 0 = Course, 1 = Assignment.

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
      if (checked.length === 0) return "None selected";
      if (checked.length === 1) return checked[0].label;
      if (checked.length === options.length) return "All (" + checked.length + ")";
      return checked.length + " selected";
    }
    function paintLabel() {
      labelSpan.textContent = summary();
    }

    for (const o of options) {
      const item = document.createElement("label");
      item.className = "context-dropdown-option download-ms-option";
      item.setAttribute("role", "option");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.className = "download-ms-cb";
      cb.checked = checkedSet.has(o.value);
      item.setAttribute("aria-selected", cb.checked ? "true" : "false");
      const span = document.createElement("span");
      span.textContent = o.label;
      cb.addEventListener("change", () => {
        if (cb.checked) checkedSet.add(o.value);
        else checkedSet.delete(o.value);
        item.setAttribute("aria-selected", cb.checked ? "true" : "false");
        paintLabel();
        if (onChange) onChange();
      });
      // Clicking a row toggles its checkbox; keep the click from closing the list.
      item.addEventListener("click", (e) => e.stopPropagation());
      item.appendChild(cb);
      item.appendChild(span);
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

  function makeCourseOption(labelText, courseKey, checked) {
    const row = document.createElement("label");
    row.className = "download-option";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "download-course-cb";
    cb.checked = checked;
    cb.dataset.course = courseKey;
    const span = document.createElement("span");
    span.textContent = labelText;
    row.appendChild(cb);
    row.appendChild(span);
    return { row: row, cb: cb };
  }

  // Read the Course step's checkboxes back into state before navigating away.
  // The Assignment step's dropdowns persist into assignChecked as they change,
  // so no save is needed there.
  function saveStep() {
    if (step === 0) {
      for (const cb of stepBody.querySelectorAll(".download-course-cb")) {
        courseChecked[cb.dataset.course] = cb.checked;
      }
    }
  }

  function renderCourseStep() {
    for (const c of courses) {
      const opt = makeCourseOption(
        c.course_name || c.course,
        c.course,
        courseChecked[c.course] !== false
      );
      opt.cb.addEventListener("change", () => {
        courseChecked[c.course] = opt.cb.checked;
      });
      stepBody.appendChild(opt.row);
    }
  }

  function renderAssignmentStep() {
    const chosen = selectedCourses();
    if (!chosen.length) return; // selection changed out from under us; guarded by nav
    for (const course of chosen) {
      const title = document.createElement("p");
      title.className = "download-course-title";
      title.textContent = course.course_name || course.course;
      stepBody.appendChild(title);

      if (!course.assignments.length) {
        const none = document.createElement("p");
        none.className = "download-empty-note";
        none.textContent = "No assignments.";
        stepBody.appendChild(none);
        continue;
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
  }

  // Refresh the step label + Back/Next button text for the current step.
  function updateChrome() {
    const kind = step === 0 ? "Course" : "Assignment";
    stepLabel.textContent = "Step " + (step + 1) + " of " + TOTAL_STEPS + ": " + kind;
    backBtn.hidden = step === 0;
    nextBtn.textContent =
      step === TOTAL_STEPS - 1 ? "Download CSV File" : "Continue";
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
      renderAssignmentStep();
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
      // Everything checked by default: all courses, all assignments.
      courseChecked = {};
      assignChecked = {};
      for (const c of courses) {
        courseChecked[c.course] = true;
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
      showError("Select at least one assignment to download.");
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
      showError("Select at least one course.");
      return;
    }
    if (step < TOTAL_STEPS - 1) {
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
