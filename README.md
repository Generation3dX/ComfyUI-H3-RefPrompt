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
| `@anna(s)` | `<Subject 1> (S1)`. Speaker numbers follow the order in which people first speak. |
| `(s:narrator)` | `(S2)`: a voice that isn't a subject |
| `{{Hello there.}}` | `<d>[English] Hello there.</d>` |
| `{{French\| Bonjour.}}` | `<d>[French] Bonjour.</d>` |
| `>>` at the start of a line | `[Shot 1]` |
| `>> 3.5` at the start of a line | `[Shot 2] At 00:03.500, ` |
| `@clip_audio` | the soundtrack of the video reference named `clip` |
| `// note` at the start of a line | removed |

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
>> A medium shot establishes @cafe. @anna(s) sits on the sofa and says,
   {{Hey! Watch your dog!}}
>> 3.0 the shot cuts to a close-up of @anna(s). She replies, {{Well, he has good taste.}}
```

The `report` output lists every problem and the `@name` → label mapping. Wire it into a Preview Any node. With `strict` on (an advanced input, on by default), any error stops the run before sampling.

## What it catches

These errors stop the run:
- unknown `@names`;
- unnamed or duplicate references;
- subjects without a description, or never shown in a shot;
- a voice whose speaker never speaks;
- missing or unordered cut times, or cut times past the video's length;
- unclosed `{{`;
- dialogue outside the shots;
- an empty summary;
- `audio_vae` missing when audio is connected.

The finished prompt is then checked against the official format as a safety net: headers, tags, markers, timestamps, `<d>` balance and speaker IDs.

## Tests

`python tests/test_grammar.py`. No ComfyUI needed.
