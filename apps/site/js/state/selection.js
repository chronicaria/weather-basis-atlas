/** Explicit draft text and committed county identity; no implicit top-result selection. */
export function findCountyMatches(counties, draft) {
  const query = String(draft || '').trim().toLowerCase();
  if (!query) return [];
  return counties.filter((county) => {
    const fips = String(county.fips || '').padStart(5, '0');
    const label = `${county.name || ''}, ${county.state || ''}`.toLowerCase();
    return fips === query || label.includes(query) || `${county.name || ''} ${county.state || ''}`.toLowerCase().includes(query);
  }).map((county) => ({ ...county, fips: String(county.fips).padStart(5, '0') }));
}

export function createSelectionController({ initialFips, loadCounty, onChange = () => {} }) {
  let committedFips = initialFips;
  let requestId = 0;
  let controller = null;
  let visibleFips = initialFips;
  async function commit(fips) {
    if (!/^\d{5}$/.test(String(fips))) return { ok: false, reason: 'Invalid county identity.' };
    requestId += 1;
    const thisRequest = requestId;
    controller?.abort();
    controller = new AbortController();
    committedFips = String(fips);
    onChange({ phase: 'loading', committedFips, visibleFips });
    try {
      const payload = await loadCounty(committedFips, controller.signal);
      if (thisRequest !== requestId) return { ok: false, stale: true };
      visibleFips = committedFips;
      onChange({ phase: 'ready', committedFips, visibleFips, payload });
      return { ok: true, payload };
    } catch (error) {
      if (error?.name === 'AbortError' || thisRequest !== requestId) return { ok: false, stale: true };
      onChange({ phase: 'error', committedFips, visibleFips, error });
      return { ok: false, error };
    }
  }
  return { commit, get committedFips() { return committedFips; }, get visibleFips() { return visibleFips; } };
}
