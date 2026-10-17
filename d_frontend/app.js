"use strict";

const files = { features: "features.json", cells: "cells.geojson", risk: "risk.json", dispatch: "dispatch.json" };
let feeds = {};
let loadVersion = 0;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function loadFeed(filename) {
  for (const [base, label] of [["/data/", "served handoff"], ["mocks/", "static mock"]]) {
    try {
      const response = await fetch(base + filename, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return { data: await response.json(), label, url: base + filename };
    } catch (error) {
      if (label === "static mock") throw new Error(`${filename}: ${error.message}`);
    }
  }
}

function render() {
  const horizon = Number(document.querySelector("#horizon").value);
  const riskBody = document.querySelector("#risk");
  riskBody.replaceChildren();
  for (const row of feeds.risk.data.filter(record => record.horizon_h === horizon)) {
    const tr = element("tr");
    tr.append(element("td", row.cell_id));
    const level = element("td");
    level.append(element("span", row.risk_level, `badge ${row.risk_level}`));
    tr.append(level, element("td", row.risk_score.toFixed(2)), element("td", row.top_factors.map(f => `${f.feature}: ${f.contribution}`).join(", ")));
    riskBody.append(tr);
  }
  const dispatch = document.querySelector("#dispatch");
  dispatch.replaceChildren();
  if (feeds.dispatch.data.length === 0) dispatch.append(element("p", "No active simulated dispatches."));
  for (const row of feeds.dispatch.data) {
    const article = element("article");
    article.append(element("strong", `${row.action} · ${row.cell_id} · ${row.status}`));
    article.append(element("p", `Target: ${row.target.lat}, ${row.target.lon}. Water source: ${row.water_source ? row.water_source.kind : "unavailable"}.`));
    article.append(element("p", row.rationale));
    for (const audience of row.audiences) {
      article.append(element("p", `${audience} — ID: ${row.messages[audience].id} EN: ${row.messages[audience].en}`));
    }
    dispatch.append(article);
  }
}

async function reload() {
  const version = ++loadVersion;
  const status = document.querySelector("#status");
  status.textContent = "Loading handoffs…";
  try {
    const entries = await Promise.all(Object.entries(files).map(async ([kind, filename]) => [kind, await loadFeed(filename)]));
    if (version !== loadVersion) return;
    feeds = Object.fromEntries(entries);
    const sources = document.querySelector("#sources");
    sources.replaceChildren();
    for (const [kind, feed] of entries) {
      const item = element("li");
      const link = element("a", `${kind}: ${feed.label}`);
      link.href = feed.url;
      item.append(link);
      sources.append(item);
    }
    render();
    status.textContent = `${feeds.cells.data.features.length} cells · ${feeds.features.data.length} feature records · ${feeds.risk.data.length} predictions · ${feeds.dispatch.data.length} simulated dispatches`;
  } catch (error) {
    if (version === loadVersion) status.textContent = `Could not load handoffs: ${error.message}`;
  }
}

document.querySelector("#horizon").addEventListener("change", () => { if (feeds.risk) render(); });
document.querySelector("#reload").addEventListener("click", reload);
reload();
