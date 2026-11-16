import logging

import nodes
from comfy_api.latest import io
from comfy_extras.nodes_minimax_h3 import FPS, MiniMaxH3ReferenceToVideo, align_frame_count

from .h3_grammar import APPEARANCE, AUDIO_MARKERS, ERROR, IMAGE_ASPECTS, VIDEO_ASPECTS, VISUAL_MARKERS, Result, compile_prompt, lint

CATEGORY = "model/conditioning/minimax"

H3Reference = io.Custom("H3_REFERENCE")


def visual_keep(default):
    return io.Combo.Input("keep", options=VISUAL_MARKERS, default=default,
                          tooltip="How closely the video follows this reference (the retention marker).")


def visual_role(key, keep, aspects, kept=(), ignored=(), first=()):
    return io.DynamicCombo.Option(key, [
        *first, visual_keep(keep),
        io.MultiCombo.Input("keep_these", options=aspects, default=list(kept), placeholder="(role default)",
                            tooltip="What the video takes from this reference. Written into its retention line."),
        io.MultiCombo.Input("ignore_these", options=aspects, default=list(ignored), placeholder="(nothing)",
                            tooltip="What the video must not take from this reference, e.g. the clothing of the person "
                                    "in a staging layout. Written into its retention line."),
    ])


def audio_keep(default):
    return io.Combo.Input("keep", options=AUDIO_MARKERS, default=default,
                          tooltip="reference: only timbre/style is followed. fully_copy / partially_copy: the audio itself is reused.")


def common_inputs(name_tip, description_tip):
    return [
        io.String.Input("name", default="", tooltip=name_tip),
        io.String.Input("description", multiline=True, default="", tooltip=description_tip),
        io.String.Input("what_is_kept", multiline=True, default="",
                        tooltip="Anything keep_these / ignore_these can't say about what the video keeps and what changes, "
                                "e.g. 'she wears a red coat instead'. Audio: what is kept from the recording."),
    ]


def reference(kind, data, name, description, what_is_kept, role, **extra):
    return io.NodeOutput({"kind": kind, "data": data, "name": name, "description": description, "what_is_kept": what_is_kept,
                          "role": role["role"], "keep": role["keep"], "shots": role.get("shots", ""),
                          "speaker": role.get("speaker", ""), "keep_these": role.get("keep_these", []),
                          "ignore_these": role.get("ignore_these", []), **extra})


