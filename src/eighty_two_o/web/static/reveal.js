// Reveal the season one game (or race) at a time, like a scoreboard ticking through it.
// Without JavaScript the server-rendered page simply shows every result and the summary.
(() => {
  "use strict";

  const STEP_MS = 350;
  const list = document.querySelector("[data-reveal]");
  if (!list) return;

  const rows = Array.from(list.querySelectorAll("[data-game]"));
  const unit = list.dataset.unit || "Game";
  const summary = document.querySelector("[data-summary]");
  const winsEl = document.querySelector("[data-wins]");
  const lossesEl = document.querySelector("[data-losses]");
  const streakEl = document.querySelector("[data-streak]");
  const streakLabel = document.querySelector("[data-streak-label]");
  const counter = document.querySelector("[data-counter]");
  const skip = document.querySelector("[data-skip]");

  let shown = 0;
  let wins = 0;
  let losses = 0;
  let streak = 0;
  let timer = null;

  const render = () => {
    winsEl.textContent = String(wins);
    lossesEl.textContent = String(losses);
    streakEl.textContent = String(streak);
    counter.textContent = `${unit} ${shown} of ${rows.length}`;
  };

  const revealNext = (animate) => {
    const row = rows[shown];
    shown += 1;
    row.hidden = false;
    if (row.dataset.won === "1") {
      wins += 1;
      streak += 1;
    } else {
      losses += 1;
      streak = 0;
      if (animate && losses === 1) row.classList.add("flash");
    }
    if (animate) row.scrollIntoView({ block: "nearest" });
  };

  const finish = () => {
    window.clearInterval(timer);
    while (shown < rows.length) revealNext(false);
    render();
    streakLabel.textContent = "Longest win streak";
    streakEl.textContent = streakEl.dataset.longest;
    counter.hidden = true;
    skip.hidden = true;
    summary.hidden = false;
  };

  const step = () => {
    if (shown >= rows.length) {
      finish();
      return;
    }
    revealNext(true);
    render();
  };

  rows.forEach((row) => {
    row.hidden = true;
  });
  summary.hidden = true;
  streakLabel.textContent = "Win streak";
  counter.hidden = false;
  skip.hidden = false;
  skip.addEventListener("click", finish);
  render();

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduceMotion) {
    finish();
  } else {
    timer = window.setInterval(step, STEP_MS);
  }
})();
