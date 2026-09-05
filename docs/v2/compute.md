# V2 compute and artifact contract

B08 starts with one worker and a 12 GiB reservation on the 24 GiB reference
host. BLAS/OpenMP thread counts and process RSS are recorded per execution;
no full tournament runs until the representative profile is reviewed.

`weather_basis.provenance.ids` is the only V2 content-ID boundary. It uses
strict canonical JSON (sorted keys, compact UTF-8, no NaN or Infinity) and
returns `sha256:<digest>`. Scientific `analysis_id`s include the stage,
coordinates, relevant `StageDefinition.config_fields`, frozen vintage/input
IDs, producer fingerprint and `v2-seed-1`; workers, memory and cache paths do
not change them. `execution_id` records the actual run separately.

Each completed shard lives at `var/shards/<stage>/<content-id>/`. A handler
writes a fresh same-filesystem staging directory. Outputs are hashed and
validated, then `artifact-manifest.json` is written last and the directory is
atomically published. An output directory without a valid manifest is never a
cache hit. A hash/schema/identity failure moves the whole directory to
`var/quarantine/` with a reason before selective recomputation.

`create_plan` resolves all registry ancestors, producer fingerprints, declared
input hashes and missing dependencies without execution. A frozen plan carries
per-stage semantic IDs and rejects changed relevant research, request, vintage,
input byte or producer source. It executes dependencies before descendants;
their completed artifact IDs become descendant manifest inputs. The profile is
recorded as execution metadata but excluded from semantic IDs.

The fixture acceptance check interrupts after one accepted shard, resumes only
the missing coordinate, corrupts a published output byte, observes quarantine,
and recomputes only that shard. The planned representative check uses the
existing daily R2 kernel unchanged and records wall/CPU time, RSS, array
shape/dtype, input/output hashes and equivalence evidence.

## B08 measured representative result

The accepted local run is `HDD-01`, origin 2022, all 3,107 counties and 2,000
paths through the unchanged `_daily_r2_draws` kernel. It completed in 25.04
wall seconds (24.23 CPU seconds) with 4,295,540,736 bytes peak RSS (4.00 GiB)
and emitted a `3107 × 2000` `float32` matrix (24,856,000 bytes; draw hash
`e336bbb3ae1fcf884563891d6e9c319c0345c5ccb9c0fc746819be3a61c674a4`).
The local execution report is `var/runs/bench-one/report.json`; its immutable
artifact and full input/output manifest are under
`var/shards/tournament.execute/sha256-5d354940a960fda8f4249b4f545b4083649286032326a24e903ad8e75ce42003/`.

This is one coordinate, not a tournament scaling claim. The measured RSS
supports the 12 GiB one-worker reservation and does not authorize parallel
daily fit workers yet.

## B09 exact-cutoff cache and two-worker result

`FitRequest` keys cache reuse on the exact calendar cutoff, panel content ID,
ordered series/support IDs, model settings, producer fingerprint and numerical
environment. It does not use a month/pair label. HDD-04 and CDD-04 share the
same 2022-02-28 cutoff only when every other key is identical; HDD-10's
2022-08-31 fit is distinct.

The real 3,107-county April fit built in 11.46 seconds and loaded from its
immutable cache in 0.121 seconds. Its standardized-innovation hash was exactly
unchanged (`c4e5d4dd2a0fa783e8793d32742cad51f2e84297c994547afd37aaebd004f4e0`).
The cache profile peaked at 4.17 GiB RSS. The two-worker profile used one
BLAS/OpenMP/vecLib thread per worker for independent April and October 2022
fits: 17.87 wall seconds and 4.78 GiB aggregate peak RSS. April matched the
single-worker hash exactly. Reports are retained under `var/runs/b09-fit-cache/`
and `var/runs/b09-two-worker/`.

The executor now permits only one or two independent same-stage workers and
serializes dependent stages. Planning inspection is read-only: an invalid
published shard is reported as invalid during `plan`; only execution quarantines
it before recomputation. Four workers remain disallowed because this profile
does not establish the required lower per-worker memory envelope.
