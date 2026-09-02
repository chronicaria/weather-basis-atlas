/** Decode deterministic gzip JSON without relying on a server content-encoding header. */
export async function gzipJson(response) {
  if (!response.ok) throw new Error(`Could not load ${response.url}`);
  if (typeof DecompressionStream === 'undefined') {
    throw new Error('This browser cannot decode county payloads.');
  }
  const stream = response.body.pipeThrough(new DecompressionStream('gzip'));
  return JSON.parse(await new Response(stream).text());
}
