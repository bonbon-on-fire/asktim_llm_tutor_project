"use strict";
// Render \(...\) (inline) and \[...\] (display) math with KaTeX *inside* the
// marked parse, before markdown's backslash-escaping strips the delimiters.
// $...$ is deliberately NOT a delimiter — it is currency in this course.
(function (global) {
  function makeMathExtension(katex) {
    function render(tex, displayMode) {
      return katex.renderToString(tex, { displayMode: displayMode, throwOnError: false });
    }
    return {
      extensions: [
        {
          name: "inlineMath",
          level: "inline",
          start(src) { const m = src.match(/\\\(/); return m ? m.index : undefined; },
          tokenizer(src) {
            const m = /^\\\(([\s\S]+?)\\\)/.exec(src);
            if (m) return { type: "inlineMath", raw: m[0], text: m[1] };
          },
          renderer(token) { return render(token.text, false); },
        },
        {
          name: "displayMath",
          level: "inline",
          start(src) { const m = src.match(/\\\[/); return m ? m.index : undefined; },
          tokenizer(src) {
            const m = /^\\\[([\s\S]+?)\\\]/.exec(src);
            if (m) return { type: "displayMath", raw: m[0], text: m[1] };
          },
          renderer(token) { return render(token.text, true); },
        },
      ],
    };
  }

  let cached = null; // memoized Marked instance (browser)
  function renderTutorMarkdown(content) {
    const marked = global.marked;
    const katex = global.katex;
    const DOMPurify = global.DOMPurify;
    if (!marked || !DOMPurify) return null; // caller falls back to textContent
    let html;
    if (katex) {
      if (!cached) { cached = new marked.Marked(); cached.use(makeMathExtension(katex)); }
      html = cached.parse(content || "");
    } else {
      html = marked.parse(content || ""); // KaTeX missing: math stays literal
    }
    return DOMPurify.sanitize(html);
  }

  const api = { makeMathExtension: makeMathExtension, renderTutorMarkdown: renderTutorMarkdown };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  global.renderTutorMarkdown = renderTutorMarkdown; // browser global
})(typeof globalThis !== "undefined" ? globalThis : this);
