const form = document.getElementById("form");
const topicEl = document.getElementById("topic");
const goBtn = document.getElementById("go");
const stepsEl = document.getElementById("steps");
const statusEl = document.getElementById("status");
const outputEl = document.getElementById("output");
const actionsEl = document.getElementById("actions");

const LABELS = {
  router: "Deciding if research is needed",
  research: "Researching the web",
  orchestrator: "Planning the blog",
  worker: "Writing sections",
  reducer: "Assembling the blog",
  evaluate: "Reviewing quality",
};

let source = null,
  round = 1,
  markdown = "",
  plannedTasks = 0,
  finished = false;

const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const safeUrl = (u) => (/^https?:\/\//i.test(u) ? u : "#");

function setStatus(text, cls = "") {
  statusEl.textContent = text;
  statusEl.className = "status " + cls;
}

function getStep(key, title) {
  let li = stepsEl.querySelector(`[data-key="${key}"]`);
  if (!li) {
    li = document.createElement("li");
    li.className = "step";
    li.dataset.key = key;
    li.innerHTML = `<b></b><div class="detail"></div><div class="extra"></div>`;
    li.querySelector("b").textContent = title;
    stepsEl.appendChild(li);
  }
  return li;
}

function markActive(li) {
  stepsEl.querySelectorAll(".step.active").forEach((s) => {
    if (s !== li) {
      s.classList.remove("active");
      s.classList.add("done");
    }
  });
}

function onStep(d) {
  const node = d.node,
    suffix = round > 1 ? ` (round ${round})` : "";
  const li = getStep(`${node}-${round}`, LABELS[node] + suffix);
  const detail = li.querySelector(".detail"),
    extra = li.querySelector(".extra");
  markActive(li);
  li.classList.add("active");

  if (node === "router") {
    detail.textContent =
      `Mode: ${d.mode}` +
      (d.queries.length
        ? ` · ${d.queries.length} search queries`
        : " · no search needed");
    extra.innerHTML = d.queries.length
      ? `<ul>${d.queries.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>`
      : "";
  } else if (node === "research") {
    detail.textContent = `${d.count} useful sources found`;
    extra.innerHTML = `<ul>${d.sources.map((s) => `<li><a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener">${esc(s.title)}</a></li>`).join("")}</ul>`;
  } else if (node === "orchestrator") {
    plannedTasks = d.tasks.length;
    detail.textContent = `“${d.title}” · ${d.tasks.length} sections`;
    extra.innerHTML = `<ul>${d.tasks.map((t) => `<li>${esc(t.title)} <i>(${esc(t.worker)}, ~${t.words} words)</i></li>`).join("")}</ul>`;
  } else if (node === "worker") {
    const done = (+li.dataset.done || 0) + 1;
    li.dataset.done = done;
    detail.textContent = `${done} of ${plannedTasks} sections written`;
    if (done >= plannedTasks) {
      li.classList.remove("active");
      li.classList.add("done");
    }
  } else if (node === "reducer") {
    detail.textContent = "Sections combined in order";
    li.classList.remove("active");
    li.classList.add("done");
  } else if (node === "evaluate") {
    const ok = d.evaluation === "approved";
    detail.textContent = ok
      ? "Approved"
      : "Needs improvement. Re-planning with feedback.";
    extra.innerHTML = d.feedback ? `<ul><li>${esc(d.feedback)}</li></ul>` : "";
    li.classList.remove("active");
    li.classList.add(ok ? "done" : "warn");
    round = d.iteration; // iteration is already incremented by the agent
  }
  li.scrollIntoView({ block: "nearest" });
}

function showBlog(md) {
  markdown = md;
  outputEl.innerHTML = DOMPurify.sanitize(marked.parse(md));
  actionsEl.hidden = !md;
}

function finish(text, cls) {
  finished = true;
  if (source) source.close();
  stepsEl.querySelectorAll(".step.active").forEach((s) => {
    s.classList.remove("active");
    s.classList.add("done");
  });
  setStatus(text, cls);
  goBtn.disabled = false;
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const topic = topicEl.value.trim();
  if (!topic) return;
  if (source) source.close();

  round = 1;
  plannedTasks = 0;
  finished = false;
  markdown = "";
  stepsEl.innerHTML = "";
  outputEl.innerHTML = `<p class="empty">Writing… the blog will appear when the agent finishes.</p>`;
  actionsEl.hidden = true;
  goBtn.disabled = true;
  setStatus("Running", "running");

  source = new EventSource(`/api/generate?topic=${encodeURIComponent(topic)}`);
  source.addEventListener("step", (ev) => onStep(JSON.parse(ev.data)));
  source.addEventListener("final", (ev) =>
    showBlog(JSON.parse(ev.data).markdown),
  );
  source.addEventListener("error", (ev) => {
    if (ev.data) {
      const msg = JSON.parse(ev.data).message;
      outputEl.innerHTML = `<p class="empty">Something went wrong: ${esc(msg)}</p>`;
      finish("Failed", "error");
    } else if (!finished) {
      finish("Connection lost", "error"); // network error, not an agent error
    }
  });
  source.addEventListener("done", () => {
    if (!finished) finish("Done", "done");
  });
});

document.getElementById("copy").addEventListener("click", async (e) => {
  await navigator.clipboard.writeText(markdown);
  e.target.textContent = "Copied";
  setTimeout(() => (e.target.textContent = "Copy markdown"), 1500);
});

document.getElementById("download").addEventListener("click", () => {
  const name = ((markdown.match(/^#\s+(.+)$/m) || [])[1] || "blog")
    .replace(/[^\w\- ]+/g, "")
    .trim()
    .replace(/\s+/g, "_")
    .toLowerCase();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([markdown], { type: "text/markdown" }));
  a.download = `${name}.md`;
  a.click();
  URL.revokeObjectURL(a.href);
});


document.getElementById("copy-text").addEventListener("click", async (e) => {
  const btn = e.target;
  try {
    await navigator.clipboard.write([
      new ClipboardItem({
        "text/html": new Blob([outputEl.innerHTML], { type: "text/html" }),
        "text/plain": new Blob([outputEl.innerText], { type: "text/plain" }),
      }),
    ]);
    btn.textContent = "Copied";
  } catch {
    btn.textContent = "Copy failed";
  }
  setTimeout(() => (btn.textContent = "Copy"), 1500);
});