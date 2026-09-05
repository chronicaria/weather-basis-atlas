/** Canvas renderer consumes already-normalised scalar layer values only. */
const MISSING = '#c5d1cf'; const ZERO = '#e5ece9'; const NEGATIVE = '#ba765e'; const POSITIVE = '#247080';
const CATEGORIES = ['#247080', '#9a6a2f', '#6a7187', '#8b5365', '#4b806a', '#7561a8'];
function categoryColor(value) { const text = String(value); let hash = 0; for (let index = 0; index < text.length; index += 1) hash = (hash * 31 + text.charCodeAt(index)) >>> 0; return CATEGORIES[hash % CATEGORIES.length]; }
function quantitativeColor(value, extent) { if (!Number.isFinite(value)) return MISSING; if (value === 0) return ZERO; const opacity = Math.max(0.3, Math.min(1, Math.abs(value) / (extent || 1))); const source = value < 0 ? NEGATIVE : POSITIVE; return source === NEGATIVE ? `rgba(186,118,94,${opacity})` : `rgba(36,112,128,${opacity})`; }
export async function renderAtlasMap(canvas, { topologyUrl, summary = [], selectedFips, onSelect, layerKind = 'quantitative' }) {
  const context = canvas.getContext('2d'); context.fillStyle = '#e7efec'; context.fillRect(0, 0, canvas.width, canvas.height);
  if (!window.d3 || !window.topojson) throw new Error('Map geometry libraries are unavailable. Use the county table to explore results.');
  const response = await fetch(topologyUrl); if (!response.ok) throw new Error('National map geometry is unavailable. Use the county table to explore results.');
  const topology = await response.json(); const object = topology.objects.counties || Object.values(topology.objects)[0]; const rows = new Map(summary.map((row) => [String(row.fips).padStart(5, '0'), row]));
  const numeric = summary.map((row) => row.metric_value).filter(Number.isFinite); const extent = Math.max(0, ...numeric.map((value) => Math.abs(value))); const path = d3.geoPath(); const features = topojson.feature(topology, object).features; const hit = [];
  features.forEach((feature) => { const fips = String(feature.id).padStart(5, '0'); const value = rows.get(fips)?.metric_value; context.fillStyle = layerKind === 'quantitative' ? quantitativeColor(value, extent) : value == null ? MISSING : categoryColor(value); const area = new Path2D(path(feature)); context.fill(area); if (fips === selectedFips) { context.strokeStyle = '#bf5035'; context.lineWidth = 2.5; context.stroke(area); } hit.push({ fips, area }); });
  canvas.onclick = (event) => { const box = canvas.getBoundingClientRect(); const x = (event.clientX - box.left) * canvas.width / box.width; const y = (event.clientY - box.top) * canvas.height / box.height; const item = hit.find(({ area }) => context.isPointInPath(area, x, y)); if (item) onSelect(item.fips); };
}
