"use strict";
const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="token"]').content;
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };

async function init() {
  const info = await (await fetch("/api/info")).json();
  for (const t of info.tools) { const li = el("li", "", t.name); li.title = t.description; $("tools").appendChild(li); }
  for (const c of info.cases) {
    const b = el("button", "chip", c.order); b.type = "button";
    b.appendChild(el("small", "", c.note));
    b.addEventListener("click", () => { $("ticket").value = c.ticket; });
    $("samples").appendChild(b);
  }
  if (!info.live_available) {
    $("live-label").classList.add("off");
    document.querySelector('input[value="live"]').disabled = true;
    $("live-note").textContent = "Not available: add GROQ_API_KEY to .env and restart the dashboard.";
  }
  $("ticket").value = info.cases[0].ticket;
}

function kv(label, text) { const d = el("div", "kv"); d.appendChild(el("span", "", label)); d.appendChild(el("code", "", text)); return d; }

function show(r) {
  $("empty").hidden = true; $("err").hidden = true; $("out").hidden = false;
  const key = r.decision === "NO DECISION" ? "NO" : r.decision;
  $("decision").className = "decision d-" + key;
  $("badge").textContent = r.decision === "NO DECISION" ? "NO DECISION" : r.decision.replace("_", " ");
  $("reason").textContent = r.reason;
  $("meta").textContent = (r.mode === "live" ? "Live model" : "Scripted model (not a model-quality test)") + " \u00b7 " + r.trace.length + " tool call" + (r.trace.length === 1 ? "" : "s") + " \u00b7 " + (r.total_ms < 1000 ? r.total_ms + " ms" : (r.total_ms / 1000).toFixed(1) + " s");
  const ol = $("trace"); ol.textContent = "";
  for (const s of r.trace) {
    const li = el("li", "step" + (s.ok ? "" : " bad"));
    const h = el("header"); h.appendChild(el("b", "", s.name)); h.appendChild(el("span", "ms", s.ms + " ms"));
    li.appendChild(h); li.appendChild(kv("Arguments", JSON.stringify(s.args))); li.appendChild(kv("Result from backend", s.result));
    ol.appendChild(li);
  }
  if (!r.trace.length) ol.appendChild(el("li", "step", "No tool was called."));
}

function fail(msg) { $("out").hidden = true; $("empty").hidden = true; $("err").hidden = false; $("err").textContent = msg; }

$("run").addEventListener("click", async () => {
  const btn = $("run"), mode = document.querySelector('input[name="mode"]:checked').value;
  btn.disabled = true; btn.textContent = "Running\u2026"; $("hint").textContent = "Calling the tools through the isolated gateway.";
  try {
    const res = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json", "X-Dashboard-Token": token }, body: JSON.stringify({ ticket: $("ticket").value, mode }) });
    const data = await res.json();
    if (!res.ok) fail(data.error || "Request failed."); else show(data);
  } catch (e) { fail("Could not reach the dashboard server."); }
  btn.disabled = false; btn.textContent = "Run ticket"; $("hint").textContent = "";
});
init().catch(() => fail("Could not load dashboard data."));
