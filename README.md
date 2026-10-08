# grid

DJ tools that stay out of [ix](https://github.com/ixamal/ix). Beatgrids, tempo, and playlist runs.

**GPL-3.0-or-later.** ix, CRATER, and STEMIT stay Apache 2.0. This repo does not import them. They do not import this repo. [stage](https://github.com/ixamal/stage) is the Blender repo, and the two do not depend on each other.

Each tool here builds and runs on its own. Point a script at a playlist named in this repo.

The analysis engine to call is [`rbl-analysis`](https://github.com/chrisle/rbxport/tree/main/crates/rbl-analysis) (GPL-2.0-or-later, used here under GPL-3). It reads audio and returns a grid. It does not write a rekordbox database.
