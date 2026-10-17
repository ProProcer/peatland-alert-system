"use strict";

const files = { features: "features.json", cells: "cells.geojson", risk: "risk.json", dispatch: "dispatch.json" };
let feeds = {};
let loadVersion = 0;
const mapBounds = { west: 108, east: 119.5, south: -4.5, north: 4.5 };
const mapColors = { LOW: "#32945b", MODERATE: "#e9c643", HIGH: "#e78b38", CRITICAL: "#d64b57" };
let mapView;
let selectedCell;
let peatland;
let peatlandPaths = [];
function polygonPath(polygon) {
  return polygon.map(ring => ring.map((point, index) => `${index ? "L" : "M"}${project(point).join(",")}`).join(" ") + " Z").join(" ");
}
async function loadPeatland() {
  try {
    const response = await fetch("assets/peatland.geojson");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    peatland = await response.json();
    peatlandPaths = peatland.features.flatMap(feature => feature.geometry.coordinates.map(polygonPath));
    document.querySelector("#peat-status").textContent = "Peatland boundaries: bundled Indonesian peatland dataset. Risk colors are restricted to mapped peatland.";
    if (feeds.risk) renderMap(Number(document.querySelector("#horizon").value));
  } catch (error) {
    document.querySelector("#peat-status").textContent = `Peatland boundaries unavailable (${error.message}). Risk shading is hidden to avoid showing non-peat areas as peatland.`;
  }
}
let tileTimer;
let tileGeneration = 0;
let tileSignature = "";
const project = ([lon, lat]) => [256 * 64 * (lon + 180) / 360, 256 * 64 * (1 - Math.asinh(Math.tan(lat * Math.PI / 180)) / Math.PI) / 2];
const mapNW = project([mapBounds.west, mapBounds.north]);
const mapSE = project([mapBounds.east, mapBounds.south]);
const regionView = [mapNW[0], mapNW[1], mapSE[0] - mapNW[0], mapSE[1] - mapNW[1]];
function setMapView(view) {
  const width = Math.min(regionView[2], Math.max(20, view[2]));
  const height = width * regionView[3] / regionView[2];
  mapView = [Math.max(regionView[0], Math.min(view[0], mapSE[0] - width)), Math.max(regionView[1], Math.min(view[1], mapSE[1] - height)), width, height];
  document.querySelector("#map").setAttribute("viewBox", mapView.join(" "));
  updateRiskLabels();
  clearTimeout(tileTimer);
  tileTimer = setTimeout(updateMapTiles, 160);
}
function mapPixelScale() {
  const map = document.querySelector("#map");
  return Math.min((map.clientWidth || 900) / mapView[2], (map.clientHeight || 650) / mapView[3]);
}
function updateRiskLabels() {
  if (!mapView) return;
  const scale = mapPixelScale();
  for (const label of document.querySelectorAll(".risk-map-label")) {
    label.setAttribute("font-size", 11 / scale);
    label.setAttribute("display", Number(label.dataset.cellWidth) * scale >= 65 ? "block" : "none");
  }
  for (const marker of document.querySelectorAll(".risk-map-marker")) marker.setAttribute("r", 4 / scale);
}
function updateMapTiles() {
  const map = document.querySelector("#map");
  const layer = document.querySelector("#map-tiles");
  if (!mapView || !layer) return;
  const [left, top, width, height] = mapView;
  const zoom = Math.max(6, Math.min(18, Math.ceil(6 + Math.log2(mapPixelScale() * Math.min(window.devicePixelRatio || 1, 2)))));
  const size = 256 / 2 ** (zoom - 6);
  const bounds = [Math.floor(left / size), Math.floor(top / size), Math.floor((left + width) / size), Math.floor((top + height) / size)];
  const signature = [zoom, ...bounds].join(":");
  if (signature === tileSignature) return;
  tileSignature = signature;
  const generation = ++tileGeneration;
  const pending = svgElement("g", { "aria-hidden": "true" });
  let remaining = (bounds[2] - bounds[0] + 1) * (bounds[3] - bounds[1] + 1);
  let failures = 0;
  const complete = failed => {
    if (failed) failures++;
    if (--remaining || generation !== tileGeneration) return;
    for (const child of Array.from(layer.children)) if (child !== pending) child.remove();
    document.querySelector("#map-tile-status").textContent = failures ? "Some background tiles are unavailable. Risk overlays remain available." : "";
    if (failures) tileSignature = "";
  };
  for (let x = bounds[0]; x <= bounds[2]; x++) {
    for (let y = bounds[1]; y <= bounds[3]; y++) {
      const tile = svgElement("image", { x: x * size, y: y * size, width: size, height: size });
      tile.addEventListener("load", () => complete(false), { once: true });
      tile.addEventListener("error", () => complete(true), { once: true });
      tile.setAttribute("href", `https://tile.openstreetmap.org/${zoom}/${x}/${y}.png`);
      pending.append(tile);
    }
  }
  // Keep the previous tiles underneath until the replacement tiles finish loading.
  layer.append(pending);
}
function svgElement(tag, attributes) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}
function regionalCells() {
  return feeds.cells.data.features.filter(feature => feature.geometry.type === "Polygon" && feature.geometry.coordinates[0].every(([lon, lat]) => lon >= mapBounds.west && lon <= mapBounds.east && lat >= mapBounds.south && lat <= mapBounds.north));
}
function renderMap(horizon) {
  const map = document.querySelector("#map");
  map.replaceChildren();
  tileSignature = "";
  tileGeneration++;
  map.append(svgElement("g", { id: "map-tiles", "aria-hidden": "true" }));
  if (!mapView) setMapView(regionView.slice());
  const definitions = svgElement("defs", {});
  const clip = svgElement("clipPath", { id: "peatland-clip", clipPathUnits: "userSpaceOnUse" });
  const peatLayer = svgElement("g", { class: "peatland-layer", "aria-hidden": "true" });
  for (const d of peatlandPaths) {
    clip.append(svgElement("path", { d, "clip-rule": "evenodd" }));
    peatLayer.append(svgElement("path", { d, "fill-rule": "evenodd" }));
  }
  definitions.append(clip);
  map.append(definitions, peatLayer);
  const riskLayer = svgElement("g", { "clip-path": "url(#peatland-clip)" });
  map.append(riskLayer);
  const risks = new Map(feeds.risk.data.filter(row => row.horizon_h === horizon).map(row => [row.cell_id, row]));
  document.querySelector("#map-detail").textContent = "Select a colored cell for its prediction and contributing signals.";
  for (const feature of regionalCells()) {
    const id = feature.properties.cell_id;
    const risk = risks.get(id);
    const description = risk ? `${id}: ${risk.risk_level}, score ${risk.risk_score.toFixed(2)}, ${horizon}h. ${risk.top_factors.map(f => `${f.feature}: ${f.contribution}`).join(", ")}. Timestamp: ${risk.ts}.` : `${id}: no prediction for ${horizon}h.`;
    const path = feature.geometry.coordinates.map(ring => ring.map((point, index) => `${index ? "L" : "M"}${project(point).join(",")}`).join(" ") + " Z").join(" ");
    const cell = svgElement("path", { d: path, fill: mapColors[risk?.risk_level] || "#bdcdb8", "fill-rule": "evenodd", class: "map-cell", tabindex: 0, role: "button", "aria-label": description, "aria-pressed": selectedCell === id });
    const title = svgElement("title", {});
    title.textContent = description;
    cell.append(title);
    const select = () => {
      selectedCell = id;
      for (const other of map.querySelectorAll(".map-cell")) other.setAttribute("aria-pressed", other === cell);
      document.querySelector("#map-detail").textContent = description;
    };
    cell.addEventListener("click", select);
    cell.addEventListener("keydown", event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); select(); } });
    riskLayer.append(cell);
    const points = feature.geometry.coordinates[0].map(project);
    const xs = points.map(point => point[0]), ys = points.map(point => point[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const marker = svgElement("circle", { cx, cy, r: 1, fill: mapColors[risk?.risk_level] || "#bdcdb8", class: "risk-map-marker", "aria-hidden": "true" });
    const label = svgElement("text", { x: cx, y: cy, "text-anchor": "middle", "dominant-baseline": "central", class: "risk-map-label", "data-cell-width": Math.max(...xs) - Math.min(...xs), "aria-hidden": "true" });
    label.textContent = risk ? `${risk.risk_level} · ${risk.risk_score.toFixed(2)}` : "NO DATA";
    riskLayer.append(marker, label);
    if (selectedCell === id) document.querySelector("#map-detail").textContent = description;
  }
  if (!regionalCells().length) document.querySelector("#map-detail").textContent = "No cell geometry is available within the Kalimantan regional bounds.";
  updateRiskLabels();
  clearTimeout(tileTimer);
  updateMapTiles();
}
function zoomMap(factor, anchor) {
  const [x, y, width, height] = mapView || regionView;
  const nextWidth = Math.min(regionView[2], Math.max(20, width * factor));
  const nextHeight = nextWidth * regionView[3] / regionView[2];
  const [ax, ay] = anchor || [x + width / 2, y + height / 2];
  setMapView([ax - (ax - x) * nextWidth / width, ay - (ay - y) * nextHeight / height, nextWidth, nextHeight]);
}

