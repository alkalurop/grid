# grid

Beatgrid a whole playlist once, write markers back to rekordbox and Traktor sidecars — so Performance mode and the FLX10 are not a click-fest. Lives in its own repo because the analyzer is **GPL**; [ix](https://github.com/ixamal/ix) stays **Apache**.

## Why a separate repo

[ix](https://github.com/ixamal/ix) is **Apache-2.0** (CRATER, STEMIT, crate). This repo is **GPL-3.0-or-later**. The beatgrid engine shells out to [`rbl-analysis`](https://github.com/chrisle/rbxport/tree/main/crates/rbl-analysis) from [rbxport](https://github.com/chrisle/rbxport) (GPL-2.0-or-later, used here under GPL-3). That lineage does not belong inside an Apache tree, and ix does not import grid. You run grid on its own when you want a playlist batch grid outside rekordbox’s in-app analyze or ear-checking in the booth. [stage](https://github.com/ixamal/stage) holds Blender tools under the same license split; grid and stage do not depend on each other.

## beatgrid

One playlist in from **rekordbox.xml** or **Traktor NML**. Dry-run by default. **`--execute`** decodes each file, grids it, and writes back: xml/nml sidecar markers, and for rekordbox (after you confirm) the **ANLZ** beat grid and collection BPM that Performance mode and the FLX10 load. Keys stay as Mixed In Key / rekordbox left them. Python is the command you run; **`grid-analyse`** is the Rust helper (analyze + optional rekordbox commit).

How and why: [docs/beatgrid.md](docs/beatgrid.md). Example entrypoint: [docs/examples/beatgrid.sh](docs/examples/beatgrid.sh).

## Rekordbox sample bank (2026-10-11)

Not a grid job. Opening Traktor or Maschine while Rekordbox is already up restarts Core Audio, and the sample-bank drop dies even while the deck keeps playing. Quit **Maschine**, then **Traktor**, then **Rekordbox**, and open Rekordbox again. Audio device stays native **DDJ-FLX10**. Full write-up: [ixamal/ix](https://github.com/ixamal/ix) `docs/examples/traktor-master-class-notes.md`.
