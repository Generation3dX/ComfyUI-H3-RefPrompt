"""Run:  python tests/test_grammar.py   (no ComfyUI needed)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from h3_grammar import ERROR, WARN, compile_prompt, lint


def ref(kind, role, name, description="", keep=None, retained="", shots="", speaker="", soundtrack=None):
    keep = keep or ("reference" if kind == "audio" else "fully_preserved")
    return dict(kind=kind, role=role, name=name, description=description, retained=retained, keep=keep, shots=shots,
                speaker=speaker, soundtrack=soundtrack, audio=None, data=None)


REFS = [
    ref("image", "character", "potter", "the elderly potter with a grey beard, a linen tunic and clay-stained hands"),
    ref("image", "environment", "shop", "the workshop interior with a kick wheel, shelves of unfired bowls and a small window"),
    ref("image", "environment", "shop"),
    ref("video", "character", "girl", "the young apprentice with a dark braid and a rust-red apron"),
    ref("video", "character", "cat", "the tabby cat with white paws", keep="partially_preserved"),
    ref("audio", "voice", "potter_voice", "a low unhurried male voice", speaker="potter"),
]
SUMMARY = ("@potter throws a bowl in @shop while @girl carries in water and @cat watches. "
           "The exchange uses @potter_voice as the voice-timbre reference for @potter.")
SHOTS = """
The target video uses a naturalistic documentary style with soft window light.
// comments are dropped
>> A medium shot establishes @shop. @potter(s) leans over the wheel, centring the clay, while @cat sits
   on the shelf behind him. @potter(s), in the low voice referenced from @potter_voice, says,
   {{Hey! Mind the water!}}
   as @girl steps in from the left with a jug.
>> 3 the shot cuts to a close-up of @girl(s) setting the jug down beside @potter. @girl(s) answers in a
   bright quick voice, {{I have not spilled a drop.}} She wipes her hands on her apron.
>> 5.0 the shot cuts to a close-up of @potter(s) lifting the finished bowl. @potter(s) says,
   {{Then you may fire it.}} The wheel slows to a stop.
