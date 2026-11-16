from .h3_grammar import (TASK_TYPES, ERROR, Issue, Result, compile_prompt, lint, frames_for_duration)

CATEGORY = "MiniMax H3/prompt"

_COUNT_TIP = ("How many {0} are wired into MiniMax H3 Reference to Video. A tag pointing at an unwired "
              "slot is one of the classic silent failures. -1 = don't check.")


def _finish(res: Result, strict: bool, title: str):
    report = res.report()
    print(f"[{title}]\n{report}")
    if strict and res.errors:
        raise ValueError(f"{title}: prompt blocked before sampling.\n\n" + "\n".join(str(i) for i in res.errors)
                         + "\n\n(Set 'strict' to false to let it through anyway.)")
    return report


def _counts(n_images, n_videos, n_audios):
    return [None if n < 0 else n for n in (n_images, n_videos, n_audios)]


class H3Ref2VAPromptBuilder:
    """Readable shorthand in, official six-section Ref2VA prompt out."""

    @classmethod
    def INPUT_TYPES(cls):
        ml = lambda ph, tip: ("STRING", {"multiline": True, "default": "", "placeholder": ph, "tooltip": tip})
        tt = lambda default, tip: ("BOOLEAN", {"default": default, "tooltip": tip})
        return {"required": {
            "subjects": ml(
                "anna = the young woman in @pic1, with long dark hair and a blue cardigan\n"
                "cafe = the coffee-shop interior in @pic2, with a brick wall and an orange sofa\n"
                "@aud1 = the voice-timbre reference for @anna(s)\n"
                "// one per line. name = definition. Indent to continue a line.",
                "subject_definitions. 'name = …' becomes '<Subject N> is …'. '@pic2 = …' gives a picture/video/audio "
                "its own entry (frame anchors, source videos, audio)."),
            "summary": ml("@anna eats a cookie in @cafe, using @aud1 as her voice-timbre reference.",
                          "One paragraph. The [task type] prefix is added from the toggles below."),
            "retention": ml(
                "anna: full - her face, long dark hair and blue cardigan are retained\n"
                "cafe (all): full - brick wall and orange sofa are retained\n"
                "@aud1: ref - its timbre guides @anna's delivery without copying the signal",
                "One line per defined label: 'name: marker - what is kept'. Visual markers: full, partial, transfer, "
                "weak. Audio markers: copy, partial, ref, weak. '(appears in [Shot …])' is filled in automatically; "
                "'(all)' forces every shot; any other '(…)' is kept as written."),
            "shots": ml(
                "Realistic sitcom style with warm indoor lighting.\n"
                ">> A medium shot establishes @cafe. @anna(s) sits on the sofa and says,\n"
                "   {{Hey! Watch your dog!}}\n"
                ">> 3.0 the shot cuts to a close-up of @anna(s). She replies, {{French| Bon.}}",
                "detailed_description. Style sentence first, then one '>>' per shot ('>> 3.5' = cut at 3.5 s). "
                "@name = reference tag, @name(s) = that subject speaking, (s:narrator) = a voice with no subject, "
                "{{…}} = spoken line. Line breaks are free."),
            "soundscape": ml("Soft indoor room tone continues throughout the scene.",
                             "overall_soundscape: ambience and physical sounds, 1–4 sentences. Empty = N/A (total silence)."),
            "music": ml("leave empty for N/A",
                        "non_diegetic_music: audience-only score (instrumentation, tempo, dynamics). Empty = N/A."),
            "language": ("STRING", {"default": "English", "tooltip": "Default language tag for {{…}} dialogue."}),
            "duration": ("FLOAT", {"default": 5.0, "min": 0.2, "max": 15.0, "step": 0.1,
                                   "tooltip": "Target length in seconds. Cut times are checked against it and the "
                                              "'length' output is snapped to H3's 17k+5 frame grid."}),
            "reference_generation": tt(True, "References guide characters, scenes, style, motion or camera."),
            "keyframe_completion": tt(False, "A picture is an exact first / key / last frame."),
            "video_editing": tt(False, "A source video is directly modified."),
            "video_continuation": tt(False, "New content continues from a source video."),
            "audio_reuse": tt(False, "An audio signal is copied in full or in part."),
            "audio_reference": tt(False, "Only timbre, style, rhythm or content of an audio is referenced."),
            "num_images": ("INT", {"default": 1, "min": -1, "max": 9, "tooltip": _COUNT_TIP.format("ref_images")}),
            "num_videos": ("INT", {"default": 0, "min": -1, "max": 3, "tooltip": _COUNT_TIP.format("ref_videos")}),
            "num_audios": ("INT", {"default": 0, "min": -1, "max": 6,
                                   "tooltip": _COUNT_TIP.format("audio tracks") + " <Audio N> counts wired video "
                                              "soundtracks first (in video order), then standalone ref_audios."}),
            "strict": ("BOOLEAN", {"default": True, "tooltip": "Stop the run on any error instead of sampling a broken prompt."}),
        }}

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("prompt", "length", "report")
    FUNCTION = "build"
    CATEGORY = CATEGORY
    DESCRIPTION = "Builds and validates a MiniMax H3 Ref2VA six-section prompt from readable shorthand."

    def build(self, subjects, summary, retention, shots, soundscape, music, language, duration,
              reference_generation, keyframe_completion, video_editing, video_continuation,
              audio_reuse, audio_reference, num_images, num_videos, num_audios, strict):
        flags = dict(zip(TASK_TYPES, (keyframe_completion, reference_generation, video_editing,
                                      video_continuation, audio_reuse, audio_reference)))
        types = [t for t, on in flags.items() if on]
        text, issues = compile_prompt(subjects, summary, retention, shots, soundscape, music, types, language)
        res = Result(text, list(issues))
        if not types:
            res.issues.append(Issue(ERROR, "summary", "no task type selected."))
        res.issues += lint(text, duration, *_counts(num_images, num_videos, num_audios))
        report = _finish(res, strict, "H3 Ref2VA Prompt Builder")
        return (text, frames_for_duration(duration), report)


