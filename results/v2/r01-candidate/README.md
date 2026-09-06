# R01 candidate artifacts

`r01_protocol.json` here is the protocol the public research record cites. The
tables beside it are a candidate run, not the accepted comparison.

**Do not read `matched_comparisons.parquet` in this directory as the accepted
result.** Its `paired_loss_change_prior_minus_nearest` column carries the
opposite sign to its name: it holds `RSS_nearest - RSS_prior_best`. The sign was
corrected in `hedge/national.py` after these files were written, and the
acceptance check (`application/acceptance.py`) asserts the corrected direction,
so it ran against the accepted shard rather than these bytes.

The accepted table is the content-addressed shard under
`var/shards/v2/atlas.evaluate/`, whose column agrees with its name in every row
and which the release lock pins. The public per-county summaries and the
`Gain vs nearest station` map layer are projected from that shard, so the site
and the accepted table agree by construction.
