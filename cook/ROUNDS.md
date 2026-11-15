# Cook ledger: Sticky screens

Copy to `cook/ROUNDS.md` at the start of a run. Keep the header current. One entry per round, newest at the bottom. Label every number measured or eyeballed.

Started: 2026-11-15 18:53 UTC
Size: light | Time: floor none | cap 3h
Bar: layout 9 | type 9 | tone 9 | components 9 | polish 9 | interaction 9 (of 10)
Calibration offset: [none yet] (from [Parth's estimate, date])
Gate: stills approved [no] | final [not started]
Best so far: round [N], `cook/stills/r[NN]/`, commit [sha]

## Decisions

Made without asking, one line each.
- [time] [decision], because [reason]

## Feedback inbox

Parth's exact words. Close an item only when a still proves it.
- [time] "[quote]" | round [N] | [open / done, proof: path]

- 18:58 No strong web references for e-paper editorial UI; use R01 as hardware floor and the 9/10 rubric.
- 19:00 Screens are HTML rendered by Chromium and snapped to 4 grays; photos pre-dithered on the server. Tap targets come from data-tap / data-hold attributes, exported as a hotspot list the firmware can use.
- 19:00 Approving a Claude permission is hold-to-allow (1s), never a single tap, because it runs real commands.
- 19:00 Fonts: Newsreader for display and reading, Inter for small labels.
