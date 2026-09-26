const API_BASE_A = "/api";

let analyticsLoaded = false;

const SVG_NS = "http://www.w3.org/2000/svg";

function fmtCompact(n) {
  return new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

function fmtFull(n) {
  return new Intl.NumberFormat("en-IN").format(n);
}

function truncateLabel(text, maxChars) {
  if (text.length <= maxChars) return text;
  return text.slice(0, maxChars - 1) + "…";
}

function svgEl(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    el.setAttribute(k, v);
  }
  return el;
}

function ensureTooltip(container) {
  let tooltip = container.querySelector(".chart-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    container.appendChild(tooltip);
  }
  return tooltip;
}

function showTooltip(container, tooltip, x, y, valueText, labelText) {
  tooltip.innerHTML = "";
  const valueSpan = document.createElement("span");
  valueSpan.className = "tt-value";
  valueSpan.textContent = valueText;
  const labelSpan = document.createElement("span");
  labelSpan.className = "tt-label";
  labelSpan.textContent = labelText;
  tooltip.appendChild(valueSpan);
  tooltip.appendChild(labelSpan);

  const rect = container.getBoundingClientRect();
  tooltip.style.left = `${(x / container._vbWidth) * rect.width}px`;
  tooltip.style.top = `${(y / container._vbHeight) * rect.height - 8}px`;
  tooltip.classList.add("visible");
}

function hideTooltip(tooltip) {
  tooltip.classList.remove("visible");
}

/**
 * Horizontal bar chart: one series, magnitude only (see dataviz skill --
 * single-series charts use one hue throughout, no legend needed).
 */
function renderBarChart(container, data, color) {
  container.innerHTML = "";
  if (!data.length) {
    container.innerHTML = '<p class="chart-loading">No data available.</p>';
    return;
  }

  const rowHeight = 34;
  const barThickness = 20;
  const labelColW = 190;
  const chartW = 680;
  const rightPad = 55; // room for value labels
  const topPad = 10;
  const bottomPad = 28;
  const barAreaW = chartW - labelColW - rightPad;
  const height = data.length * rowHeight + topPad + bottomPad;

  const svg = svgEl("svg", { viewBox: `0 0 ${chartW} ${height}`, role: "img" });
  container.appendChild(svg);
  container._vbWidth = chartW;
  container._vbHeight = height;

  const maxValue = Math.max(...data.map((d) => d.value));
  const scale = (v) => (v / maxValue) * barAreaW;

  // Gridlines at 0/25/50/75/100%
  for (let f = 0; f <= 1; f += 0.25) {
    const gx = labelColW + barAreaW * f;
    svg.appendChild(
      svgEl("line", {
        x1: gx, x2: gx,
        y1: topPad, y2: topPad + data.length * rowHeight,
        class: "chart-gridline",
      })
    );
    const tick = svgEl("text", {
      x: gx, y: topPad + data.length * rowHeight + 18,
      class: "chart-axis-label", "text-anchor": "middle",
    });
    tick.textContent = fmtCompact(maxValue * f);
    svg.appendChild(tick);
  }

  const tooltip = ensureTooltip(container);

  data.forEach((d, i) => {
    const y = topPad + i * rowHeight;
    const barY = y + (rowHeight - barThickness) / 2;
    const w = Math.max(scale(d.value), 2);

    const label = svgEl("text", {
      x: labelColW - 10, y: y + rowHeight / 2 + 4,
      class: "chart-axis-label", "text-anchor": "end",
    });
    label.textContent = truncateLabel(d.label, 26);
    svg.appendChild(label);

    const radius = 4;
    const x0 = labelColW;
    const path = svgEl("path", {
      d: `M ${x0},${barY} H ${x0 + w - radius} A ${radius},${radius} 0 0 1 ${x0 + w},${barY + radius} ` +
         `V ${barY + barThickness - radius} A ${radius},${radius} 0 0 1 ${x0 + w - radius},${barY + barThickness} ` +
         `H ${x0} Z`,
      fill: color,
      class: "bar-mark",
      tabindex: "0",
    });
    svg.appendChild(path);

    const valueLabel = svgEl("text", {
      x: x0 + w + 8, y: y + rowHeight / 2 + 4,
      class: "chart-value-label",
    });
    valueLabel.textContent = fmtCompact(d.value);
    svg.appendChild(valueLabel);

    const onEnter = () => {
      path.classList.add("hovered");
      showTooltip(container, tooltip, x0 + w / 2, barY, fmtFull(d.value), d.label);
    };
    const onLeave = () => {
      path.classList.remove("hovered");
      hideTooltip(tooltip);
    };
    path.addEventListener("pointerenter", onEnter);
    path.addEventListener("focus", onEnter);
    path.addEventListener("pointerleave", onLeave);
    path.addEventListener("blur", onLeave);
  });
}

/**
 * Line chart with crosshair + point tooltips (registrations per year).
 */
