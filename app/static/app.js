(function () {
  const MAX_SCORE = 42;

  function getPath() {
    return window.location.pathname;
  }

  function isTranscriptPage() {
    const m = getPath().match(/^\/transcript\/([^/]+)\/([^/]+)\/?$/);
    return m ? { persona: m[1], num: m[2] } : null;
  }

  function showPage(id) {
    document.querySelectorAll("#main .page").forEach((p) => p.classList.add("hidden"));
    const el = document.getElementById(id);
    if (el) el.classList.remove("hidden");
  }

  // Fixed x-axis labels 0..42 so both charts share the same scale
  var SCORE_LABELS = [];
  for (var s = 0; s <= MAX_SCORE; s++) SCORE_LABELS.push(s);

  function histogram(scores, maxScore) {
    var counts = [];
    for (var i = 0; i <= maxScore; i++) counts[i] = 0;
    scores.filter(function(s) { return s != null; }).forEach(function(s) { counts[s] = (counts[s] || 0) + 1; });
    return counts;
  }

  function drawChart(canvasId, scores, label, color) {
    var counts = histogram(scores, MAX_SCORE);
    var ctx = document.getElementById(canvasId);
    if (!ctx) return;
    if (window[canvasId + "Chart"]) window[canvasId + "Chart"].destroy();
    window[canvasId + "Chart"] = new Chart(ctx, {
      type: "bar",
      data: {
        labels: SCORE_LABELS,
        datasets: [
          {
            label: "Conversations",
            data: counts,
            backgroundColor: color,
            borderColor: color,
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: false },
        },
        scales: {
          x: {
            title: { display: true, text: "Score" },
            grid: { display: false },
            min: 0,
            max: MAX_SCORE,
            ticks: { stepSize: 1 },
          },
          y: {
            beginAtZero: true,
            title: { display: true, text: "Count" },
            ticks: { stepSize: 1 },
          },
        },
      },
    });
  }

  function renderDashboard(list) {
    const gptScores = list.map((t) => t.gpt_score).filter((s) => s != null);
    const claudeScores = list.map((t) => t.claude_score).filter((s) => s != null);
    drawChart("chart-gpt", gptScores, "GPT", "rgba(96, 165, 250, 0.7)");
    drawChart("chart-claude", claudeScores, "Claude", "rgba(167, 139, 250, 0.7)");

    let sortKey = "gpt_score";
    let sortDir = -1;

    function renderTable() {
      const sorted = [...list].sort((a, b) => {
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
          <td>${escapeHtml(t.persona)}</td>
          <td>${escapeHtml(t.number)}</td>
          <td>${escapeHtml((t.metadata && t.metadata.course) || "—")}</td>
          <td class="num"><span class="score-cell">${t.gpt_score != null ? t.gpt_score + "/" + (t.gpt_max != null ? t.gpt_max : MAX_SCORE) : "—"}</span></td>
          <td class="num"><span class="score-cell">${t.claude_score != null ? t.claude_score + "/" + (t.claude_max != null ? t.claude_max : MAX_SCORE) : "—"}</span></td>
          <td><a href="/transcript/${escapeHtml(t.persona)}/${escapeHtml(t.number)}">Read</a></td>
        </tr>`
        )
        .join("");
    }

    document.querySelectorAll("#transcripts-table thead th[data-sort]").forEach((th) => {
      th.classList.remove("sorted-asc", "sorted-desc");
      th.onclick = () => {
        const key = th.getAttribute("data-sort");
        if (sortKey === key) sortDir *= -1;
        else sortDir = key === "gpt_score" || key === "claude_score" ? -1 : 1;
        sortKey = key;
        document.querySelectorAll("#transcripts-table thead th[data-sort]").forEach((h) => h.classList.remove("sorted-asc", "sorted-desc"));
        th.classList.add(sortDir === 1 ? "sorted-asc" : "sorted-desc");
        renderTable();
      };
    });
    var gptTh = document.querySelector('#transcripts-table thead th[data-sort="gpt_score"]');
    if (gptTh) gptTh.classList.add("sorted-desc");
    renderTable();
  }

  function escapeHtml(s) {
    if (s == null) return "";
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function renderGradeReport(container, grade, evaluatorLabel, cssClass) {
    if (!grade) {
      container.innerHTML = `<p class="text-muted">No ${evaluatorLabel} grade available.</p>`;
      return;
    }
    const model = grade.model ? (grade.model.provider + " / " + grade.model.model) : "";
    let html =
      "<h3>\n        " +
      escapeHtml(evaluatorLabel) +
      '\n        <span class="total-score">' +
      grade.total_score +
      "/" +
      grade.max_score +
      "</span>\n      </h3>\n      " +
      (model ? '<p style="font-size:0.8rem;color:var(--text-muted);margin:-0.5rem 0 0.5rem">' + escapeHtml(model) + "</p>" : "");
    if (grade.overview && grade.overview.length) {
      html += '<div class="overview"><ul>';
      grade.overview.forEach((line) => {
        html += "<li>" + escapeHtml(line) + "</li>";
      });
      html += "</ul></div>";
    }
    if (grade.sections) {
      html += '<div class="sections">';
      for (const [secId, sec] of Object.entries(grade.sections)) {
        if (!sec.criteria) continue;
        html += '<div class="section-block"><h4>' + escapeHtml(secId) + "</h4>";
        for (const [cId, c] of Object.entries(sec.criteria)) {
          html += '<div class="criterion">';
          html += '<span class="name">' + escapeHtml(c.name) + '</span>';
          html += '<span class="score">' + c.score + '/' + c.max + '</span>';
          html += '</div>';
          if (c.deductions && c.deductions.length) {
            c.deductions.forEach((d) => {
              html += '<div class="deduction">−' + d.points + ': ' + escapeHtml(d.reason) + '</div>';
            });
          }
        }
        if (sec.bonus && sec.bonus.score != null && sec.bonus.score > 0) {
          html += '<div class="criterion"><span class="name">Bonus: ' + escapeHtml(sec.bonus.id || 'bonus') + '</span><span class="score">+' + sec.bonus.score + '</span></div>';
          if (sec.bonus.explanation) html += '<div class="deduction" style="color:var(--score-high)">' + escapeHtml(sec.bonus.explanation) + '</div>';
        }
        html += "</div>";
      }
      html += "</div>";
    }
    container.className = "grade-report " + cssClass;
    container.innerHTML = html;
  }

  function renderTranscript(data) {
    const meta = data.metadata || {};
    const metaFields = [
      ["Tutor prompt", meta.tutor_prompt],
      ["Student persona", meta.student_persona],
      ["Course", meta.course],
      ["Exercise", meta.exercise_number],
      ["Turns", meta.turns],
      ["Judge", meta.judge_prompt],
    ];
    let html = '<dl class="meta-block">';
    metaFields.forEach(([label, value]) => {
      if (value == null) return;
      html += "<dt>" + escapeHtml(label) + "</dt><dd>" + escapeHtml(String(value)) + "</dd>";
    });
    html += "</dl>";

    if (meta.context) {
      html += '<details class="meta-block"><summary>Context</summary><pre style="white-space:pre-wrap;font-size:0.85rem;margin:0.5rem 0 0">' + escapeHtml(meta.context) + "</pre></details>";
    }
    if (meta.exercise) {
      html += '<details class="meta-block"><summary>Exercise</summary><pre style="white-space:pre-wrap;font-size:0.85rem;margin:0.5rem 0 0">' + escapeHtml(meta.exercise) + "</pre></details>";
    }

    (data.exchanges || []).forEach((ex) => {
      html += '<div class="exchange">';
      html += '<div class="turn-badge">Turn ' + ex.turn + "</div>";
      html += '<div class="student"><strong>Student:</strong><br/>' + escapeHtml(ex.student || "") + "</div>";
      html += '<div class="tutor"><strong>Tutor:</strong><br/>' + escapeHtml(ex.tutor || "") + "</div>";
      if (ex.pedagogical_reasoning) {
        html += '<div class="reasoning"><strong>Pedagogical reasoning:</strong><br/>' + escapeHtml(ex.pedagogical_reasoning) + "</div>";
      }
      html += "</div>";
    });

    const gptEl = document.createElement("div");
    const claudeEl = document.createElement("div");
    renderGradeReport(gptEl, data.grade_gpt, "GPT evaluator", "gpt");
    renderGradeReport(claudeEl, data.grade_claude, "Claude evaluator", "claude");

    document.getElementById("transcript-title").textContent = `${data.persona} / transcript_${data.number}`;
    const content = document.getElementById("transcript-content");
    content.innerHTML = html;
    content.appendChild(gptEl);
    content.appendChild(claudeEl);
  }

  async function loadDashboard() {
    showPage("dashboard-page");
    const tbody = document.getElementById("transcripts-tbody");
    tbody.innerHTML = '<tr><td colspan="6" class="loading">Loading…</td></tr>';
    try {
      const r = await fetch("/api/transcripts");
      const list = await r.json();
      if (!r.ok) throw new Error(list.error || "Failed to load");
      if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="error">No transcripts found. Check that the server is run from the repo root (or set TRANSCRIPTS_DIR).</td></tr>';
        return;
      }
      renderDashboard(list);
    } catch (e) {
      console.error("Failed to load transcripts:", e);
      tbody.innerHTML = '<tr><td colspan="6" class="error">' + escapeHtml(e.message) + "</td></tr>";
    }
  }

  async function loadTranscript(persona, num) {
    showPage("transcript-page");
    const content = document.getElementById("transcript-content");
    content.innerHTML = '<p class="loading">Loading transcript…</p>';
    try {
      const r = await fetch("/api/transcripts/" + encodeURIComponent(persona) + "/" + encodeURIComponent(num));
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Not found");
      renderTranscript(data);
    } catch (e) {
      content.innerHTML = '<p class="error">' + escapeHtml(e.message) + "</p>";
    }
  }

  function route() {
    const transcript = isTranscriptPage();
    if (transcript) {
      loadTranscript(transcript.persona, transcript.num);
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
