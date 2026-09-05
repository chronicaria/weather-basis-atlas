/** Strict decoder for the canonical V2 public ResultEnvelope boundary. */
const statuses = new Set(['available', 'unavailable', 'partial']);
export function assertResultEnvelope(value, { releaseId } = {}) {
  if (!value || typeof value !== 'object') throw new TypeError('Public object must be a JSON object.');
  const required = ['schema_version', 'release_id', 'object_id', 'result_type', 'analysis_id', 'source_artifact_ids', 'data_vintage_id', 'model_spec_ids', 'valuation_asof', 'index_definition_id', 'units', 'status', 'evidence_reference'];
  required.forEach((key) => { if (!(key in value)) throw new TypeError(`Public object is missing ${key}.`); });
  if (value.schema_version !== '2.0') throw new TypeError(`Unsupported public schema ${value.schema_version}.`);
  if (releaseId && value.release_id !== releaseId) throw new TypeError('Payload release does not match the committed scenario release.');
  if (!statuses.has(value.status)) throw new TypeError('Public object has an invalid availability status.');
  if (value.status === 'available' && (value.payload === null || value.reason_code !== null)) throw new TypeError('Available object has an invalid payload or reason.');
  if (value.status !== 'available' && !value.reason_code) throw new TypeError('Unavailable object is missing a reason code.');
  return value;
}

export function assertBootstrap(value, { releaseId } = {}) {
  if (!value || value.schema_version !== '2.0' || !value.release_id || !value.objects) throw new TypeError('Invalid V2 release bootstrap.');
  if (releaseId && value.release_id !== releaseId) throw new TypeError('Bootstrap release does not match the scenario link.');
  const objects = Array.isArray(value.objects) ? value.objects : Object.values(value.objects);
  objects.forEach((object) => {
    if (object?.schema_version) assertResultEnvelope(object, { releaseId: value.release_id });
    else if (!object?.path || typeof object.path !== 'string') throw new TypeError('Public object reference is missing its relative path.');
  });
  return value;
}

export function bootstrapObjects(bootstrap) {
  return Array.isArray(bootstrap.objects)
    ? bootstrap.objects
    : Object.entries(bootstrap.objects).map(([objectKey, value]) => ({ ...value, object_key: objectKey }));
}
