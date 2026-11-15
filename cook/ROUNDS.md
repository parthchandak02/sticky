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
- 19:20 Parth: firmware updates are OTA only; asked why we ride on a fork. Answer given: own thin-client firmware recommended, later task.

## Feedback inbox

- 19:20 "all FW updates happen OTA ok?" | noted, design keeps OTA | done
- 19:20 "is the FW not our own? ... Why not have our own?" | answered in chat; own thin client recommended | open (later task)

---

## Round 01

Time: 18:53 to 19:20 | elapsed 0.5h
Focus: build the pipeline, all 10 screens, the prototype.
Stills: `screens/out/`, `cook/stills/proto/` (video), `cook/compare/r01/all.png`
Scores, eyeballed (2 critics, Claude, median, no calibration yet), out of 10:

| Shot | Layout | Type | Tone | Components | Polish |
|---|---|---|---|---|---|
| board | 7.5 | 7 | 6.5 | 6.5 | 6.5 |
| approve | 6 | 7 | 6.5 | 6 | 6 |
| today | 8 | 8 | 7 | 7 | 7 |
| countdown | 6.5 | 8 | 7 | 6 | 6 |
| photo | 7 | 7 | 7 | 6 | 6.5 |
| onthisday | 8 | 8 | 7.5 | 7 | 7 |
| note | 6 | 7 | 6.5 | 5.5 | 5.5 |
| listening | 5 | 6.5 | 5.5 | 4.5 | 5 |
| voice_result | 6 | 7.5 | 7 | 6 | 6.5 |
| art | 7 | 7 | 5 | 6 | 6 |
| reader | 7 | 6 | 8 | 7 | 5.5 |
| prototype page | 6.5 | 6 | 6.5 | 6 | 6 |

Measured: proto_test 19/19 gestures land on the right frame. shoot 390: overflow none, taps under 44px 0.
Top gaps: small gray text everywhere; hatch fills moire risk; listening screen generic; reader clips last line; note/listening lack the folio.
Progress note: files could not be delivered (no project thread); summary in chat.
Next focus: system fixes (min 15px, no hatching, folio everywhere), then listening, note, approve, countdown.
