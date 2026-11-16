# ComfyUI-H3-RefPrompt

Two nodes for writing MiniMax H3 **Ref2VA** prompts without hand-typing the six-section format.

- **H3 Ref2VA Prompt Builder** — readable shorthand in, official prompt out, linted.
- **H3 Ref2VA Prompt Lint** — checks a prompt you already have (hand-written or from an LLM formatter).

Both output `prompt` (wire into `MiniMax H3 Reference to Video` → `prompt`), `length` (frames, snapped to
the 17k+5 grid, wire into `length`), and `report` (wire into a Preview Any node).

With `strict` on, any error stops the run **before** sampling.

Grammar follows MiniMax's own spec: `skills/h3-prompt-writing/references/ref-en.txt` and `base-en.txt`
in github.com/MiniMax-AI/MiniMax-H3.

## Install

Copy this folder into `ComfyUI/custom_nodes/` and restart. No dependencies.

## Shorthand

| You write | It becomes |
| --- | --- |
| `anna = the woman in @pic1, …` (subjects box) | `<Subject 1> is the woman in <Picture 1>, …` |
| `@pic2 = the first frame of [Shot 1], …` | `<Picture 2> is the first frame of [Shot 1], …` |
| `@anna` | `<Subject 1>` |
| `@pic1` `@vid1` `@aud1` | `<Picture 1>` `<Video 1>` `<Audio 1>` |
| `@anna(s)` | `<Subject 1> (S1)` — speaker numbers follow the order people first speak |
| `(s:narrator)` | `(S2)` — a voice that is not a subject |
| `(s:anna,ben)` | `(S1,S2)` — speaking together |
| `{{Hello there.}}` | `<d>[English] Hello there.</d>` |
| `{{French\| Bonjour.}}` | `<d>[French] Bonjour.</d>` |
| `>>` at line start | `[Shot 1]` |
| `>> 3.5` at line start | `[Shot 2] At 00:03.500, ` |
| `anna: full - face and hair kept` (retention box) | `<Subject 1> (appears in [Shot 1], [Shot 2]): fully_preserved - face and hair kept` |
| `cafe (all): full - …` | appears in every shot (for environments you don't re-tag each shot) |
| `// note to self` at line start | removed |

Retention markers — visual: `full` `partial` `transfer` `weak`; audio: `copy` `partial` `ref` `weak`.
The official names (`fully_preserved`, …) are accepted too.

Line breaks inside a shot are free, so you can lay a shot out however reads best.
Official syntax (`<Subject 1>`, `<d>…</d>`, `<scenetrans>`, `<cutoff>`) can be typed directly anywhere.

After `>> 3.5`, start the text with a cut phrase: `the shot cuts to …`.

## Example

subjects
```
anna = the young woman in @pic1, with long dark hair and a blue cardigan
cafe = the coffee-shop interior in @pic2, with a brick wall and an orange sofa
@aud1 = the voice-timbre reference for @anna(s)
```
summary
```
@anna eats a cookie in @cafe, using @aud1 as her voice-timbre reference.
```
retention
```
anna: full - her face, long dark hair and blue cardigan are retained
cafe (all): full - brick wall and orange sofa are retained
@aud1: ref - its timbre guides @anna's delivery without copying the signal
```
shots
```
Realistic sitcom style with warm indoor lighting.
>> A medium shot establishes @cafe. @anna(s) sits on the sofa and says,
   {{Hey! Watch your dog!}}
>> 3.0 the shot cuts to a close-up of @anna(s). She replies, {{Well, he has good taste.}}
```
Toggles: `reference_generation` + `audio_reference`; `num_images` 2, `num_audios` 1.

## What the linter catches

Errors (block the run): misspelled or reordered section headers; malformed tags (`<Subject1>`,
`<subject 1>`, `[Subject 1]`); labels used but never defined; tags pointing at unwired reference slots;
invalid task types or separators; invalid or wrong-family retention markers; missing or duplicate
retention lines; speaker IDs in `retention_analysis`; shot numbering gaps; bad, missing, non-increasing or
out-of-duration timestamps; unbalanced `<d>`; missing `[Language]`; dialogue outside
`detailed_description`; speaker IDs that never speak.

Warnings (reported only): wired references never mentioned; subjects with no source asset; dialogue in
quotes instead of `<d>`; missing speaker before a line; missing cut phrase; missing end punctuation;
task types that disagree with audio markers; style sentence missing before `[Shot 1]`.

## Audio numbering

`<Audio N>` counts wired `ref_video_audio_*` inputs first (in video order), then standalone `ref_audio_*`.
Set `num_audios` to the total.

## Tests

`python tests/test_grammar.py` — no ComfyUI needed.
