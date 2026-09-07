/** National county map. Canvas renderer with a hit canvas for hover/click.
 *  Consumes already-normalised {fips, value} rows and a layer descriptor; it
 *  never interprets result semantics beyond colour. */
import { stationColor } from '../pages/format.js';

const MISSING = '#d8dedc';
const RAMPS = {
  sequential: ['#eaf1ee', '#bcd6d0', '#7fb0af', '#3f8391', '#195d70', '#0f3d4a'],
  'sequential-bad': ['#f4efe9', '#e9c9b8', '#d99f83', '#c97555', '#a9502f', '#7e3a20'],
  diverging: ['#a9502f', '#d99f83', '#f3efe9', '#7fb0af', '#195d70'],
};
const hex = (color) => [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
function interpolate(stops, t) {
  const clamped = Math.max(0, Math.min(1, t)); const scaled = clamped * (stops.length - 1); const index = Math.min(stops.length - 2, Math.floor(scaled)); const local = scaled - index;
  const a = hex(stops[index]); const b = hex(stops[index + 1]);
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * local)).join(',')})`;
}
function quantile(sorted, q) { if (!sorted.length) return NaN; const position = (sorted.length - 1) * q; const low = Math.floor(position); const high = Math.ceil(position); return sorted[low] + (sorted[high] - sorted[low]) * (position - low); }

/** Domain for a quantitative layer: fixed [0,1] for ratios/fractions on a
 *  sequential ramp, otherwise a 2nd–98th percentile window so outliers do not
 *  wash the colours out. Diverging layers are symmetric around zero. */
export function layerDomain(values, layer) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return { min: 0, max: 1 };
  if (layer.kind === 'diverging') { const extent = Math.max(Math.abs(quantile(sorted, 0.02)), Math.abs(quantile(sorted, 0.98))) || 1; return { min: -extent, max: extent }; }
  if (layer.kind === 'sequential' && ['ratio', 'fraction'].includes(layer.units)) return { min: 0, max: 1 };
  const min = quantile(sorted, 0.02); const max = quantile(sorted, 0.98); return max > min ? { min, max } : { min: sorted[0], max: sorted.at(-1) || sorted[0] + 1 };
}
export function colorFor(value, layer, domain) {
  if (layer.kind === 'category') return value == null ? MISSING : stationColor(value) === '#9aa7a4' && typeof value === 'string' && !/USW/.test(value) ? categoryFallback(value) : stationColor(value);
  if (!Number.isFinite(value)) return MISSING;
  const stops = RAMPS[layer.kind] || RAMPS.sequential;
  if (layer.kind === 'diverging') return interpolate(stops, (value - domain.min) / (domain.max - domain.min || 1));
  return interpolate(stops, (value - domain.min) / (domain.max - domain.min || 1));
}
const FALLBACK = ['#247080', '#9a6a2f', '#6a7187', '#8b5365', '#4b806a', '#7561a8'];
function categoryFallback(value) { let hash = 0; for (const ch of String(value)) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0; return FALLBACK[hash % FALLBACK.length]; }
export function rampCss(layer) { const stops = RAMPS[layer.kind] || RAMPS.sequential; return `linear-gradient(to right, ${stops.join(', ')})`; }

const cache = new Map();
async function geometry(topologyUrl) {
  if (cache.has(topologyUrl)) return cache.get(topologyUrl);
  const promise = (async () => {
    if (!window.d3 || !window.topojson) throw new Error('Map libraries did not load. Use the county search and table instead.');
    const response = await fetch(topologyUrl); if (!response.ok) throw new Error('The national map geometry is unavailable. Use the county search and table instead.');
    const topology = await response.json(); const object = topology.objects.counties || Object.values(topology.objects)[0]; const path = d3.geoPath();
    // Bounding boxes make hit testing exact and cheap: filter by box, then isPointInPath.
    // A colour-coded hit canvas cannot be used here, because canvas antialiases path fills
    // and a blended edge pixel decodes to an unrelated county.
    const features = topojson.feature(topology, object).features.map((feature) => {
      const [[x0, y0], [x1, y1]] = path.bounds(feature);
      return { fips: String(feature.id).padStart(5, '0'), area: new Path2D(path(feature)), x0, y0, x1, y1 };
    });
    const states = new Path2D(path(topojson.mesh(topology, object, (a, b) => a !== b && String(a.id).slice(0, 2) !== String(b.id).slice(0, 2))));
    return { features, states };
  })();
  cache.set(topologyUrl, promise); return promise;
}

/**
 * @param canvas HTMLCanvasElement (975×610)
 * @param options {topologyUrl, rows:[{fips,value}], layer:{kind,units,format,name}, selectedFips, onSelect(fips), tooltip:HTMLElement|null, describe(fips)=>string|null}
 * @returns {domain}
 */
export async function renderAtlasMap(canvas, { topologyUrl, rows = [], layer, selectedFips, onSelect, tooltip, describe }) {
  const context = canvas.getContext('2d');
  const geo = await geometry(topologyUrl);
  const values = new Map(rows.map((row) => [String(row.fips).padStart(5, '0'), row.value]));
  // The study covers the contiguous states, so counties it does not publish are not drawn
  // at all: an Alaskan county the reader could click has nothing behind it.
  const drawn = geo.features.filter((feature) => values.has(feature.fips));
  const domain = layerDomain(rows.map((row) => row.value), layer);
  context.fillStyle = '#e3ece8'; context.fillRect(0, 0, canvas.width, canvas.height);
  drawn.forEach((feature) => { context.fillStyle = colorFor(values.get(feature.fips), layer, domain); context.fill(feature.area); });
  context.strokeStyle = 'rgba(23,44,56,.55)'; context.lineWidth = .8; context.stroke(geo.states);
  const selected = drawn.find((feature) => feature.fips === selectedFips);
  if (selected) { context.strokeStyle = '#fff'; context.lineWidth = 4; context.stroke(selected.area); context.strokeStyle = '#c2543a'; context.lineWidth = 2.2; context.stroke(selected.area); }
  const pointAt = (event) => { const box = canvas.getBoundingClientRect(); return [(event.clientX - box.left) * canvas.width / box.width, (event.clientY - box.top) * canvas.height / box.height]; };
  const fipsAt = (event) => {
    const [x, y] = pointAt(event);
    if (x < 0 || y < 0 || x > canvas.width || y > canvas.height) return null;
    const hit = drawn.find((feature) => x >= feature.x0 - .5 && x <= feature.x1 + .5 && y >= feature.y0 - .5 && y <= feature.y1 + .5 && context.isPointInPath(feature.area, x, y));
    return hit ? hit.fips : null;
  };
  canvas.onclick = (event) => { const fips = fipsAt(event); if (fips) onSelect(fips); };
  if (tooltip) {
    canvas.onmousemove = (event) => {
      const fips = fipsAt(event); const text = fips ? describe?.(fips) : null;
      if (!text) { tooltip.hidden = true; return; }
      tooltip.textContent = text; tooltip.hidden = false;
      // Keep the label inside the panel: a county on either edge would otherwise lose its name.
      const panel = canvas.parentElement.getBoundingClientRect();
      const half = tooltip.offsetWidth / 2; const centre = event.clientX - panel.left;
      tooltip.style.left = `${Math.max(half + 4, Math.min(panel.width - half - 4, centre))}px`;
      tooltip.style.top = `${event.clientY - panel.top}px`;
    };
    canvas.onmouseleave = () => { tooltip.hidden = true; };
  }
  return { domain, drawn: drawn.length };
}