class H3ImageReference(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        option = lambda key, keep, *picks, **first: visual_role(key, keep, IMAGE_ASPECTS, *picks, **first)
        return io.Schema(
            node_id="H3ImageReference",
            display_name="H3 Image Reference",
            category=CATEGORY,
            description="One reference image and its role, for H3 Ref2VA Prompt.",
            inputs=[
                io.Image.Input("image"),
                *common_inputs("Name to use as @name in the shots. Subject references with the same name merge into one subject.",
                               "Main features, as a noun phrase: 'the young woman with long dark hair and a blue cardigan'. "
                               "Optional for layouts and frames."),
                io.DynamicCombo.Input("role", options=[
                    option("character", "fully_preserved", APPEARANCE, ["background"]),
                    option("environment", "fully_preserved", ["background", "lighting"]),
                    option("prop", "fully_preserved"),
                    option("outfit", "fully_preserved", ["clothing"], ["face", "hair", "background"]),
                    option("style", "fully_preserved", ["style", "colours", "lighting"]),
                    option("staging layout", "partially_preserved", ["subject positions", "camera angle"], APPEARANCE,
                           first=[io.String.Input("shots", default="1", tooltip="Shot numbers this layout stages, e.g. '1' or '1, 2', or 'all'.")]),
                    option("first frame", "fully_preserved"),
                    option("last frame", "fully_preserved"),
                ], tooltip="character / environment / prop / outfit / style: something seen in the video. "
                           "staging layout: where subjects stand and the camera viewpoint. first / last frame: the exact frame."),
            ],
            outputs=[H3Reference.Output(display_name="reference")],
        )

    @classmethod
    def execute(cls, image, name, description, what_is_kept, role) -> io.NodeOutput:
        return reference("image", image, name, description, what_is_kept, role)


class H3VideoReference(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        option = lambda key, keep, *picks: visual_role(key, keep, VIDEO_ASPECTS, *picks)
        return io.Schema(
            node_id="H3VideoReference",
            display_name="H3 Video Reference",
            category=CATEGORY,
            description="One reference video, its optional soundtrack, and its role, for H3 Ref2VA Prompt.",
            inputs=[
                io.Image.Input("video", tooltip="Video frames at 24 fps (2-15 s)."),
                io.Audio.Input("soundtrack", optional=True, tooltip="The video's own audio. Use it in the shots as @name_audio."),
                io.Combo.Input("soundtrack_keep", options=AUDIO_MARKERS, default="reference",
                               tooltip="How the soundtrack is used, when connected."),
                *common_inputs("Name to use as @name in the shots. Subject references with the same name merge into one subject.",
                               "Main features, as a noun phrase. Required for character and motion."),
                io.DynamicCombo.Input("role", options=[
                    option("character", "fully_preserved", APPEARANCE, ["background"]),
                    option("motion", "fully_preserved", ["motion", "timing"], APPEARANCE),
                    option("camera and pacing", "partially_preserved", ["camera movement", "timing"], APPEARANCE),
                    option("edit source", "partially_preserved"),
                    option("continue from", "fully_preserved"),
                ], tooltip="character / motion: a subject seen in the video. camera and pacing: follow its camera work. "
                           "edit source: modify this video. continue from: carry on from its end."),
            ],
            outputs=[H3Reference.Output(display_name="reference")],
        )

    @classmethod
    def execute(cls, video, soundtrack_keep, name, description, what_is_kept, role, soundtrack=None) -> io.NodeOutput:
        return reference("video", video, name, description, what_is_kept, role,
                         audio=soundtrack, soundtrack=soundtrack_keep if soundtrack is not None else None)


class H3AudioReference(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3AudioReference",
            display_name="H3 Audio Reference",
            category=CATEGORY,
            description="One reference audio and its role, for H3 Ref2VA Prompt.",
            inputs=[
                io.Audio.Input("audio"),
                *common_inputs("Name to use as @name in the shots.", "Optional: what it sounds like, e.g. 'a low unhurried male voice'."),
                io.DynamicCombo.Input("role", options=[
                    io.DynamicCombo.Option("voice", [
                        io.String.Input("speaker", default="", tooltip="Name of the subject this voice belongs to, or the key used in (s:key)."),
                        audio_keep("reference")]),
                    io.DynamicCombo.Option("music", [audio_keep("reference")]),
                    io.DynamicCombo.Option("ambience", [audio_keep("reference")]),
                ], tooltip="voice: a speaker's voice. music: audience-only score. ambience: background and physical sounds."),
            ],
            outputs=[H3Reference.Output(display_name="reference")],
        )

    @classmethod
    def execute(cls, audio, name, description, what_is_kept, role) -> io.NodeOutput:
        return reference("audio", audio, name, description, what_is_kept, role)


class H3Ref2VAPrompt(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3Ref2VAPrompt",
            display_name="H3 Ref2VA Prompt",
            category=CATEGORY,
            description="Writes the six-section MiniMax H3 Ref2VA prompt from the references and the shot text, checks it, "
                        "and encodes it with the references. Replaces MiniMax H3 Reference to Video.",
            inputs=[
                io.Clip.Input("clip"),
                io.Vae.Input("vae"),
                io.Vae.Input("audio_vae", optional=True, tooltip="Audio VAE, needed when an audio reference or soundtrack is connected."),
                io.Autogrow.Input("references", template=io.Autogrow.TemplatePrefix(
                    H3Reference.Input("reference", tooltip="An H3 Image, Video or Audio Reference."), prefix="reference", min=1, max=20)),
                io.String.Input("summary", multiline=True, default="",
                                tooltip="One paragraph on what happens, using @names. The [task type] prefix is added for you."),
                io.String.Input("shots", multiline=True, default="",
                                placeholder="Realistic sitcom style with warm indoor lighting.\n"
                                            ">> A medium shot establishes @cafe. @anna sits on the sofa and says,\n"
                                            "   {{Hey! Watch your dog!}}\n"
                                            ">> 3.0 the shot cuts to a close-up of @anna, who replies, {{Well, he has good taste.}}",
                                tooltip="Style sentence first, then one '>>' per shot ('>> 3.5' = cut at 3.5 s). @name = a reference. "
                                        "{{...}} = a spoken line, said by the one @name before it in the sentence. @name(s) picks the speaker "
                                        "when several are named; 'a child (s:child) says' = a voice with no reference."),
                io.String.Input("soundscape", multiline=True, default="", tooltip="Ambience and physical sounds. Empty = N/A (silence)."),
                io.String.Input("music", multiline=True, default="", tooltip="Audience-only score. Empty = N/A."),
                io.String.Input("language", default="English", tooltip="Default language tag for {{...}} dialogue."),
                io.Int.Input("width", default=1344, min=32, max=nodes.MAX_RESOLUTION, step=32),
                io.Int.Input("height", default=768, min=32, max=nodes.MAX_RESOLUTION, step=32),
                io.Int.Input("length", default=124, min=5, max=3600, step=17, tooltip="Frame count at 24 fps (124 = ~5 s, trained range ~124-362)."),
                io.Combo.Input("ref_image_size", options=["match", "max"], default="match", advanced=True,
                               tooltip="As in MiniMax H3 Reference to Video: 'max' keeps reference images at up to 2048 px for identity, but is slower."),
                io.Boolean.Input("strict", default=True, advanced=True, tooltip="Stop the run on any prompt error instead of sampling a broken prompt."),
            ],
            outputs=[io.Conditioning.Output(display_name="positive"), io.Latent.Output(), io.String.Output(display_name="prompt"),
                     io.String.Output(display_name="report")],
        )

    @classmethod
    def execute(cls, clip, vae, references, summary, shots, soundscape, music, language, width, height, length,
                ref_image_size, strict, audio_vae=None) -> io.NodeOutput:
        refs = [references[k] for k in sorted(references, key=lambda k: int(k.removeprefix("reference"))) if references[k] is not None]
        text, issues, legend = compile_prompt(refs, summary, shots, soundscape, music, language)
        images = [r for r in refs if r["kind"] == "image"]
        videos = [r for r in refs if r["kind"] == "video"]
        audios = [r for r in refs if r["kind"] == "audio"]
        n_audio = len(audios) + sum(r["audio"] is not None for r in videos)
        issues += lint(text, align_frame_count(max(5, length)) / FPS, len(images), len(videos), n_audio)
        res = Result(text, issues, legend)
        report = res.report()
        logging.info("H3 Ref2VA Prompt:\n%s\n\n%s", text, report)
        if strict and res.errors:
            raise ValueError("H3 Ref2VA Prompt: the prompt has errors, so the run was stopped before sampling.\n\n"
                             + "\n".join(str(i) for i in res.errors))
        if n_audio and audio_vae is None:
            raise ValueError("H3 Ref2VA Prompt: connect audio_vae to use audio references or soundtracks.")

        cond, latent = MiniMaxH3ReferenceToVideo.execute(
            clip, text, width, height, length, ref_image_size=ref_image_size, vae=vae, audio_vae=audio_vae,
            ref_images={f"ref_image_{i}": r["data"] for i, r in enumerate(images, 1)},
            ref_videos={f"ref_video_{i}": r["data"] for i, r in enumerate(videos, 1)},
            ref_video_audios={f"ref_video_audio_{i}": r["audio"] for i, r in enumerate(videos, 1) if r["audio"] is not None},
            ref_audios={f"ref_audio_{i}": r["data"] for i, r in enumerate(audios, 1)},
        ).args
        return io.NodeOutput(cond, latent, text, report)
