(function () {
  /** Returns the current URL pathname. */
  function getPath() {
    return window.location.pathname;
  }

  /**
   * Parse the pathname to detect a /transcript/:group/:version URL.
   * @returns {{group: string, version: string}|null}
   */
  function isTranscriptPage() {
    const m = getPath().match(/^\/transcript\/([^/]+)\/([^/]+)\/?$/);
    return m ? { group: m[1], version: m[2] } : null;
  }

  /** Hide all .page elements and show the one with the given id. */
  function showPage(id) {
    document.querySelectorAll("#main .page").forEach((p) => p.classList.add("hidden"));
    const el = document.getElementById(id);
    if (el) el.classList.remove("hidden");
  }

  /**
   * Parse x as an integer; returns Infinity for non-numeric values (used for sort ordering
   * so that missing/non-numeric entries sort to the end).
   * @param {*} x
   * @returns {number}
   */
  function parseNumericOrInfinity(x) {
    const n = Number.parseInt(String(x || ""), 10);
    return Number.isFinite(n) ? n : Number.POSITIVE_INFINITY;
  }

  /**
   * Render the dashboard: sortable transcript table.
   * @param {object[]} list - transcript row objects
   */
  function renderDashboard(list) {
    let sortKey = "group";
    let sortDir = 1;

    function displayedGroup(t) {
      if (t.kind === "transcript") {
        return String((t.metadata && t.metadata.student_persona) || t.group || "");
      }
      return String(t.group || "");
    }

    function renderTable() {
      const sorted = [...list].sort((a, b) => {
        if (sortKey === "resume_from_turn") {
          const va = a[sortKey];
          const vb = b[sortKey];
          if (va == null && vb == null) return 0;
          if (va == null) return 1;
          if (vb == null) return -1;
          return sortDir * (va - vb);
        }
        if (sortKey === "group") {
          const groupCompare = displayedGroup(a).localeCompare(displayedGroup(b));
          if (groupCompare !== 0) return sortDir * groupCompare;
          const versionCompare = parseNumericOrInfinity(a.version) - parseNumericOrInfinity(b.version);
          if (versionCompare !== 0) return sortDir * versionCompare;
          const courseCompare = String((a.metadata && a.metadata.course) || "").localeCompare(
            String((b.metadata && b.metadata.course) || "")
          );
          if (courseCompare !== 0) return sortDir * courseCompare;
          return sortDir * (
            parseNumericOrInfinity(a.metadata && a.metadata.exercise_number) -
            parseNumericOrInfinity(b.metadata && b.metadata.exercise_number)
          );
        }
        if (sortKey === "version") {
          const aNum = parseNumericOrInfinity(a.version);
          const bNum = parseNumericOrInfinity(b.version);
          if (aNum !== bNum) return sortDir * (aNum - bNum);
          return sortDir * String(a.version || "").localeCompare(String(b.version || ""));
        }
        if (sortKey === "course") {
          return sortDir * String((a.metadata && a.metadata.course) || "").localeCompare(
            String((b.metadata && b.metadata.course) || "")
          );
        }
        if (sortKey === "exercise") {
          const aEx = String((a.metadata && a.metadata.exercise_number) || "");
          const bEx = String((b.metadata && b.metadata.exercise_number) || "");
          const aNum = Number.parseInt(aEx, 10);
          const bNum = Number.parseInt(bEx, 10);
          if (Number.isFinite(aNum) && Number.isFinite(bNum) && aNum !== bNum) {
            return sortDir * (aNum - bNum);
          }
          return sortDir * aEx.localeCompare(bEx);
        }
        const va = a[sortKey];
        const vb = b[sortKey];
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        if (typeof va === "number" && typeof vb === "number") return sortDir * (va - vb);
        return sortDir * String(va).localeCompare(String(vb));
      });

      const tbody = document.getElementById("transcripts-tbody");
      tbody.innerHTML = sorted
        .map(
          (t) =>
            `<tr>
          <td>${escapeHtml(displayedGroup(t) || "—")}</td>
          <td>${escapeHtml(t.version || "—")}</td>
          <td>${escapeHtml((t.metadata && t.metadata.course) || "—")}</td>
          <td>${escapeHtml((t.metadata && t.metadata.exercise_number) || "—")}</td>
          <td class="num">${t.resume_from_turn != null ? t.resume_from_turn : "—"}</td>
          <td><a href="/transcript/${encodeURIComponent(t.route_group || t.group)}/${encodeURIComponent(t.route_version || t.version)}">Read</a></td>
        </tr>`
        )
        .join("");
    }

    document.querySelectorAll("#transcripts-table thead th[data-sort]").forEach((th) => {
      th.classList.remove("sorted-asc", "sorted-desc");
      th.onclick = () => {
        const key = th.getAttribute("data-sort");
        if (sortKey === key) sortDir *= -1;
        else sortDir = key === "resume_from_turn" ? 1 : 1;
        sortKey = key;
        document.querySelectorAll("#transcripts-table thead th[data-sort]").forEach((h) => h.classList.remove("sorted-asc", "sorted-desc"));
        th.classList.add(sortDir === 1 ? "sorted-asc" : "sorted-desc");
        renderTable();
      };
    });
    const groupTh = document.querySelector('#transcripts-table thead th[data-sort="group"]');
    if (groupTh) groupTh.classList.add("sorted-asc");
    renderTable();
  }

  /**
   * Safely escape a string for insertion into innerHTML.
   * @param {*} s
   * @returns {string}
   */
  function escapeHtml(s) {
    if (s == null) return "";
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  /**
   * Render a list of exchanges as HTML.
   * @param {object[]} exchanges
   * @param {number|null} resumeFromTurn - turn number where mini continuation starts (for mini exchanges)
   * @returns {string}
   */
  function renderExchanges(exchanges, resumeFromTurn) {
    if (!exchanges || exchanges.length === 0) {
      return '<p class="error">No exchanges available.</p>';
    }
    return exchanges.map((ex) => {
      const isPivot = resumeFromTurn != null && ex.turn === resumeFromTurn;
      let html = '<div class="exchange' + (isPivot ? " pivot-turn" : "") + '">';
      html += '<div class="turn-badge">Turn ' + ex.turn + (isPivot ? ' <span class="pivot-badge">pivot</span>' : "") + "</div>";
      html += '<div class="student"><strong>Student:</strong><br/>' + escapeHtml(ex.student || "") + "</div>";
      html += '<div class="tutor"><strong>Tutor:</strong><br/>' + escapeHtml(ex.tutor || "") + "</div>";
      if (ex.pedagogical_reasoning) {
        html += '<div class="reasoning"><strong>Pedagogical reasoning:</strong><br/>' + escapeHtml(ex.pedagogical_reasoning) + "</div>";
      }
      html += "</div>";
      return html;
    }).join("");
  }

  /**
   * Render the full transcript detail view: metadata, raw exchanges, then mini exchanges.
   * @param {object} data - transcript detail object returned by /api/transcripts/:group/:version
   */
  function renderTranscript(data) {
    const meta = data.metadata || {};
    let html = '<div class="meta-top">';
    html += '<span><strong>Tutor prompt:</strong> ' + escapeHtml(meta.tutor_prompt || "—") + "</span>";
    html += '<span><strong>Student persona:</strong> ' + escapeHtml(meta.student_persona || "—") + "</span>";
    html += '<span><strong>Course:</strong> ' + escapeHtml(meta.course || "—") + "</span>";
    html += '<span><strong>Exercise:</strong> ' + escapeHtml(meta.exercise_number || "—") + "</span>";
    html += '<span><strong>Turns:</strong> ' + escapeHtml(String(meta.turns != null ? meta.turns : "—")) + "</span>";
    html += "</div>";

    if (meta.context) {
      html += '<details class="meta-block"><summary>Context</summary><pre style="white-space:pre-wrap;font-size:0.85rem;margin:0.5rem 0 0">' + escapeHtml(meta.context) + "</pre></details>";
    }
    if (meta.exercise) {
      html += '<details class="meta-block"><summary>Exercise</summary><pre style="white-space:pre-wrap;font-size:0.85rem;margin:0.5rem 0 0">' + escapeHtml(meta.exercise) + "</pre></details>";
    }

    html += '<h2 class="transcript-section-heading">Original (tutor_04)</h2>';
    html += renderExchanges(data.exchanges_raw, null);

    const miniLabel = data.resume_from_turn != null
      ? "Mini continuation (tutor_05) — resumed from turn " + data.resume_from_turn
      : "Mini continuation (tutor_05)";
    html += '<h2 class="transcript-section-heading">' + escapeHtml(miniLabel) + "</h2>";
    html += renderExchanges(data.exchanges_mini, data.resume_from_turn);

    document.getElementById("transcript-title").textContent = `${data.group} / ${data.version}`;
    const content = document.getElementById("transcript-content");
    content.innerHTML = html;
  }

  /**
   * Fetch all dashboard rows from /api/transcripts and render the dashboard page.
   */
  async function loadDashboard() {
    showPage("dashboard-page");
    const tbody = document.getElementById("transcripts-tbody");
    tbody.innerHTML = '<tr><td colspan="6" class="loading">Loading...</td></tr>';
    try {
      const r = await fetch("/api/transcripts");
      const list = await r.json();
      if (!r.ok) throw new Error(list.error || "Failed to load");
      if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="error">No transcript rows found.</td></tr>';
        return;
      }
      renderDashboard(list);
    } catch (e) {
      console.error("Failed to load transcripts:", e);
      tbody.innerHTML = '<tr><td colspan="6" class="error">' + escapeHtml(e.message) + "</td></tr>";
    }
  }

  /**
   * Fetch a single transcript detail from /api/transcripts/:group/:version and render it.
   * @param {string} group
   * @param {string} version
   */
  async function loadTranscript(group, version) {
    showPage("transcript-page");
    const content = document.getElementById("transcript-content");
    content.innerHTML = '<p class="loading">Loading transcript...</p>';
    try {
      const r = await fetch("/api/transcripts/" + encodeURIComponent(group) + "/" + encodeURIComponent(version));
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Not found");
      renderTranscript(data);
    } catch (e) {
      content.innerHTML = '<p class="error">' + escapeHtml(e.message) + "</p>";
    }
  }

  /**
   * Decide which page to render based on the current URL.
   */
  function route() {
    const transcript = isTranscriptPage();
    if (transcript) {
      loadTranscript(transcript.group, transcript.version);
    } else {
      loadDashboard();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", route);
  } else {
    route();
  }

  window.addEventListener("popstate", route);
})();
