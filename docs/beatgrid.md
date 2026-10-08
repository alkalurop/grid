# beatgrid

One playlist in, a beat grid written back into that library. GPL-3.0-or-later. ix stays Apache and is not imported.

`--xml` reads `rekordbox.xml`. `--nml` reads Traktor `collection.nml`. The playlist argument is the playlist name. When two playlists share a name, pass `Folder/Name`.

Dry-run lists the tracks and does not open audio. `--execute` quits nothing: Rekordbox must already be quit for XML, Traktor for NML. Each file is decoded and gridded by `grid-analyse`, which calls [rbl-analysis](https://github.com/chrisle/rbxport/tree/main/crates/rbl-analysis) (GPL-2.0-or-later, used here under GPL-3). High precision is the engine default. The BPM search is 70–180 unless `--min-bpm` and `--max-bpm` say otherwise. Key is not written.

XML gets one `TEMPO` marker per beat, so a mid-track tempo change stays in the file. Hot cues stay. NML gets the opening BPM and one `AutoGrid` anchor on the first downbeat. Hot cues stay. Traktor's NML does not store a marker per beat.

On `--xml --execute` the command asks before it replaces the grids rekordbox and the FLX10 load. Those live in each track's analysis file and the collection BPM, not in the xml sidecar. `no` writes nothing. `--yes` skips the question. Pass `confirm` to `main` when another program should answer. Key is left alone. Tracks with no analysis file yet are skipped.

A sibling `*.beatgrid.bak` is the xml or nml from before that execute. The database copy goes to `~/local_tools/grid/rekordbox-backups`. Open rekordbox and load the track. If a tag dialog appears: Don't ask again + No. Reopen Traktor after an NML write.

```bash
docs/examples/beatgrid.sh "Deep House" --xml
docs/examples/beatgrid.sh "Deep House" --nml --execute
cargo build --release --manifest-path beatgrid/engine/Cargo.toml
```

`grid-analyse` needs Rust 1.89 or newer. Rebuild after pulling grid changes that touch the engine. The Python command is the one you run.
