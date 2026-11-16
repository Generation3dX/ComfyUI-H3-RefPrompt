# ComfyUI-H3-RefPrompt

Writes MiniMax H3 **Ref2VA** prompts for you. You connect reference images, videos and audio, give each a name and a role, and write the shots in plain text. The node writes the six-section prompt, checks it, and encodes it with the references.

**H3 Ref2VA Prompt** replaces core's **MiniMax H3 Reference to Video**. It has the same `positive` and `latent` outputs, so the sampler side of your workflow doesn't change. Because the same node numbers the references and writes the prompt, `<Picture 2>` in the prompt is always the second image connected.

The grammar follows MiniMax's own spec: `skills/h3-prompt-writing/references/ref-en.txt` and `base-en.txt` in github.com/MiniMax-AI/MiniMax-H3.

## Install

Copy this folder into `ComfyUI/custom_nodes/` and restart ComfyUI. There are no extra dependencies. Requires ComfyUI 0.42 or later, with MiniMax H3 support.

## Nodes

| Node | Roles |
|---|---|
| **H3 Image Reference** | character, environment, prop, outfit, style, staging layout, first frame, last frame |
| **H3 Video Reference** | character, motion, camera and pacing, edit source, continue from. It has an optional `soundtrack` input. |
| **H3 Audio Reference** | voice (with `speaker`), music, ambience |
| **H3 Ref2VA Prompt** | takes the references, the text, and core's other inputs (clip, vae, audio_vae, width, height, length) |

Each reference node has these fields:
- `name`: what you write as `@name` in the text.
- `description`: a noun phrase, such as *the young woman with long dark hair and a blue cardigan*.
- `keep`: the retention marker. It defaults to a sensible value for each role.
- `keep_these` / `ignore_these` (image and video): what the video takes from this reference, and what it must not take. Each role starts with its own picks. For example, a staging layout keeps *subject positions, camera angle* and ignores *face, hair, body, clothing*, so a person in the layout image doesn't lend their clothes to your character. The picks become the retention line: *the subject positions and camera angle are kept; the subjects' clothing is not taken from `<Picture 2>`; each subject looks as its own reference shows.*
- `what_is_kept`: anything the picks can't say, added to the end of the retention line, e.g. *she wears a red coat instead*. With no picks and no text, the line falls back to the role's standard wording, and the report warns if the marker is `partially_preserved`, `attribute_transfer` or `weak_reference`.

H3 has no weights or negative prompt for references. The retention line is how the model is told what to take and what to leave.

Descriptions starting with *A*, *An* or *The* are lower-cased where they follow *is* or *showing*.

References with a subject role that share a name merge into one subject. For example, two images of the same dog become `<Subject 2> … as shown in <Picture 2> and <Picture 3>`.

From the roles, the node writes:
- the definition and retention lines;
- the `[task type]` prefix;
- the "edited version of `<Video N>`" lead for edit sources;
- "the shot begins from `<Picture N>`" for first frames;
- the music and ambience sentences.

## Text

| You write | It becomes |
| --- | --- |
| `@anna` | `<Subject 1>`, or `<Picture N>` / `<Video N>` / `<Audio N>` for non-subject roles |
| `@anna says {{Hello there.}}` | `<Subject 1> (S1) says <d>[English] Hello there.</d>`. The one subject named before a line in the same sentence speaks it. Speaker numbers follow the order in which people first speak. |
| `@anna(s)` | `<Subject 1> (S1)`. Marks the speaker when several subjects are named before the line. |
| `a child (s:child) says {{Hi!}}` | `a child (S2) says <d>[English] Hi!</d>`: a voice that isn't a reference |
| `{{French\| Bonjour.}}` | `<d>[French] Bonjour.</d>` |
| `>>` at the start of a line | `[Shot 1]` |
| `>> 3.5` at the start of a line | `[Shot 2] At 00:03.500, ` |
| `@clip_audio` | the soundtrack of the video reference named `clip` |
| `// note` at the start of a line | removed |

A line after a music reference or a soundtrack, with no speaker named, is a cue inside that audio and gets no speaker: *@joni nods along as @song reaches {{Stay with me.}}*

In `shots`, put the style sentence first, then one `>>` per shot. Line breaks inside a shot are allowed. After `>> 3.5`, start with a cut phrase, such as *the shot cuts to …*.

## Example

References:
- Image, `anna`, character: *the young woman with long dark hair and a blue cardigan*
- Image, `cafe`, environment: *the coffee-shop interior with a brick wall and an orange sofa*
- Audio, `anna_voice`, voice, speaker `anna`

summary
```
@anna eats a cookie in @cafe, using @anna_voice as her voice-timbre reference.
```
shots
```
Realistic sitcom style with warm indoor lighting.
>> A medium shot establishes @cafe. @anna sits on the sofa and says,
   {{Hey! Watch your dog!}}
>> 3.0 the shot cuts to a close-up of @anna, who replies, {{Well, he has good taste.}}
```

The `report` output lists every problem, marked 🔴 error, 🟡 warning or 🔵 info, and the `@name` → label mapping. Wire it into a Preview Any node. With `strict` on (an advanced input, on by default), any error stops the run before sampling.

## What it catches

These errors stop the run:
- unknown `@names`;
- unnamed or duplicate references;
- subjects without a description, or never shown in a shot;
- a spoken line with no speaker, or with several subjects before it and none marked with `(s)`;
- a voice whose speaker never speaks;
- missing or unordered cut times, or cut times past the video's length;
- unclosed `{{`;
- dialogue outside the shots;
- an empty summary;
- `audio_vae` missing when audio is connected.

The finished prompt is then checked against the official format as a safety net: headers, tags, markers, timestamps, `<d>` balance and speaker IDs.

## Tests

`python tests/test_grammar.py`. No ComfyUI needed.
