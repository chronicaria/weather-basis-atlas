export const HOLDINGS_COLUMNS = Object.freeze(['row_id', 'kind', 'entity_id', 'amount', 'budget', 'candidate_id', 'payoff_kind', 'strike', 'multiplier', 'unit_cost', 'units', 'currency']);

export function holdingsTemplate() {
  // Entity ids must match the aligned scenario matrices: FIPS:PAIR for counties, STATION:PAIR for stations.
  return `${HOLDINGS_COLUMNS.join(',')}\nexposure-1,heating_shortfall,31109:HDD-01,120,1188,,,,,,USD,USD\nhedge-1,hedge,USW00014935:HDD-01,1,,hedge-1,put,1200,20,20,index_point,USD\n`;
}

export function parseHoldingsCsv(text) {
  const lines = String(text).trim().split(/\r?\n/).filter(Boolean);
  if (!lines.length) return { rows: [], errors: ['The CSV is empty.'] };
  const header = lines[0].split(',').map((value) => value.trim());
  const missing = HOLDINGS_COLUMNS.filter((column) => !header.includes(column));
  if (missing.length) return { rows: [], errors: [`Missing required columns: ${missing.join(', ')}.`] };
  const rows = []; const errors = [];
  lines.slice(1).forEach((line, index) => {
    const cells = line.split(',').map((value) => value.trim()); const row = Object.fromEntries(header.map((column, cell) => [column, cells[cell] ?? '']));
    if (!row.row_id || !['heating_shortfall', 'cooling_overrun', 'asymmetric_deviation', 'hedge'].includes(row.kind) || !row.entity_id || !Number.isFinite(Number(row.amount)) || !row.units || !row.currency) errors.push(`Row ${index + 2} is incomplete or uses an unsupported holding kind.`);
    else { const parsed = { ...row }; ['amount', 'budget', 'multiplier', 'unit_cost'].forEach((key) => { if (parsed[key] !== '') parsed[key] = Number(parsed[key]); }); if (row.kind === 'hedge') parsed.payoff_spec = { kind: row.payoff_kind, strike: Number(row.strike), multiplier: Number(row.multiplier) }; rows.push(parsed); }
  });
  if (new Set(rows.map((row) => row.row_id)).size !== rows.length) errors.push('row_id values must be unique.');
  if (rows.some((row) => row.currency !== 'USD')) errors.push('Mixed or unrecognised currency is not converted in the browser.');
  return { rows, errors };
}
