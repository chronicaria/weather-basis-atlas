import { assertBootstrap, assertResultEnvelope, bootstrapObjects } from './public.js';

/** DTO boundary: callers receive explicit errors, never substituted current-release results. */
export function createPayloadClient({ baseUrl = 'data/v2', fetchImpl = fetch } = {}) {
  const catalogCache = new Map();
  async function json(url, signal) {
    const response = await fetchImpl(url, { signal, headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`Could not load ${url} (${response.status}).`);
    return response.json();
  }
  async function verifiedObjectJson(url, ref, signal) {
    const response = await fetchImpl(url, { signal, headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`Could not load ${url} (${response.status}).`);
    const bytes = await response.arrayBuffer();
    if (!ref.sha256 || !/^[a-f0-9]{64}$/i.test(ref.sha256)) throw new Error(`Object ${ref.object_id || ref.path} is missing a valid SHA-256 digest.`);
    if (!globalThis.crypto?.subtle) throw new Error('This browser cannot verify public result bytes. Use the offline bundle.');
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    const actual = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
    if (actual !== ref.sha256.toLowerCase()) throw new Error(`Integrity check failed for ${ref.object_id || ref.path}.`);
    let text;
    if (ref.path.endsWith('.gz')) {
      if (!globalThis.DecompressionStream) throw new Error('This browser cannot decompress public result data. Use the offline bundle.');
      const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
      text = await new Response(stream).text();
    } else text = new TextDecoder().decode(bytes);
    try { return JSON.parse(text); }
    catch { throw new Error(`Object ${ref.object_id || ref.path} is not valid JSON after integrity verification.`); }
  }
  function catalogKeyFor(objectId) {
    const match = /^(county|county_scenarios|quote):(\d{5})(?::|$)/.exec(objectId);
    return match ? `${match[1]}:${match[2].slice(0, 2)}` : null;
  }
  async function catalogObject(bootstrap, objectId, signal) {
    const catalogKey = catalogKeyFor(objectId); const ref = catalogKey && bootstrap.object_catalogs?.[catalogKey];
    if (!ref) return null;
    let catalog = catalogCache.get(ref.sha256);
    if (!catalog) {
      const url = `${baseUrl}/releases/${encodeURIComponent(bootstrap.release_id)}/${ref.path.replace(/^\/+/, '')}`;
      catalog = await verifiedObjectJson(url, ref, signal);
      if (catalog.schema_version !== '2.0' || catalog.release_id !== bootstrap.release_id || !catalog.objects || typeof catalog.objects !== 'object') throw new Error(`Catalog ${catalogKey} has an invalid release identity.`);
      catalogCache.set(ref.sha256, catalog);
    }
    return catalog.objects[objectId] || null;
  }
  return {
    current: (signal) => json(`${baseUrl}/current.json`, signal),
    bootstrap: async (releaseId, signal) => {
      const bootstrap = assertBootstrap(await json(`${baseUrl}/releases/${encodeURIComponent(releaseId)}/bootstrap.json`, signal), { releaseId });
      return { ...bootstrap, objects: bootstrapObjects(bootstrap) };
    },
    object: async (bootstrap, objectId, signal) => {
      let ref = Array.isArray(bootstrap.objects) ? bootstrap.objects.find((item) => item.object_key === objectId || item.object_id === objectId) : bootstrap.objects[objectId];
      if (!ref) ref = await catalogObject(bootstrap, objectId, signal);
      if (!ref) throw new Error('This release does not publish that record.');
      if (ref.schema_version) return assertResultEnvelope(ref, { releaseId: bootstrap.release_id });
      const url = `${baseUrl}/releases/${encodeURIComponent(bootstrap.release_id)}/${ref.path.replace(/^\/+/, '')}`;
      let result = assertResultEnvelope(await verifiedObjectJson(url, ref, signal), { releaseId: bootstrap.release_id });
      if (result.object_id !== ref.object_id) throw new Error('Public object identity does not match its catalog reference.');
      result = { ...result, source_artifact_ids: result.source_artifact_ids.flatMap((id) => {
        if (!id.startsWith('source-group:')) return [id];
        const sources = bootstrap.source_artifact_groups?.[id];
        if (!Array.isArray(sources) || !sources.length || sources.some((source) => typeof source !== 'string' || source.startsWith('source-group:'))) throw new Error('Result references an unavailable source provenance group.');
        return sources;
      }) };
      if (result.result_type === 'contract_ticket' && result.payload?.contract_definition_id) {
        const definition = bootstrap.contract_definitions?.[result.payload.contract_definition_id];
        if (!definition) throw new Error('Contract references an unavailable release definition.');
        return { ...result, payload: { ...result.payload, option_contract: { ...definition, ...result.payload.option_contract } } };
      }
      if (result.result_type === 'scenario_matrix' && result.payload?.scenario_set_id) {
        const setId = result.payload.scenario_set_id;
        const matches = (bootstrap.scenario_sets || []).filter((item) => item.scenario_set_id === setId);
        if (matches.length !== 1 || result.scenario_set_id !== setId || result.payload.matrix?.parent_scenario_set_id !== setId) throw new Error('Matrix references an unavailable or mismatched shared ScenarioSet.');
        let matrix = result.payload.matrix;
        if (matrix.values_encoding) {
          if (matrix.values_encoding !== 'float32-le-base64' || typeof matrix.values_bytes !== 'string' || matrix.values !== undefined) throw new Error('Unsupported or ambiguous scenario value encoding.');
          const [rows, columns] = matrix.shape || [];
          if (!Number.isInteger(rows) || !Number.isInteger(columns) || rows < 1 || rows > 10000 || columns < 1 || columns > 252) throw new Error('Encoded scenario dimensions exceed the supported boundary.');
          const bytes = Uint8Array.from(atob(matrix.values_bytes), (letter) => letter.charCodeAt(0));
          if (bytes.byteLength !== rows * columns * 4) throw new Error('Encoded scenario byte count does not match its shape.');
          const view = new DataView(bytes.buffer);
          const values = Array.from({ length: rows }, (_, row) => Array.from({ length: columns }, (_, col) => view.getFloat32((row * columns + col) * 4, true)));
          const { values_bytes, values_encoding, ...metadata } = matrix;
          matrix = { ...metadata, values };
        }
        return { ...result, payload: { ...result.payload, matrix, scenario_set: matches[0] } };
      }
      return result;
    },
  };
}
