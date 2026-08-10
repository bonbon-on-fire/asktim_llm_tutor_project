"use strict";
// database_ui — "Download data" modal. Fetches the course/assignment options,
// lets the reviewer multi-select, then navigates to /api/export.csv to download.
(function () {
  const openBtn = document.getElementById("download-open");
  const modal = document.getElementById("download-modal");
  const fields = document.getElementById("download-fields");
  const errorBox = document.getElementById("download-error");
  const cancelBtn = document.getElementById("download-cancel");
  const submitBtn = document.getElementById("download-submit");
  if (!openBtn || !modal) return;

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

  // Build one course block: a course checkbox (checked) followed by its
  // assignment checkboxes (all checked). Unchecking the course disables its
  // whole assignment group so those pairs drop out of the selection.
  function renderCourse(course) {
    const block = document.createElement("div");
    block.className = "download-course";

    const head = document.createElement("label");
    head.className = "download-course-head";
    const courseCb = document.createElement("input");
    courseCb.type = "checkbox";
    courseCb.checked = true;
    courseCb.className = "download-course-cb";
    courseCb.dataset.course = course.course;
    const courseName = document.createElement("span");
    courseName.textContent = course.course_name || course.course;
    head.appendChild(courseCb);
    head.appendChild(courseName);
    block.appendChild(head);

    const group = document.createElement("div");
    group.className = "download-assignments";
    for (const a of course.assignments) {
      const row = document.createElement("label");
      row.className = "download-assignment";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = true;
      cb.className = "download-assignment-cb";
      cb.dataset.course = course.course;
      cb.dataset.exercise = a.exercise_number;
      const kind = a.exercise_kind === "practice" ? "Practice" : "Exercise";
      const label = document.createElement("span");
      label.textContent = kind + " " + a.exercise_number;
      row.appendChild(cb);
      row.appendChild(label);
      group.appendChild(row);
    }
    block.appendChild(group);

    // Toggling the course enables/disables (and visually dims) its assignments.
    courseCb.addEventListener("change", () => {
      group.classList.toggle("is-disabled", !courseCb.checked);
      for (const cb of group.querySelectorAll(".download-assignment-cb")) {
        cb.disabled = !courseCb.checked;
      }
    });
    return block;
  }

  function renderCourses(courses) {
    fields.innerHTML = "";
    if (!courses || courses.length === 0) {
      fields.textContent = "No data to export yet.";
      return;
    }
    for (const c of courses) fields.appendChild(renderCourse(c));
  }

  // Collect selected (course, exercise) pairs as "course::exercise" strings,
  // skipping assignments whose course is unchecked (their boxes are disabled).
  function selectedPairs() {
    const pairs = [];
    for (const cb of fields.querySelectorAll(".download-assignment-cb")) {
      if (cb.checked && !cb.disabled) {
        pairs.push(cb.dataset.course + "::" + cb.dataset.exercise);
      }
    }
    return pairs;
  }

  async function openModal() {
    clearError();
    fields.textContent = "Loading…";
    modal.hidden = false;
    try {
      const r = await fetch("/api/export/filters");
      if (!r.ok) {
        let msg = "Could not load export options";
        try {
          const body = await r.json();
          if (body && body.message) msg = body.message;
        } catch (_) {}
        fields.textContent = "";
        showError(msg);
        return;
      }
      const data = await r.json();
      renderCourses(data.courses);
    } catch (e) {
      fields.textContent = "";
      showError("Could not load export options");
    }
  }

  function submit() {
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

  openBtn.addEventListener("click", openModal);
  cancelBtn.addEventListener("click", closeModal);
  submitBtn.addEventListener("click", submit);
  // Click on the dark backdrop (outside the card) closes the modal.
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });
})();