class H3Ref2VAPromptLint:
    """Validates an already-written six-section prompt (hand-typed or LLM-generated)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prompt": ("STRING", {"multiline": True, "default": "", "forceInput": True}),
            "duration": ("FLOAT", {"default": 5.0, "min": 0.2, "max": 15.0, "step": 0.1}),
            "num_images": ("INT", {"default": -1, "min": -1, "max": 9, "tooltip": _COUNT_TIP.format("ref_images")}),
            "num_videos": ("INT", {"default": -1, "min": -1, "max": 3, "tooltip": _COUNT_TIP.format("ref_videos")}),
            "num_audios": ("INT", {"default": -1, "min": -1, "max": 6, "tooltip": _COUNT_TIP.format("audio tracks")}),
            "strict": ("BOOLEAN", {"default": True}),
        }}

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("prompt", "length", "report")
    FUNCTION = "check"
    CATEGORY = CATEGORY
    DESCRIPTION = "Checks a MiniMax H3 Ref2VA prompt against the official six-section format and passes it through."

    def check(self, prompt, duration, num_images, num_videos, num_audios, strict):
        res = Result(prompt, lint(prompt, duration, *_counts(num_images, num_videos, num_audios)))
        report = _finish(res, strict, "H3 Ref2VA Prompt Lint")
        return (prompt, frames_for_duration(duration), report)


NODE_CLASS_MAPPINGS = {
    "H3Ref2VAPromptBuilder": H3Ref2VAPromptBuilder,
    "H3Ref2VAPromptLint": H3Ref2VAPromptLint,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "H3Ref2VAPromptBuilder": "H3 Ref2VA Prompt Builder",
    "H3Ref2VAPromptLint": "H3 Ref2VA Prompt Lint",
}