function renderLineChart(container, data, color) {
  container.innerHTML = "";
  if (!data.length) {
    container.innerHTML = '<p class="chart-loading">No data available.</p>';
    return;
  }

  const chartW = 680;
  const height = 260;
  const leftPad = 55;
  const rightPad = 15;
  const topPad = 15;
  const bottomPad = 30;
  const plotW = chartW - leftPad - rightPad;
  const plotH = height - topPad - bottomPad;

  const svg = svgEl("svg", { viewBox: `0 0 ${chartW} ${height}`, role: "img" });
  container.appendChild(svg);
  container._vbWidth = chartW;
  container._vbHeight = height;

  const maxValue = Math.max(...data.map((d) => d.value));
  const xFor = (i) => leftPad + (data.length === 1 ? plotW / 2 : (i / (data.length - 1)) * plotW);
  const yFor = (v) => topPad + plotH - (v / maxValue) * plotH;

  for (let f = 0; f <= 1; f += 0.25) {
    const gy = topPad + plotH * (1 - f);
    svg.appendChild(svgEl("line", { x1: leftPad, x2: leftPad + plotW, y1: gy, y2: gy, class: "chart-gridline" }));
    const tick = svgEl("text", { x: leftPad - 10, y: gy + 4, class: "chart-axis-label", "text-anchor": "end" });
    tick.textContent = fmtCompact(maxValue * f);
    svg.appendChild(tick);
  }

  data.forEach((d, i) => {
    const label = svgEl("text", {
      x: xFor(i), y: height - 8, class: "chart-axis-label", "text-anchor": "middle",
    });
    label.textContent = d.year;
    svg.appendChild(label);
  });

  const points = data.map((d, i) => `${xFor(i)},${yFor(d.value)}`).join(" ");
  svg.appendChild(svgEl("polyline", { points, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));

  data.forEach((d, i) => {
    svg.appendChild(
      svgEl("circle", { cx: xFor(i), cy: yFor(d.value), r: 5, fill: color, stroke: "var(--card)", "stroke-width": 2 })
    );
  });

  const crosshair = svgEl("line", { x1: 0, x2: 0, y1: topPad, y2: topPad + plotH, class: "chart-crosshair hidden" });
  svg.appendChild(crosshair);

  const tooltip = ensureTooltip(container);

  const hitArea = svgEl("rect", { x: leftPad, y: topPad, width: plotW, height: plotH, fill: "transparent" });
  svg.appendChild(hitArea);

  hitArea.addEventListener("pointermove", (e) => {
    const rect = svg.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * chartW;
    let nearest = 0;
    let minDist = Infinity;
    data.forEach((d, i) => {
      const dist = Math.abs(xFor(i) - px);
      if (dist < minDist) {
        minDist = dist;
        nearest = i;
      }
    });
    crosshair.setAttribute("x1", xFor(nearest));
    crosshair.setAttribute("x2", xFor(nearest));
    crosshair.classList.remove("hidden");
    showTooltip(container, tooltip, xFor(nearest), yFor(data[nearest].value), fmtFull(data[nearest].value), `in ${data[nearest].year}`);
  });

  hitArea.addEventListener("pointerleave", () => {
    crosshair.classList.add("hidden");
    hideTooltip(tooltip);
  });
}

function renderStatTiles(container, stats) {
  container.innerHTML = "";
  const tiles = [
    { label: "Total enterprises", value: stats.total_enterprises },
    { label: "States covered", value: stats.total_states },
    { label: "Districts covered", value: stats.total_districts },
    { label: "Industries (NIC codes)", value: stats.total_industries },
  ];
  for (const t of tiles) {
    const tile = document.createElement("div");
    tile.className = "stat-tile";
    tile.innerHTML = `
      <div class="stat-label">${t.label}</div>
      <div class="stat-value">${fmtCompact(t.value)}</div>
    `;
    container.appendChild(tile);
  }
}

async function loadAnalytics() {
  if (analyticsLoaded) return;
  analyticsLoaded = true;

  const statTiles = document.getElementById("stat-tiles");
  const byStateEl = document.getElementById("chart-by-state");
  const byIndustryEl = document.getElementById("chart-by-industry");
  const byYearEl = document.getElementById("chart-by-year");

  statTiles.innerHTML = '<p class="chart-loading">Loading…</p>';
  byStateEl.innerHTML = '<p class="chart-loading">Loading…</p>';
  byIndustryEl.innerHTML = '<p class="chart-loading">Loading…</p>';
  byYearEl.innerHTML = '<p class="chart-loading">Loading…</p>';

  try {
    const [summary, byState, byIndustry, byYear] = await Promise.all([
      fetch(`${API_BASE_A}/analytics/summary`).then((r) => r.json()),
      fetch(`${API_BASE_A}/analytics/by-state`).then((r) => r.json()),
      fetch(`${API_BASE_A}/analytics/by-industry`).then((r) => r.json()),
      fetch(`${API_BASE_A}/analytics/by-year`).then((r) => r.json()),
    ]);

    renderStatTiles(statTiles, summary);
    renderBarChart(byStateEl, byState, getComputedStyle(document.documentElement).getPropertyValue("--series-state").trim());
    renderBarChart(byIndustryEl, byIndustry, getComputedStyle(document.documentElement).getPropertyValue("--series-industry").trim());
    renderLineChart(
      byYearEl,
      byYear.map((d) => ({ year: d.year, value: d.value })),
      getComputedStyle(document.documentElement).getPropertyValue("--series-year").trim()
    );
  } catch (e) {
    statTiles.innerHTML = '<p class="chart-loading">Failed to load analytics.</p>';
    analyticsLoaded = false;
  }
}

window.loadAnalytics = loadAnalytics;
