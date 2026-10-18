/* Storage OS charts: Chart.js manager + zero-dependency canvas sparklines. */
(function () {
  "use strict";

  const TONES = {
    cyan: "#22d3ee", emerald: "#34d399", amber: "#fbbf24",
    rose: "#fb7185", sky: "#38bdf8", slate: "#64748b",
    info: "#38bdf8", warning: "#fbbf24",
  };

  function toHexAlpha(hex, alpha) {
    const n = parseInt(hex.slice(1), 16);
    const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    return `rgba(${r},${g},${b},${alpha})`;
  }

  // ------------------------------------------------------------- sparklines

  function drawSparks() {
    document.querySelectorAll("canvas.spark").forEach((c) => {
      const raw = c.getAttribute("data-points");
      if (!raw) return;
      let points;
      try { points = JSON.parse(raw); } catch (e) { return; }
      let series = points.map((p) => (typeof p === "object" ? p.y : p));
      if (!series.length || series.every((v) => v === 0)) {
        // Draw a flat baseline for empty series.
        series = [0, 0];
      }
      const tone = TONES[c.getAttribute("data-tone")] || TONES.cyan;
      const ctx = c.getContext("2d");
      const dpr = window.devicePixelRatio || 1;
      const w = c.clientWidth || 96, h = c.clientHeight || 28;
      c.width = w * dpr; c.height = h * dpr;
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, h);
      const min = Math.min.apply(null, series);
      const max = Math.max.apply(null, series);
      const pad = 3;
      const span = max - min || 1;
      const stepX = (w - pad * 2) / Math.max(1, series.length - 1);
      const xy = series.map((v, i) => [
        pad + i * stepX,
        h - pad - ((v - min) / span) * (h - pad * 2),
      ]);
      // line
      ctx.beginPath();
      xy.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.strokeStyle = tone;
      ctx.lineWidth = 1.4;
      ctx.lineJoin = "round";
      ctx.stroke();
      // subtle area
      ctx.lineTo(xy[xy.length - 1][0], h);
      ctx.lineTo(xy[0][0], h);
      ctx.closePath();
      const grad = ctx.createLinearGradient(0, 0, 0, h);
      grad.addColorStop(0, toHexAlpha(tone, 0.22));
      grad.addColorStop(1, toHexAlpha(tone, 0.0));
      ctx.fillStyle = grad;
      ctx.fill();
      // last dot
      const [lx, ly] = xy[xy.length - 1];
      ctx.beginPath();
      ctx.arc(lx, ly, 1.8, 0, Math.PI * 2);
      ctx.fillStyle = tone;
      ctx.fill();
    });
  }

  // ------------------------------------------------------------- chart.js

  const CHARTS = {};
  const GRID = "rgba(148,163,184,0.10)";
  const TICK = "#64748b";

  // Widget slugs (used in json_script ids and data-chart attrs) → renderer kind.
  const KIND_ALIASES = {
    trend: "line",
    value_cat: "barg",
    status_dist: "donut",
    top_tools: "barh",
  };

  function chartDefaults() {
    if (!window.Chart) return;
    Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
    Chart.defaults.font.size = 10;
    Chart.defaults.color = TICK;
    Chart.defaults.plugins.legend.display = false;
    Chart.defaults.plugins.tooltip.backgroundColor = "#0c1118";
    Chart.defaults.plugins.tooltip.borderColor = "rgba(148,163,184,0.3)";
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.titleFont = { size: 10 };
    Chart.defaults.plugins.tooltip.bodyFont = { size: 10 };
    Chart.defaults.plugins.tooltip.padding = 6;
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.animation.duration = 150;
  }

  function buildChart(kind, canvas, payload, colors) {
    let series = payload.series || {};
    let labels = payload.days || payload.labels || [];
    const borderColor = colors[0] || TONES.cyan;

    if (kind === "line") {
      return new Chart(canvas, {
        type: "line",
        data: {
          labels,
          datasets: [
            { label: "Received", data: series.receive, borderColor: TONES.emerald,
              backgroundColor: toHexAlpha(TONES.emerald, 0.12), fill: true, tension: 0.3,
              borderWidth: 1.4, pointRadius: 0, pointHoverRadius: 3 },
            { label: "Issued", data: series.issue, borderColor: TONES.sky,
              backgroundColor: toHexAlpha(TONES.sky, 0.12), fill: true, tension: 0.3,
              borderWidth: 1.4, pointRadius: 0, pointHoverRadius: 3 },
            { label: "Returned", data: series.return, borderColor: TONES.cyan,
              backgroundColor: "transparent", fill: false, tension: 0.3,
              borderWidth: 1.4, pointRadius: 0, pointHoverRadius: 3 },
          ],
        },
        options: {
          plugins: { legend: { display: true, position: "bottom", labels:
              { boxWidth: 6, boxHeight: 6, font: { size: 9 }, color: TICK } } },
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 10 } },
            y: { beginAtZero: true, grid: { color: GRID }, border: { display: false } },
          },
        },
      });
    }

    if (kind === "barg") { // horizontal value bars
      const data = payload.items || [];
      return new Chart(canvas, {
        type: "bar",
        data: {
          labels: data.map((d) => d.label),
          datasets: [{ data: data.map((d) => d.value), backgroundColor: toHexAlpha(TONES.cyan, 0.65),
                       borderRadius: 2, barThickness: 12 }],
        },
        options: {
          indexAxis: "y",
          plugins: { tooltip: { callbacks: { label: (c) =>
            " $" + Number(c.parsed.x).toLocaleString(undefined, { maximumFractionDigits: 0 }) } } },
          scales: {
            x: { grid: { color: GRID }, border: { display: false },
                 ticks: { font: { family: "'JetBrains Mono', monospace" }, callback: (v) =>
                   "$" + (v >= 1000 ? (v / 1000).toFixed(0) + "k" : v) } },
            y: { grid: { display: false }, ticks: { font: { size: 9 } } },
          },
        },
      });
    }

    if (kind === "donut") {
      const data = payload.items || [];
      return new Chart(canvas, {
        type: "doughnut",
        data: {
          labels: data.map((d) => d.label),
          datasets: [{ data: data.map((d) => d.value),
                       backgroundColor: data.map((d) => d.color),
                       borderColor: "#05070b", borderWidth: 2 }],
        },
        options: {
          cutout: "62%",
          plugins: {
            legend: { display: true, position: "bottom",
                      labels: { boxWidth: 6, boxHeight: 6, font: { size: 9 }, color: TICK } },
          },
        },
      });
    }

    if (kind === "barh") { // top tools usage bars
      const data = payload.items || [];
      return new Chart(canvas, {
        type: "bar",
        data: {
          labels: data.map((d) => d.sku),
          datasets: [{ data: data.map((d) => d.count),
                       backgroundColor: toHexAlpha(TONES.sky, 0.7), borderRadius: 2,
                       barThickness: 10 }],
        },
        options: {
          indexAxis: "y",
          plugins: { tooltip: { callbacks: {
            title: (items) => data[items[0].dataIndex].name || items[0].label,
            label: (c) => " " + c.parsed.x + " uses" } } },
          scales: {
            x: { beginAtZero: true, grid: { color: GRID }, border: { display: false },
                 ticks: { maxTicksLimit: 6 } },
            y: { grid: { display: false }, ticks: { font: { family: "'JetBrains Mono', monospace", size: 9 } } },
          },
        },
      });
    }
    return null;
  }

  function renderAll() {
    if (!window.Chart) return;
    chartDefaults();
    document.querySelectorAll("script[type='application/json'][id^='chart-data-']")
      .forEach((tag) => {
        const kind = tag.id.replace("chart-data-", "");
        const canvas = document.querySelector(`canvas[data-chart='${kind}']`);
        if (!canvas || !canvas.offsetParent) { if (CHARTS[kind]) { CHARTS[kind].destroy(); delete CHARTS[kind]; } return; }
        let payload;
        try { payload = JSON.parse(tag.textContent); } catch (e) { return; }
        if (CHARTS[kind]) CHARTS[kind].destroy();
        const colors = (payload.colors || []).map((c) => TONES[c] || c);
        chartDefaults();
        CHARTS[kind] = buildChart(KIND_ALIASES[kind] || kind, canvas, payload, colors);
        // Accessible summary for screen readers, requested in the design spec.
        canvas.setAttribute("aria-label", canvas.dataset.summary || kind + " chart");
        canvas.setAttribute("role", "img");
      });
    drawSparks();
  }

  window.Charts = {
    rerenderAll: renderAll,
    destroyAll() { Object.values(CHARTS).forEach((c) => c.destroy()); },
  };

  function boot() {
    if (window.Chart) renderAll();
    else document.addEventListener("DOMContentLoaded", renderAll);
  }
  if (document.readyState !== "loading") boot();
  else document.addEventListener("DOMContentLoaded", boot);

  // 30/90-day client-side toggle: both datasets delivered in one payload.
  window.toggleTrendRange = function (btn, days) {
    btn.parentElement.querySelectorAll("button").forEach((b) =>
      b.classList.remove("bg-cyan-500/20", "text-cyan-300"));
    btn.classList.add("bg-cyan-500/20", "text-cyan-300");
    const tag = document.getElementById(`chart-data-trend${days}`);
    const canvas = document.querySelector("canvas[data-chart='trend']");
    if (!tag || !canvas) return;
    const payload = JSON.parse(tag.textContent);
    if (window.SH_TREND) window.SH_TREND.destroy();
    window.SH_TREND = buildChart("line", canvas, payload, []);
  };
})();
