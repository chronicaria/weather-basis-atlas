export const node = (tag, text, attributes = {}) => {
  const element = document.createElement(tag);
  if (text !== undefined && text !== null) element.textContent = String(text);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
};

export function keyValueTable(entries) {
  const table = node('table', undefined, { class: 'metric-table' });
  const body = node('tbody');
  entries.forEach(([label, value]) => {
    const row = node('tr'); row.append(node('th', label, { scope: 'row' }), node('td', value ?? 'Unavailable'));
    body.append(row);
  });
  table.append(body); return table;
}

export function availabilityText(value) {
  if (!value) return 'Unavailable';
  return value.reason_code ? `${value.status || 'unavailable'}: ${value.reason_code}` : value.status || 'Available';
}

export function replacePanel(selector, children) {
  const panel = document.querySelector(selector);
  if (!panel) return null;
  panel.replaceChildren(...children); return panel;
}