const mapElement = document.querySelector("#map");
window.addEventListener("resize", () => {
  updateRiskLabels();
  clearTimeout(tileTimer);
  tileTimer = setTimeout(updateMapTiles, 160);
});
let mapDrag = null;
let suppressMapClick = false;
function pointerOnMap(event, inverse = mapElement.getScreenCTM()?.inverse()) {
  if (!inverse) return null;
  const point = mapElement.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  return point.matrixTransform(inverse);
}
mapElement.addEventListener("wheel", event => {
  event.preventDefault();
  if (mapDrag) return;
  const point = pointerOnMap(event);
  if (!point) return;
  // Normalize wheel units: pixels, lines, or pages; cap large trackpad bursts.
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? mapElement.clientHeight : 1;
  const delta = Math.max(-200, Math.min(200, event.deltaY * unit));
  zoomMap(Math.exp(delta * .003), [point.x, point.y]);
}, { passive: false });
mapElement.addEventListener("pointerdown", event => {
  if (event.button !== 0 || mapDrag) return;
  const inverse = mapElement.getScreenCTM()?.inverse();
  const point = pointerOnMap(event, inverse);
  if (!point) return;
  suppressMapClick = false;
  mapDrag = { id: event.pointerId, inverse, point, view: (mapView || regionView).slice(), x: event.clientX, y: event.clientY, moved: false };
});
mapElement.addEventListener("pointermove", event => {
  if (!mapDrag || event.pointerId !== mapDrag.id) return;
  if (!mapDrag.moved && Math.hypot(event.clientX - mapDrag.x, event.clientY - mapDrag.y) < 5) return;
  if (!mapDrag.moved) {
    mapDrag.moved = true;
    mapElement.setPointerCapture(event.pointerId);
    mapElement.classList.add("is-dragging");
  }
  const point = pointerOnMap(event, mapDrag.inverse);
  setMapView([mapDrag.view[0] + mapDrag.point.x - point.x, mapDrag.view[1] + mapDrag.point.y - point.y, mapDrag.view[2], mapDrag.view[3]]);
});
function finishMapDrag(event) {
  if (!mapDrag || event.pointerId !== mapDrag.id) return;
  suppressMapClick = mapDrag.moved;
  mapDrag = null;
  mapElement.classList.remove("is-dragging");
  if (mapElement.hasPointerCapture(event.pointerId)) mapElement.releasePointerCapture(event.pointerId);
}
mapElement.addEventListener("pointerup", finishMapDrag);
mapElement.addEventListener("pointercancel", finishMapDrag);
mapElement.addEventListener("lostpointercapture", finishMapDrag);
mapElement.addEventListener("pointerleave", event => { if (mapDrag && !mapDrag.moved) finishMapDrag(event); });
mapElement.addEventListener("click", event => {
  if (suppressMapClick && event.detail !== 0) {
    event.stopPropagation();
    event.preventDefault();
    suppressMapClick = false;
  }
}, true);

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
  renderMap(horizon);
  document.querySelector("#summary-horizon").textContent = horizon;
  document.querySelector("#priority-count").textContent = feeds.risk.data.filter(row => row.horizon_h === horizon && ["HIGH", "CRITICAL"].includes(row.risk_level)).length;
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
document.querySelector("#map-in").addEventListener("click", () => zoomMap(.5));
document.querySelector("#map-out").addEventListener("click", () => zoomMap(2));
document.querySelector("#map-reset").addEventListener("click", () => setMapView(regionView.slice()));
document.querySelector("#map-cells").addEventListener("click", () => {
  if (!feeds.cells) return;
  const points = regionalCells().flatMap(feature => feature.geometry.coordinates[0].map(project));
  if (!points.length) return;
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  const width = Math.max(30, Math.max(...xs) - Math.min(...xs) + 20, (Math.max(...ys) - Math.min(...ys) + 20) * regionView[2] / regionView[3]);
  const height = width * regionView[3] / regionView[2];
  setMapView([(Math.min(...xs) + Math.max(...xs) - width) / 2, (Math.min(...ys) + Math.max(...ys) - height) / 2, width, height]);
});
loadPeatland();
reload();
