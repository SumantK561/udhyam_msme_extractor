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

function fmtSigned(pct) {
  if (pct === null || pct === undefined) return null;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

function fmtMonthLabel(period) {
  const [y, m] = period.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[parseInt(m, 10) - 1]} '${y.slice(2)}`;
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
 * Line chart with crosshair + point tooltips.
 *
 * points: [{ label, value, projected?, delta? }]
 * - `projected` points render as a dashed continuation in a lighter step
 *   of the same hue, with hollow dots (see dataviz skill: identity by
 *   texture/style, never hue alone, for the actual-vs-forecast split).
 * - `delta` (signed % string) is direct-labeled only on the last actual
 *   point -- labeling every point would be noise.
 */
function renderLineChart(container, points, color, opts = {}) {
  container.innerHTML = "";
  if (!points.length) {
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

  const maxValue = Math.max(...points.map((d) => d.value));
  const xFor = (i) => leftPad + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
  const yFor = (v) => topPad + plotH - (v / maxValue) * plotH;

  const splitIndex = points.findIndex((d) => d.projected);

  for (let f = 0; f <= 1; f += 0.25) {
    const gy = topPad + plotH * (1 - f);
    svg.appendChild(svgEl("line", { x1: leftPad, x2: leftPad + plotW, y1: gy, y2: gy, class: "chart-gridline" }));
    const tick = svgEl("text", { x: leftPad - 10, y: gy + 4, class: "chart-axis-label", "text-anchor": "end" });
    tick.textContent = fmtCompact(maxValue * f);
    svg.appendChild(tick);
  }

  // Thin x-axis labels to avoid collision when there are many points
  const maxLabels = 9;
  const step = Math.max(1, Math.ceil(points.length / maxLabels));
  points.forEach((d, i) => {
    const isLast = i === points.length - 1;
    if (i % step !== 0 && !isLast) return;
    const label = svgEl("text", {
      x: xFor(i), y: height - 8, class: "chart-axis-label", "text-anchor": "middle",
    });
    label.textContent = opts.xLabel ? opts.xLabel(d) : d.label;
    svg.appendChild(label);
  });

  // Divider between actual and forecast
  if (splitIndex > 0) {
    const dx = (xFor(splitIndex - 1) + xFor(splitIndex)) / 2;
    svg.appendChild(svgEl("line", { x1: dx, x2: dx, y1: topPad, y2: topPad + plotH, class: "chart-gridline", "stroke-dasharray": "3 3" }));
  }

  const actualEnd = splitIndex === -1 ? points.length : splitIndex;
  const actualPoints = points.slice(0, actualEnd).map((d, i) => `${xFor(i)},${yFor(d.value)}`).join(" ");
  svg.appendChild(svgEl("polyline", { points: actualPoints, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));

  if (splitIndex > -1) {
    const forecastPoints = points.slice(splitIndex - 1).map((d, i) => `${xFor(splitIndex - 1 + i)},${yFor(d.value)}`).join(" ");
    svg.appendChild(svgEl("polyline", {
      points: forecastPoints, fill: "none", stroke: color, "stroke-width": 2,
      "stroke-linejoin": "round", "stroke-linecap": "round", "stroke-dasharray": "6 4", opacity: 0.6,
    }));
  }

  points.forEach((d, i) => {
    const isProjected = !!d.projected;
    svg.appendChild(
      svgEl("circle", {
        cx: xFor(i), cy: yFor(d.value), r: 5,
        fill: isProjected ? "var(--card)" : color,
        stroke: color, "stroke-width": 2,
        opacity: isProjected ? 0.7 : 1,
      })
    );
  });

  // Selective delta label -- last actual point only
  if (opts.showDelta && actualEnd > 0) {
    const idx = actualEnd - 1;
    const d = points[idx];
    if (d.delta !== null && d.delta !== undefined) {
      const deltaLabel = svgEl("text", {
        x: xFor(idx), y: yFor(d.value) - 14,
        class: "chart-value-label", "text-anchor": "middle",
        fill: d.delta.startsWith("-") ? "var(--delta-down)" : "var(--delta-up)",
      });
      deltaLabel.textContent = d.delta;
      svg.appendChild(deltaLabel);
    }
  }

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
    points.forEach((d, i) => {
      const dist = Math.abs(xFor(i) - px);
      if (dist < minDist) {
        minDist = dist;
        nearest = i;
      }
    });
    const d = points[nearest];
    const tagText = opts.xLabel ? opts.xLabel(d) : d.label;
    crosshair.setAttribute("x1", xFor(nearest));
    crosshair.setAttribute("x2", xFor(nearest));
    crosshair.classList.remove("hidden");
    showTooltip(
      container, tooltip, xFor(nearest), yFor(d.value),
      fmtFull(d.value),
      d.projected ? `${tagText} (forecast)` : tagText
    );
  });

  hitArea.addEventListener("pointerleave", () => {
    crosshair.classList.add("hidden");
    hideTooltip(tooltip);
  });
}

function makeTile(t, hero = false) {
  const tile = document.createElement("div");
  tile.className = hero ? "stat-tile stat-tile-hero" : "stat-tile";
  const hasDelta = t.delta !== undefined && t.delta !== null;
  const deltaClass = hasDelta ? (t.delta >= 0 ? "positive" : "negative") : "";
  const arrow = hasDelta ? (t.delta >= 0 ? "▲" : "▼") : "";
  tile.innerHTML = `
    <div class="stat-label">${t.label}</div>
    <div class="stat-value ${deltaClass}">${arrow ? `<span class="stat-arrow">${arrow}</span>` : ""}${t.value}</div>
  `;
  return tile;
}

function renderStatTiles(container, stats, momPct, yoyPct) {
  container.innerHTML = "";

  // Hero tile — total enterprises, full width
  container.appendChild(makeTile(
    { label: "Total Enterprises", value: fmtFull(stats.total_enterprises) },
    true
  ));

  // Secondary row — 5 tiles
  const row = document.createElement("div");
  row.className = "stat-tile-row";

  const secondary = [
    { label: "States covered",       value: fmtCompact(stats.total_states)     },
    { label: "Districts covered",    value: fmtCompact(stats.total_districts)   },
    { label: "Industries (NIC)",     value: fmtCompact(stats.total_industries)  },
    { label: "Month-on-Month",       value: fmtSigned(momPct) || "—", delta: momPct },
    { label: "Year-on-Year",         value: fmtSigned(yoyPct) || "—", delta: yoyPct },
  ];

  for (const t of secondary) row.appendChild(makeTile(t));
  container.appendChild(row);
}

async function loadAnalytics() {
  if (analyticsLoaded) return;
  analyticsLoaded = true;

  const statTiles = document.getElementById("stat-tiles");
  const byStateEl = document.getElementById("chart-by-state");
  const byIndustryEl = document.getElementById("chart-by-industry");
  const byYearEl = document.getElementById("chart-by-year");
  const byMonthEl = document.getElementById("chart-by-month");

  statTiles.innerHTML = '<p class="chart-loading">Loading…</p>';
  byStateEl.innerHTML = '<p class="chart-loading">Loading…</p>';
  byIndustryEl.innerHTML = '<p class="chart-loading">Loading…</p>';
  byYearEl.innerHTML = '<p class="chart-loading">Loading…</p>';
  byMonthEl.innerHTML = '<p class="chart-loading">Loading…</p>';

  const colorState = getComputedStyle(document.documentElement).getPropertyValue("--series-state").trim();
  const colorIndustry = getComputedStyle(document.documentElement).getPropertyValue("--series-industry").trim();
  const colorYear = getComputedStyle(document.documentElement).getPropertyValue("--series-year").trim();

  try {
    const [summary, byState, byIndustry, byYear, byMonth] = await Promise.all([
      fetch(`${API_BASE_A}/analytics/summary`).then((r) => r.json()),
      fetch(`${API_BASE_A}/analytics/by-state`).then((r) => r.json()),
      fetch(`${API_BASE_A}/analytics/by-industry`).then((r) => r.json()),
      fetch(`${API_BASE_A}/analytics/by-year`).then((r) => r.json()),
      fetch(`${API_BASE_A}/analytics/by-month`).then((r) => r.json()),
    ]);

    const latestYoy = byYear.length ? byYear[byYear.length - 1].yoy_change_pct : null;
    renderStatTiles(statTiles, summary, byMonth.mom_change_pct, latestYoy);

    renderBarChart(byStateEl, byState, colorState);
    renderBarChart(byIndustryEl, byIndustry, colorIndustry);

    renderLineChart(
      byYearEl,
      byYear.map((d) => ({ label: d.year, value: d.value, delta: fmtSigned(d.yoy_change_pct) })),
      colorYear,
      { showDelta: true }
    );

    const monthPoints = [
      ...byMonth.history.map((d) => ({ label: d.period, value: d.value })),
      ...byMonth.forecast.map((d) => ({ label: d.period, value: d.value, projected: true })),
    ];
    renderLineChart(byMonthEl, monthPoints, colorYear, { xLabel: (d) => fmtMonthLabel(d.label) });
  } catch (e) {
    statTiles.innerHTML = '<p class="chart-loading">Failed to load analytics.</p>';
    analyticsLoaded = false;
  }
}

window.loadAnalytics = loadAnalytics;
