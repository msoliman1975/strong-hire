// Homepage "Choose who you face": swaps the interviewer's follow-up for the chosen tone and
// difficulty. The replies come from the JSON block index.astro writes, so the copy has one
// source. A plain file, so the strict CSP allows it (script-src 'self'). Without JavaScript the
// controls stay hidden and the page shows the "Like the company", Realistic reply.
(() => {
  const data = document.getElementById("tone-demo-data");
  const controls = document.querySelector("[data-tone-demo-controls]");
  if (!data || !controls) return;

  const demo = JSON.parse(data.textContent);
  const reply = document.querySelector("[data-tone-demo-reply]");
  const label = document.querySelector("[data-tone-demo-label]");
  const note = document.querySelector("[data-tone-demo-note]");
  const state = {
    tone: controls.querySelector('[data-tone][aria-pressed="true"]').dataset.tone,
    level: controls.querySelector('[data-level][aria-pressed="true"]').dataset.level,
  };

  const render = () => {
    for (const b of controls.querySelectorAll("[data-tone]")) b.setAttribute("aria-pressed", String(b.dataset.tone === state.tone));
    for (const b of controls.querySelectorAll("[data-level]")) b.setAttribute("aria-pressed", String(b.dataset.level === state.level));
    reply.textContent = demo.replies[state.tone][state.level];
    label.textContent = `${demo.labels[state.tone]} · ${demo.labels[state.level]}`;
    note.textContent = demo.notes[state.level];
  };

  controls.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.tone) state.tone = button.dataset.tone;
    if (button.dataset.level) state.level = button.dataset.level;
    render();
  });

  controls.hidden = false;
})();
