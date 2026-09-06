/** Small canvas charts with real axes. Draws at 2× for crisp text; CSS scales the canvas. */
const INK = '#172c38'; const MUTED = '#7b8a8e'; const LINE = '#cdd9d5'; const TEAL = '#195d70'; const ACCENT = '#c2543a';
const fmt = (v) => (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString('en-US') : Math.abs(v) >= 10 ? Math.round(v).toString() : v.toFixed(1));
function niceTicks(min, max, count = 5) {
  const span = max - min || 1; const rough = span / count; const magnitude = 10 ** Math.floor(Math.log10(rough)); const residual = rough / magnitude;
  const step = (residual >= 5 ? 5 : residual >= 2 ? 2 : 1) * magnitude; const ticks = []; for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) ticks.push(v); return ticks;
}
function prepare(canvas, width, height) { canvas.width = width * 2; canvas.height = height * 2; canvas.style.aspectRatio = `${width} / ${height}`; const context = canvas.getContext('2d'); context.scale(2, 2); context.clearRect(0, 0, width, height); context.fillStyle = '#fbfcf8'; context.fillRect(0, 0, width, height); context.font = '11px ui-sans-serif, system-ui, sans-serif'; return context; }

/** Histogram of `values` with optional vertical markers [{value, label, color}]. */
export function drawHistogram(canvas, values, { markers = [], xLabel = '', width = 520, height = 220, bins = 32, color = TEAL } = {}) {
  const data = values.filter(Number.isFinite); if (data.length < 2) return false;
  const context = prepare(canvas, width, height); const pad = { left: 44, right: 14, top: 14, bottom: 34 }; const plotW = width - pad.left - pad.right; const plotH = height - pad.top - pad.bottom;
  const min = Math.min(...data); const max = Math.max(...data); const xTicks = niceTicks(min, max, 6); const lo = Math.min(min, xTicks[0]); const hi = Math.max(max, xTicks.at(-1)); const binW = (hi - lo) / bins || 1;
  const counts = Array(bins).fill(0); data.forEach((v) => { counts[Math.min(bins - 1, Math.floor((v - lo) / binW))] += 1; }); const peak = Math.max(...counts);
  const x = (v) => pad.left + (v - lo) / (hi - lo || 1) * plotW; const y = (c) => pad.top + plotH - c / peak * plotH;
  context.strokeStyle = LINE; context.lineWidth = 1; niceTicks(0, peak, 4).forEach((t) => { context.beginPath(); context.moveTo(pad.left, y(t)); context.lineTo(width - pad.right, y(t)); context.stroke(); context.fillStyle = MUTED; context.textAlign = 'right'; context.fillText(fmt(t / data.length * 100) + '%', pad.left - 6, y(t) + 4); });
  context.fillStyle = color; counts.forEach((c, i) => { const left = x(lo + i * binW); context.fillRect(left + .5, y(c), Math.max(1, x(lo + (i + 1) * binW) - left - 1), pad.top + plotH - y(c)); });
  context.strokeStyle = INK; context.beginPath(); context.moveTo(pad.left, pad.top + plotH + .5); context.lineTo(width - pad.right, pad.top + plotH + .5); context.stroke();
  context.fillStyle = MUTED; context.textAlign = 'center'; xTicks.forEach((t) => { context.fillText(fmt(t), x(t), pad.top + plotH + 14); });
  if (xLabel) { context.fillStyle = INK; context.fillText(xLabel, pad.left + plotW / 2, height - 6); }
  markers.forEach(({ value, label, color: markerColor = ACCENT }) => { if (!Number.isFinite(value)) return; const mx = x(value); context.strokeStyle = markerColor; context.lineWidth = 1.5; context.setLineDash([4, 3]); context.beginPath(); context.moveTo(mx, pad.top); context.lineTo(mx, pad.top + plotH); context.stroke(); context.setLineDash([]); if (label) { context.fillStyle = markerColor; context.textAlign = mx > width / 2 ? 'right' : 'left'; context.fillText(label, mx + (mx > width / 2 ? -5 : 5), pad.top + 10); } });
  return true;
}

/** Scatter of paired values with a fitted line and axis labels. */
export function drawScatter(canvas, xs, ys, { xLabel = '', yLabel = '', width = 520, height = 220, color = TEAL } = {}) {
  const points = xs.map((x, i) => [x, ys[i]]).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y)); if (points.length < 2) return false;
  const context = prepare(canvas, width, height); const pad = { left: 52, right: 14, top: 12, bottom: 36 }; const plotW = width - pad.left - pad.right; const plotH = height - pad.top - pad.bottom;
  const xMin = Math.min(...points.map((p) => p[0])); const xMax = Math.max(...points.map((p) => p[0])); const yMin = Math.min(...points.map((p) => p[1])); const yMax = Math.max(...points.map((p) => p[1]));
  const xTicks = niceTicks(xMin, xMax, 5); const yTicks = niceTicks(yMin, yMax, 5); const xl = Math.min(xMin, xTicks[0]); const xh = Math.max(xMax, xTicks.at(-1)); const yl = Math.min(yMin, yTicks[0]); const yh = Math.max(yMax, yTicks.at(-1));
  const x = (v) => pad.left + (v - xl) / (xh - xl || 1) * plotW; const y = (v) => pad.top + plotH - (v - yl) / (yh - yl || 1) * plotH;
  context.strokeStyle = LINE; context.lineWidth = 1; context.fillStyle = MUTED; context.textAlign = 'right'; yTicks.forEach((t) => { context.beginPath(); context.moveTo(pad.left, y(t)); context.lineTo(width - pad.right, y(t)); context.stroke(); context.fillText(fmt(t), pad.left - 6, y(t) + 4); });
  context.textAlign = 'center'; xTicks.forEach((t) => { context.fillText(fmt(t), x(t), pad.top + plotH + 14); });
  context.fillStyle = color; context.globalAlpha = .45; points.forEach(([px, py]) => { context.beginPath(); context.arc(x(px), y(py), 2.2, 0, Math.PI * 2); context.fill(); }); context.globalAlpha = 1;
  const n = points.length; const mx = points.reduce((s, p) => s + p[0], 0) / n; const my = points.reduce((s, p) => s + p[1], 0) / n; const sxy = points.reduce((s, p) => s + (p[0] - mx) * (p[1] - my), 0); const sxx = points.reduce((s, p) => s + (p[0] - mx) ** 2, 0); const syy = points.reduce((s, p) => s + (p[1] - my) ** 2, 0);
  const slope = sxx ? sxy / sxx : 0; const r = sxx && syy ? sxy / Math.sqrt(sxx * syy) : 0;
  context.strokeStyle = ACCENT; context.lineWidth = 1.5; context.beginPath(); context.moveTo(x(xl), y(my + slope * (xl - mx))); context.lineTo(x(xh), y(my + slope * (xh - mx))); context.stroke();
  context.strokeStyle = INK; context.beginPath(); context.moveTo(pad.left, pad.top + plotH + .5); context.lineTo(width - pad.right, pad.top + plotH + .5); context.moveTo(pad.left + .5, pad.top); context.lineTo(pad.left + .5, pad.top + plotH); context.stroke();
  context.fillStyle = INK; context.textAlign = 'center'; if (xLabel) context.fillText(xLabel, pad.left + plotW / 2, height - 6);
  if (yLabel) { context.save(); context.translate(12, pad.top + plotH / 2); context.rotate(-Math.PI / 2); context.fillText(yLabel, 0, 0); context.restore(); }
  return { r, slope };
}
