"use strict";
// database_ui — "Download data" wizard. Mirrors the sandbox "Edit context"
// walkthrough: Step 1 multi-selects courses, then one Assignment step per
// selected course multi-selects that course's exercises. The final step
// downloads a CSV (one row per message) via /api/export.csv.
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

  // Wizard state, rebuilt each time the modal opens.
  let courses = []; // [{course, course_name, assignments:[{exercise_number, exercise_kind}]}]
  let courseChecked = {}; // {courseKey: bool} — Step 1 selection
  let assignChecked = {}; // {"course::exercise": bool} — per-course selection
  let step = 0; // 0 = Course step; 1..N = Assignment step for selectedCourses[step-1]

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

  // Courses picked in Step 1, in their fetched order — each gets its own
  // Assignment step, so this drives the dynamic total step count.
  function selectedCourses() {
    return courses.filter((c) => courseChecked[c.course]);
  }
  function totalSteps() {
    // 1 (Course) + one Assignment step per selected course.
    return 1 + selectedCourses().length;
  }

  function pairKey(courseKey, exercise) {
    return courseKey + "::" + exercise;
  }

  // Read the current step's checkboxes back into state before navigating away
  // (the step body is rebuilt on every render, so state must persist here).
  function saveStep() {
    if (step === 0) {
      for (const cb of stepBody.querySelectorAll(".download-course-cb")) {
        courseChecked[cb.dataset.course] = cb.checked;
      }
    } else {
      for (const cb of stepBody.querySelectorAll(".download-assignment-cb")) {
        assignChecked[pairKey(cb.dataset.course, cb.dataset.exercise)] = cb.checked;
      }
    }
  }

  function makeOption(labelText, cbClass, dataset, checked) {
    const row = document.createElement("label");
    row.className = "download-option";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = cbClass;
    cb.checked = checked;
    for (const k in dataset) cb.dataset[k] = dataset[k];
    const span = document.createElement("span");
    span.textContent = labelText;
    row.appendChild(cb);
    row.appendChild(span);
    return { row: row, cb: cb };
  }

  function renderCourseStep() {
    for (const c of courses) {
      const opt = makeOption(
        c.course_name || c.course,
        "download-course-cb",
        { course: c.course },
        courseChecked[c.course] !== false
      );
      // Re-checking/unchecking a course changes the total step count, so keep
      // the "Step X of N" label and the button label honest as it changes.
      opt.cb.addEventListener("change", () => {
        courseChecked[c.course] = opt.cb.checked;
        updateChrome();
      });
      stepBody.appendChild(opt.row);
    }
  }

  function renderAssignmentStep() {
    const course = selectedCourses()[step - 1];
    if (!course) return; // selection changed out from under us; guarded by nav
    const title = document.createElement("p");
    title.className = "download-course-title";
    title.textContent = course.course_name || course.course;
    stepBody.appendChild(title);
    for (const a of course.assignments) {
      const kind = a.exercise_kind === "practice" ? "Practice" : "Exercise";
      const key = pairKey(course.course, a.exercise_number);
      const opt = makeOption(
        kind + " " + a.exercise_number,
        "download-assignment-cb",
        { course: course.course, exercise: a.exercise_number },
        assignChecked[key] !== false
      );
      stepBody.appendChild(opt.row);
    }
  }

  // Refresh the step label + Back/Next button text for the current step.
  function updateChrome() {
    const total = totalSteps();
    const kind = step === 0 ? "Course" : "Assignment";
    stepLabel.textContent = "Step " + (step + 1) + " of " + total + ": " + kind;
    backBtn.hidden = step === 0;
    nextBtn.textContent = step === total - 1 ? "Create & download file" : "Continue";
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
