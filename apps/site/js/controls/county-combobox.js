import { findCountyMatches } from '../state/selection.js';

export function mountCountyCombobox({ input, listbox, status, counties, selectedFips, onCommit }) {
  let results = [];
  let active = -1;
  const optionId = (index) => `${listbox.id}-option-${index}`;
  const announce = (text) => { status.textContent = text; };
  function render() {
    listbox.replaceChildren();
    results.forEach((county, index) => {
      const option = document.createElement('button');
      option.type = 'button'; option.id = optionId(index); option.role = 'option';
      option.className = 'county-option'; option.dataset.fips = county.fips;
      option.setAttribute('aria-selected', String(index === active));
      option.textContent = `${county.name}, ${county.state} · ${county.fips}`;
      option.addEventListener('mousedown', (event) => event.preventDefault());
      option.addEventListener('click', () => commit(index));
      listbox.append(option);
    });
    input.setAttribute('aria-expanded', String(results.length > 0));
    input.setAttribute('aria-activedescendant', active >= 0 ? optionId(active) : '');
  }
  function search() {
    results = findCountyMatches(counties, input.value);
    active = results.length === 1 ? 0 : -1;
    render();
    announce(results.length ? `${results.length} county match${results.length === 1 ? '' : 'es'}. Choose a county to change the selection.` : 'No county matches. The current county remains selected.');
  }
  function commit(index = active) {
    if (index < 0 || !results[index]) { announce('Choose a county from the search results before applying.'); return; }
    const county = results[index];
    input.value = `${county.name}, ${county.state}`;
    results = []; active = -1; render();
    announce(`${county.name}, ${county.state} selected.`);
    onCommit(county.fips);
  }
  input.setAttribute('role', 'combobox'); input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', listbox.id); input.setAttribute('aria-expanded', 'false');
  input.addEventListener('input', search);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' && results.length) { event.preventDefault(); active = Math.min(results.length - 1, active + 1); render(); }
    else if (event.key === 'ArrowUp' && results.length) { event.preventDefault(); active = Math.max(0, active - 1); render(); }
    else if (event.key === 'Enter') { event.preventDefault(); commit(); }
    else if (event.key === 'Escape') { results = []; active = -1; render(); input.value = ''; announce(`Search closed. County ${selectedFips} remains selected.`); }
  });
  return { search, commit };
}