"""
SOUND = "The wheel hums and wet clay slaps softly under a quiet room tone."


def build(refs=REFS, summary=SUMMARY, shots=SHOTS, soundscape=SOUND, music=""):
    text, issues, _ = compile_prompt(refs, summary, shots, soundscape, music, "English")
    return text, issues


def levels(issues, lvl):
    return [str(i) for i in issues if i.level == lvl]


fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"\n     {detail}"))
    fails += not cond


# 1. references compile cleanly
text, issues = build()
OFFICIAL = text
check("compile has no issues", not issues, issues)
check("subjects numbered in reference order, assets per type",
      "<Subject 2> is the workshop interior with a kick wheel, shelves of unfired bowls and a small window, as shown in <Picture 2> and <Picture 3>." in text
      and "<Subject 3> is the young apprentice with a dark braid and a rust-red apron, whose appearance comes from <Video 1>." in text, text)
check("speaker numbering follows speech order", "<Subject 1> (S1)" in text and "<Subject 3> (S2)" in text)
check("voice definition reuses the speaker ID", "<Audio 1> is the voice-timbre reference for <Subject 1> (S1), a low unhurried male voice." in text, text)
check("task types from roles", "[reference generation + audio reference] <Subject 1> throws" in text, text)
check("auto 'appears in'", "<Subject 4> (appears in [Shot 1]): partially_preserved" in text
      and "<Subject 1> (appears in [Shot 1], [Shot 2], [Shot 3])" in text, text)
check("timestamps", "[Shot 2] At 00:03.000, the shot cuts" in text and "[Shot 3] At 00:05.000," in text)

# 2. the compiled prompt lints clean
li = lint(OFFICIAL, 7.0, 3, 2, 1)
check("compiled prompt: 0 errors", not levels(li, ERROR), levels(li, ERROR))
check("compiled prompt: 0 warnings", not levels(li, WARN), levels(li, WARN))


# 3. every one of these single mistakes in a final prompt must be caught by the linter
def mut(a, b, count=1):
    assert a in OFFICIAL, a
    return OFFICIAL.replace(a, b, count)


MUTATIONS = {
    "tag missing space":            mut("<Subject 3> (S2) answers", "<Subject3> (S2) answers"),
    "tag lowercase":                mut("establishes <Subject 2>", "establishes <subject 2>"),
    "tag typo":                     mut("comes from <Picture 1>.", "comes from <Picure 1>."),
    "tag square brackets":          mut("establishes <Subject 2>", "establishes [Subject 2]"),
    "undefined subject":            mut("while <Subject 4> sits", "while <Subject 9> sits"),
    "unwired picture":              mut("<Picture 3>", "<Picture 6>"),
    "header typo":                  mut("retention_analysis:", "retention_analysys:"),
    "header with space":            mut("subject_definitions:", "subject definitions:"),
    "header capitalised":           mut("summary:", "Summary:"),
    "sections swapped":             OFFICIAL.replace("overall_soundscape:", "TMP:").replace("non_diegetic_music:", "overall_soundscape:").replace("TMP:", "non_diegetic_music:"),
    "task type typo":               mut("[reference generation + audio reference]", "[reference generation + audio referance]"),
    "task type separator":          mut("[reference generation + audio reference]", "[reference generation, audio reference]"),
    "task prefix missing":          mut("[reference generation + audio reference] ", ""),
    "marker typo":                  mut("[Shot 2]): fully_preserved", "[Shot 2]): fully_perserved"),
    "marker wrong family":          mut("<Audio 1>: reference -", "<Audio 1>: fully_preserved -"),
    "marker with hyphen":           mut("[Shot 2]): fully_preserved", "[Shot 2]): fully-preserved"),
    "retention line missing":       mut("<Audio 1>: reference - its voice timbre guides the delivery of <Subject 1> without copying the original signal.\n", "\n"),
    "retention missing dash":       mut("[Shot 2]): fully_preserved -", "[Shot 2]): fully_preserved:"),
    "speaker id in retention":      mut("delivery of <Subject 1> without", "delivery of <Subject 1> (S1) without"),
    "retention cites shot 9":       mut("(appears in [Shot 1], [Shot 2]): fully_preserved", "(appears in [Shot 1], [Shot 9]): fully_preserved"),
    "timestamp wrong format":       mut("At 00:03.000,", "At 0:03,"),
    "timestamp missing":            mut("[Shot 2] At 00:03.000, the", "[Shot 2] the"),
    "timestamps not increasing":    mut("At 00:05.000,", "At 00:02.000,"),
    "cut beyond duration":          mut("At 00:05.000,", "At 00:09.000,"),
    "shot numbering gap":           mut("[Shot 3] At", "[Shot 4] At"),
    "shot marker lowercase":        mut("[Shot 2] At", "[shot 2] At"),
    "timestamp on shot 1":          mut("[Shot 1] A medium shot", "[Shot 1] At 00:00.000, a medium shot"),
    "unclosed d":                   mut("Mind the water!</d>", "Mind the water!"),
    "d without language":           mut("<d>[English] Hey!", "<d>Hey!"),
    "d closing typo":               mut("Mind the water!</d>", "Mind the water!<d>"),
    "speaker id malformed":         mut("<Subject 3> (S2) answers", "<Subject 3> (s2) answers"),
    "speaker undefined in defs":    mut("for <Subject 1> (S1), a low", "for <Subject 1> (S4), a low"),
    "dialogue in soundscape":       mut("The wheel hums", "<d>[English] Hi.</d> The wheel hums"),
    "music section empty":          OFFICIAL[:-3].rstrip(),
}
for name, bad in MUTATIONS.items():
    errs = levels(lint(bad, 7.0, 3, 2, 1), ERROR)
    check(f"lint catches: {name}", bool(errs), "no error raised")


# 4. mistakes in the node inputs
def without(name):
    return [r for r in REFS if r["name"] != name]


CASES = {
    "unknown @name":            dict(summary=SUMMARY.replace("@potter throws", "@poter throws")),
    "reference without name":   dict(refs=REFS + [ref("image", "prop", "", "a jug")]),
    "invalid name":             dict(refs=REFS + [ref("image", "prop", "big jug", "a jug")]),
    "asset name used twice":    dict(refs=REFS + [ref("audio", "music", "potter_voice")]),
    "subject name on an asset": dict(refs=REFS + [ref("image", "staging layout", "potter", shots="1")]),
    "subject without description": dict(refs=REFS + [ref("image", "prop", "jug")], shots=SHOTS.replace("with a jug", "with @jug")),
    "character never tagged":   dict(shots=SHOTS.replace("@cat", "the cat")),
    "missing cut time":         dict(shots=SHOTS.replace(">> 5.0 ", ">> ")),
    "time on first shot":       dict(shots=SHOTS.replace(">> A medium", ">> 1.0 A medium")),
    "no shots":                 dict(shots="Documentary style."),
    "no style sentence":        dict(shots=SHOTS.replace("The target video uses a naturalistic documentary style with soft window light.", "")),
    "unclosed dialogue":        dict(shots=SHOTS.replace("{{Hey! Mind the water!}}", "{{Hey! Mind the water!")),
    "dialogue in summary":      dict(summary=SUMMARY + " {{Hey!}}"),
    "voice for a silent subject": dict(refs=without("potter_voice") + [ref("audio", "voice", "v", speaker="cat")]),
    "voice without speaker":    dict(refs=without("potter_voice") + [ref("audio", "voice", "v")]),
    "typed task prefix":        dict(summary="[reference generation] " + SUMMARY),
    "empty summary":            dict(summary=""),
    "staging shot out of range": dict(refs=REFS + [ref("image", "staging layout", "layout", shots="4")]),
    "no references":            dict(refs=[], summary="A potter works.", shots="Style.\n>> A potter works."),
}
for name, over in CASES.items():
    t, ci = build(**over)
    errs = levels(ci + lint(t, 7.0, 3, 2, 1), ERROR)
    check(f"caught (inputs): {name}", bool(errs), "no error raised")

# 5. roles
t, ci = build(refs=[ref("image", "first frame", "start", "the potter at his wheel"),
                    ref("image", "last frame", "end"),
                    ref("image", "character", "potter", "the elderly potter")] + REFS[1:3],
              summary="@potter throws a bowl in @shop.",
              shots="Documentary style.\n>> @potter throws a bowl.\n>> 3 the shot cuts to @potter lifting the bowl.", soundscape="")
check("first/last frame definitions", "<Picture 1> is the first frame of [Shot 1], showing the potter at his wheel." in t
      and "<Picture 2> is the last frame of [Shot 2]." in t, t)
check("first/last frame cited in the shots", "[Shot 1] The shot begins from <Picture 1>. <Subject 1>" in t
      and "lifting the bowl. The shot ends on <Picture 2>." in t, t)
check("keyframe completion task", "[keyframe completion + reference generation]" in t, t)
check("environment untagged: every shot", "<Subject 2> (appears in [Shot 1], [Shot 2])" in t, t)
check("frames compile and lint clean", not ci and not levels(lint(t, 5.0, 5, 0, 0), ERROR), ci + lint(t, 5.0, 5, 0, 0))

t, ci = build(refs=REFS + [ref("image", "staging layout", "layout", "two figures at a wheel", shots="1, 2")])
check("staging layout", "<Picture 4> is the staging-layout reference for [Shot 1] and [Shot 2], defining the camera viewpoint "
      "and the placement of the subjects, showing two figures at a wheel." in t
      and "<Picture 4> ([Shot 1], [Shot 2] staging layout): fully_preserved - the camera viewpoint" in t, t)

t, ci = build(refs=[ref("audio", "music", "score", keep="fully_copy"),
                    ref("video", "edit source", "src", soundtrack="fully_copy"),
                    ref("image", "character", "potter", "the elderly potter")],
              summary="@potter now wears an apron.", shots="Documentary style.\n>> @potter throws a bowl in @src.", soundscape="")
check("soundtracks are numbered before standalone audio", "<Audio 1> is the synchronized audio track of <Video 1>, reused in the target video." in t
      and "<Audio 2> is the background music, reused in the target video." in t, t)
check("video editing lead and task types", "[video editing + reference generation + audio reuse] The target video is an edited version of <Video 1>. <Subject 1> now wears" in t, t)
check("music sentence in its section", "non_diegetic_music:\n<Audio 2> is directly reused as the complete audience-only score." in t, t)
check("@name_audio for soundtracks", "<Audio 1>" in build(refs=[ref("video", "camera and pacing", "src", soundtrack="reference"),
                                                          ref("image", "character", "potter", "the elderly potter")],
                                                    summary="@potter.", shots="Style.\n>> @potter hums along to @src_audio.")[0])

t, ci = build(shots=SHOTS + "\n>> 6 the shot cuts to black as a narrator (s:narrator) says in an off-screen voiceover: {{Fin.}}",
              refs=REFS + [ref("audio", "voice", "nv", speaker="narrator")])
check("subject-less speaker gets next ID and voice", "narrator (S3) says" in t and "for the narrator (S3)." in t and not ci, ci)
t, ci = build(shots=SHOTS.replace("{{I have", "{{French| I have"))
check("per-line language override", "<d>[French] I have not" in t)
t, ci = build(refs=[dict(r, retained="her braid and apron @girl" if r["name"] == "girl" else "") for r in REFS])
check("retained override is expanded", "fully_preserved - her braid and apron <Subject 3>" in t, t)

print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
