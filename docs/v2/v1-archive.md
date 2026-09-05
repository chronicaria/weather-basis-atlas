# V1 preservation record

The V1 public release at source commit `92156fc76ba210f9b1ef2a76458ca85931eb1790`
is preserved locally under `var/archive/v1/`. It is ignored from Git and uses
hard links to the frozen V1 source outputs, so it creates a recoverable local
locator without placing a second multi-gigabyte copy in the working tree.

`var/archive/v1/source-ref.json` names the source revision, repository and
archive locations. `var/archive/v1/inventory.json` records deterministic tree
hashes for the V1 site, stage manifests, atlas, tournament and quote outputs,
plus representative file hashes and the lock/data-vintage identity.

Open `var/archive/v1/site/index.html` locally to inspect the retained site.
The archive includes county payloads and the V1 results/manifests needed to
trace every displayed claim; the frozen input panels remain located by the V1
source/data manifests. It does not change V1 numbers to fit V2 semantics.

## Known V1 limitations retained with the bytes

- Policy comparisons are not V2 exact-common-support matched comparisons.
- Historical policy selection could use held-out outcome availability.
- Current/as-of station choice is not distinct from historical evaluation.
- Some station-hedged indications used the archived county-self fallback.
- 2023–2025 confirmation years are consumed exploratory/development evidence.
- The joint diagnostic shares origins/data and is descriptive, not independent
  binomial significance evidence.
- The settlement weekday helper is an approximate research calendar, not a
  retained exchange-holiday settlement implementation.

The earlier mobile and quote screenshots remain dated audit evidence under
`/Users/andrewpark/Desktop/Rome/Weather/Weather Basis Atlas V2 evidence/`.
