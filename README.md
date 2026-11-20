# ComfyUI-H3-RefPrompt

Writes MiniMax H3 **Ref2VA** (reference to video + audio) prompts for you.

H3 expects a long, strictly formatted prompt with six sections and labels such as `<Subject 1>`, `<Picture 2>` and `(S1)`. Getting one detail wrong (a label, a speaker number, a missing tag) silently degrades the video. With this pack you:

1. connect your reference images, videos and audio, each with a **name** and a **role**;
2. write the scene in plain text, using `@name` for the references;
3. get the full prompt written, checked and encoded, ready for the sampler.

The format follows MiniMax's own spec in the [MiniMax-H3 repo](https://github.com/MiniMax-AI/MiniMax-H3): [ref-en.txt](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/ref-en.txt) (reference prompts) and [base-en.txt](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/base-en.txt) (general rules).

## Install

Copy this folder into `ComfyUI/custom_nodes/` and restart ComfyUI. No extra dependencies. Needs ComfyUI 0.42 or later (with MiniMax H3 support).

## Wiring

**H3 Ref2VA Prompt** replaces core's **MiniMax H3 Reference to Video** node. It has the same `positive` and `latent` outputs, so everything from the sampler onwards stays as it is.

```
H3 Image Reference ─┐
H3 Video Reference ─┼─► H3 Ref2VA Prompt ─► positive, latent ─► (your sampler, as before)
H3 Audio Reference ─┘                    ├─► prompt ─► Preview Any   (the finished prompt)
                                         └─► report ─► Preview Any   (errors and warnings)
```

Always wire `report` into a Preview Any node: that's where problems are explained.

