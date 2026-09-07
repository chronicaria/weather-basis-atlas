/** Explicit draft text and committed county identity; no implicit top-result selection. */
/** Reduce a search to comparable words: lowercase, no punctuation, and without the
 *  "county" / "parish" / "borough" suffix, so "Cook, IL" finds "Cook County, IL". */
const KIND = /\b(county|parish|borough|census area|city and borough|municipality|municipio)\b/g;
const terms = (value) => String(value || '').toLowerCase().replace(/[.,'’-]/g, ' ').replace(KIND, ' ').split(/\s+/).filter(Boolean);

export function findCountyMatches(counties, draft) {
  const query = String(draft || '').trim().toLowerCase();
  if (!query) return [];
  const wanted = terms(query);
  if (!wanted.length) return [];
  return counties.filter((county) => {
    const fips = String(county.fips || '').padStart(5, '0');
    if (fips === query) return true;
    const label = `${county.name || ''}, ${county.state || ''}`.toLowerCase();
    if (label.includes(query)) return true;
    // Every word the reader typed must appear in the county's name or state.
    const have = terms(`${county.name || ''} ${county.state || ''}`);
    return wanted.every((word) => have.some((part) => part.startsWith(word)));
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