A ready-made workflow is in [example_workflows/](example_workflows/H3-Ref2VA-Prompt-Builder.json), set up with the example below. It also appears under this pack in ComfyUI's template browser. It samples in two stages: a fast low-resolution pass, a latent upscale, then a short refining pass at full size. It needs three other node packs:
- [Comfyui_Minimax_h3_latent_Upscaler](https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler) for the upscale;
- [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) for the live preview while sampling;
- [rgthree-comfy](https://github.com/rgthree/rgthree-comfy) for the Power Lora Loader.

Model links are in the workflow's notes. Load your own images and voice clip into its three loaders.

## Step 1: the reference nodes

There is one node per media type. Every reference gets:

| Field | What to put in it |
|---|---|
| `name` | A short single word, such as `anna` or `cafe`. You write it as `@anna` in the text. Letters, digits and `_`, not starting with a digit. |
| `description` | A noun phrase describing what's in the reference, e.g. *the young woman with long dark hair and a blue cardigan*. A leading *A* / *An* / *The* is lower-cased for you where it follows other words. |
| `role` | What the reference is for (see below). Each role shows only the fields it needs. |
| `keep` | How closely the video follows the reference. Each role has a sensible default; usually leave it. |

### Roles

**H3 Image Reference**

| Role | Use it for |
|---|---|
| character | a person or animal who appears in the video |
| environment | a place |
| prop | an object |
| outfit | clothing to put on a character |
| style | the look of the video (colour, lighting, rendering) |
| staging layout | where subjects stand and where the camera is, for the shots you list in `shots` (e.g. `1, 2` or `all`) |
| first frame | the exact image a shot starts from |
| last frame | the exact image a shot ends on |

**H3 Video Reference** (video at 24 fps, 2–15 s)

| Role | Use it for |
|---|---|
| character | a subject seen in the video |
| motion | copy the movement, not the person |
| camera and pacing | copy the camera work and timing |
| edit source | the video you want edited |
| continue from | the video you want continued |

A video reference also has an optional `soundtrack` input for the video's own audio. Refer to it in the text as `@name_audio` (for a video named `clip`, write `@clip_audio`).

**H3 Audio Reference**

| Role | Use it for |
|---|---|
| voice | what a character sounds like. Set `speaker` to that character's name. |
| music | background score that only the audience hears |
| ambience | background and physical sounds |

**Two images of the same thing:** give character, environment, prop, outfit, style and motion references the same name and they merge into one subject (*`<Subject 2>` … as shown in `<Picture 2>` and `<Picture 3>`*). Every other role needs a unique name.

### keep, keep_these, ignore_these, what_is_kept

H3 has no prompt weights and no negative prompt. The only way to tell it what to take from a reference, and what to leave, is the reference's **retention line**. These fields write that line.

- `keep_these` (image and video): what the video takes from this reference: face, hair, clothing, background, lighting and so on.
- `ignore_these`: what it must **not** take. Example: a staging-layout image showing someone in a nightie. Ignore *clothing* on it, so your character keeps the pyjamas from her own reference.
- `what_is_kept`: anything the lists can't say, added to the end of the line: *she wears a red coat instead*.

Each role starts with its own picks, so you only change them when you need to. For a staging layout, the default line reads: *the subject positions and camera angle are kept; the subjects' face, hair, body and clothing are not taken from `<Picture 2>`; each subject looks as its own reference shows.*

**Voice `keep`:** leave it on `reference`. That borrows the voice and speaks only your `{{ }}` lines. `fully_copy` and `partially_copy` put the **recording itself** into the video, so the character talks for as long as the recording lasts.

## Step 2: the text

| Box | What goes in it |
|---|---|
| `summary` | One paragraph saying what happens, using `@names`. |
| `shots` | A style sentence, then the shots (syntax below). All dialogue goes here. |
| `soundscape` | What you hear besides speech and music: room tone, footsteps, rain. Empty means total silence. |
| `music` | Score that only the audience hears. Empty means none. |
| `language` | Default language for dialogue (English). |
| `width`, `height`, `length` | Video size, and length in frames at 24 fps (124 ≈ 5 s, 241 ≈ 10 s). |

### Syntax cheat sheet

| You write | Meaning | It becomes |
|---|---|---|
| `@anna` | a reference | `<Subject 1>`, or `<Picture N>` / `<Video N>` / `<Audio N>` for non-subject roles |
| `>>` | start of the first shot | `[Shot 1]` |
| `>> 4` | a new shot that **cuts in at 4 s** | `[Shot 2] At 00:04.000,` |
| `{{Hello there.}}` | a spoken line | `<d>[English] Hello there.</d>` |
| `@anna says {{Hello.}}` | Anna speaks | `<Subject 1> (S1) says <d>[English] Hello.</d>` |
| `@anna(s)` | marks who speaks when several people are named | `<Subject 1> (S1)` |
| `a child (s:child) says {{Hi!}}` | a speaker with no reference | `a child (S2) says <d>[English] Hi!</d>` |
| `{{French\| Bonjour.}}` | a line in another language | `<d>[French] Bonjour.</d>` |
| `{{I was just-}}` | a line that gets interrupted | ends with `-` |
| `// note` | a comment line | removed |

Any brackets work for speaker marks: `(s)`, `[s]`, `{s}`, `(s:child)`, `[s:child]`.

### Shots and timing

- Write the **style** first (one or two sentences, no `>>`): *Realistic sitcom style with warm indoor lighting.*
- Start every shot with `>>` at the beginning of a line. Line breaks inside a shot are fine.
- The **first** `>>` has no time. Every later one needs one.
- **Times count from the start of the video, not from the previous shot.** In a 10 s video, `>> 4` then `>> 7` means: shot 1 runs 0–4 s, shot 2 runs 4–7 s, shot 3 runs 7–10 s.
- Times can be written `4`, `4.5`, `4s` or `1:02.5`. They must go up and stay inside the video's length.
- After a time, start with a cut phrase: `>> 4 the shot cuts to a close-up of @anna …`
- A **first frame** or **last frame** is placed for you (*The shot begins from `<Picture 2>`*). Don't also `@` it in the shots. That would make the image a place or person in the scene.

### Who is speaking?

Each `{{line}}` needs a speaker, worked out from the same sentence:

- If exactly one subject is named before the line, that subject says it: `@anna smiles and says {{Hi.}}`
- If several are named, mark the speaker: `@anna(s) hands @ben the cup and says {{Careful.}}`
- For someone without a reference, give them a key: `a waiter (s:waiter) says {{Table for two?}}`. Reuse the same key for their later lines.
- A first frame, last frame or staging layout can't speak, even if it shows a person. Connect the same image again as a character with its own name, and use that name.
- Speaker numbers (S1, S2 …) follow the order in which people first speak.

**Exception:** a line sung or heard **inside a music track or soundtrack** has no speaker. Name the audio before it: *@anna nods along as @song reaches {{Stay with me.}}*

### Special tokens

Write these exactly as shown, inside the shots, when needed:

- `<cutoff>` at the end of a line that the **end of the video** cuts off: `{{And then I saw<cutoff>}}`
- `<scenetrans>` where a line is split across a cut, at the end of the first part and the start of the second:
  `>> @anna says {{Wait, I <scenetrans>}}` … `>> 2 the shot cuts to @ben. @anna continues off-screen, {{<scenetrans> never said that.}}`

## Example

References:
- Image, `anna`, character: *the young woman with long dark hair and a blue cardigan*
- Image, `cafe`, environment: *the coffee-shop interior with a brick wall and an orange sofa*
- Audio, `anna_voice`, voice, speaker `anna`, keep `reference`

summary
```
@anna sits in @cafe and warns a customer about his dog, using @anna_voice as her voice-timbre reference.
```
shots (`length` 241, about 10 s)
```
Realistic sitcom style with warm indoor lighting.
// a comment line: removed from the prompt
>> A medium shot establishes @cafe. @anna sits on the orange sofa with a cookie and says,
   {{Hey! Watch your dog!}}
>> 3.5 the shot cuts to a close-up of a man at the counter. The man (s:man) turns and replies, {{Sorry, he's just-}}
>> 7 the shot cuts to @anna, who laughs, puts the cookie down and says nothing more.
```
soundscape
```
Low café chatter, a coffee machine hisses, a dog's claws click on the tiles.
```

The `detailed_description` it writes:
```
Realistic sitcom style with warm indoor lighting.
[Shot 1] A medium shot establishes <Subject 2>. <Subject 1> (S1) sits on the orange sofa with a cookie and says, <d>[English] Hey! Watch your dog!</d>
[Shot 2] At 00:03.500, the shot cuts to a close-up of a man at the counter. The man (S2) turns and replies, <d>[English] Sorry, he's just-</d>
[Shot 3] At 00:07.000, the shot cuts to <Subject 1>, who laughs, puts the cookie down and says nothing more.
```

It also writes the `subject_definitions`, `retention_analysis`, task-type prefix and other sections from the references.

## The report

The `report` output lists every problem:
- 🔴 **error**: the prompt is broken. With `strict` on (an advanced input, on by default), the run stops before sampling.
- 🟡 **warning**: likely to give a worse video.
- 🔵 **info**: worth knowing.

It also shows each `@name` → label mapping and the speaker list. Even when the run stops, the `prompt` and `report` outputs still reach their Preview Any nodes, so you don't need the console.

Errors include:
- unknown or misspelt `@names`;
- unnamed or duplicate references;
- subjects with no description, or never shown in a shot;
- a line with no speaker, several possible speakers, or a non-character "speaking";
- a voice whose speaker never speaks;
- missing, unordered or out-of-range cut times;
- unclosed `{{`, or dialogue outside the shots;
- an empty summary;
- `audio_vae` missing when audio is connected.

The finished prompt is then checked against the official format as a safety net.

## Tips

- **Write more.** MiniMax's examples run 350–500 words in the shots. Short prompts leave the model to fill the time on its own, often with extra talking.
- **People keep talking after their line?** Check that the voice `keep` is `reference`. Give the silent part something to show: *her lips press together; she breathes slowly*. A positive description steers better than "she is silent". Fill the `soundscape` with real sounds (room tone, breathing) rather than leaving it empty or writing "silence".
- **Wrong clothes or face leaking in from another image?** Add those items to `ignore_these` on that image.
- Keep descriptions to what's visible. Put actions in the shots, not in the description.

## Tests

`python tests/test_grammar.py`. No ComfyUI needed.
