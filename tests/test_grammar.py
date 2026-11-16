"""Run:  python tests/test_grammar.py   (no ComfyUI needed)"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from h3_grammar import compile_prompt, lint, frames_for_duration, ERROR, WARN

SUBJECTS = """
potter = the elderly potter in @pic1, with a grey beard, a linen tunic and clay-stained hands.
shop = the workshop interior in @pic2 and @pic3, with a kick wheel, shelves of unfired bowls and a small window.
// motion comes from the clip, voice from the audio
girl = the young apprentice in @vid1, with a dark braid and a rust-red apron.
cat = the tabby cat in @vid2, with white paws.
@aud1 = the voice-timbre reference for @potter(s), a low unhurried male voice.
"""
SUMMARY = "@potter throws a bowl in @shop while @girl carries in water and @cat watches. The exchange uses @aud1 as the voice-timbre reference for @potter."
RETENTION = """
potter: full - his grey beard, linen tunic and clay-stained hands are retained.
shop (all): full - the kick wheel, shelves and window are retained.
girl: full - her dark braid and rust-red apron are retained.
cat: partial - the tabby coat is kept, the white paws are dusted with clay.
@aud1: ref - its timbre guides the delivery of @potter without copying the signal.
"""
SHOTS = """
The target video uses a naturalistic documentary style with soft window light.

>> A medium shot establishes @shop. @potter(s) leans over the wheel, centring the clay, while @cat sits
   on the shelf behind him. @potter(s), in the low voice referenced from @aud1, says,
   {{Hey! Mind the water!}}
   as @girl steps in from the left with a jug.

>> 3 the shot cuts to a close-up of @girl(s) setting the jug down beside @potter. @girl(s) answers in a
   bright quick voice, {{I have not spilled a drop.}} She wipes her hands on her apron.

>> 5.0 the shot cuts to a close-up of @potter(s) lifting the finished bowl. @potter(s) says,
   {{Then you may fire it.}} The wheel slows to a stop.
"""
SOUND = "The wheel hums and wet clay slaps softly under a quiet room tone."
TYPES = ["reference generation", "audio reference"]

def build(**over):
    a = dict(subjects=SUBJECTS, summary=SUMMARY, retention=RETENTION, shots=SHOTS, soundscape=SOUND, music="",
             task_types=TYPES, language="English")
    a.update(over)
    return compile_prompt(**a)

def levels(issues, lvl):
    return [str(i) for i in issues if i.level == lvl]

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"\n     {detail}"))
    fails += not cond

# 1. shorthand compiles cleanly
text, issues = build()
OFFICIAL = text
check("compile has no issues", not issues, issues)
check("speaker numbering follows speech order", "<Subject 1> (S1)" in text and "<Subject 3> (S2)" in text)
check("auto 'appears in'", "<Subject 4> (appears in [Shot 1]): partially_preserved" in text
      and "<Subject 2> (appears in [Shot 1], [Shot 2], [Shot 3])" in text, text)
check("timestamps", "[Shot 2] At 00:03.000, the shot cuts" in text and "[Shot 3] At 00:05.000," in text)

# 2. the compiled prompt lints clean
li = lint(OFFICIAL, 7.0, 3, 2, 1)
check("compiled prompt: 0 errors", not levels(li, ERROR), levels(li, ERROR))
check("compiled prompt: 0 warnings", not levels(li, WARN), levels(li, WARN))

# 3. every one of these single-character-class mistakes must be caught
def mut(a, b, count=1):
    assert a in OFFICIAL, a
    return OFFICIAL.replace(a, b, count)

MUTATIONS = {
    "tag missing space":            mut("<Subject 3> (S2) answers", "<Subject3> (S2) answers"),
    "tag lowercase":                mut("establishes <Subject 2>", "establishes <subject 2>"),
    "tag typo":                     mut("in <Picture 1>, with", "in <Picure 1>, with"),
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
    "marker typo":                  mut("[Shot 2]): fully_preserved - her dark", "[Shot 2]): fully_perserved - her dark"),
    "marker wrong family":          mut("<Audio 1>: reference -", "<Audio 1>: fully_preserved -"),
    "marker with hyphen":           mut("[Shot 2]): fully_preserved - her dark", "[Shot 2]): fully-preserved - her dark"),
    "retention line missing":       mut("<Audio 1>: reference - its timbre guides the delivery of <Subject 1> without copying the signal.\n", "\n"),
    "retention missing dash":       mut("fully_preserved - her dark", "fully_preserved: her dark"),
    "speaker id in retention":      mut("delivery of <Subject 1> without", "delivery of <Subject 1> (S1) without"),
    "retention cites shot 9":       mut("(appears in [Shot 1], [Shot 2]): fully_preserved - her dark", "(appears in [Shot 1], [Shot 9]): fully_preserved - her dark"),
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
    check(f"caught: {name}", bool(errs), "no error raised")

# 4. shorthand-level mistakes
CASES = {
    "unknown alias":          dict(summary=SUMMARY.replace("@potter throws", "@poter throws")),
    "bad marker alias":       dict(retention=RETENTION.replace("girl: full", "girl: fully")),
    "audio marker on subject":dict(retention=RETENTION.replace("girl: full", "girl: copy")),
    "subject never tagged":   dict(shots=SHOTS.replace("@cat", "the cat")),
    "missing cut time":       dict(shots=SHOTS.replace(">> 5.0 ", ">> ")),
    "duplicate subject":      dict(subjects=SUBJECTS + "\ncat = another cat in @pic2"),
    "missing = ":             dict(subjects=SUBJECTS.replace("cat = ", "cat ")),
    "unclosed dialogue":      dict(shots=SHOTS.replace("{{Hey! Mind the water!}}", "{{Hey! Mind the water!")),
    "dialogue in summary":    dict(summary=SUMMARY + " {{Hey!}}"),
    "silent speaker in defs": dict(subjects=SUBJECTS.replace("@potter(s)", "@cat(s)")),
    "typed task prefix":      dict(summary="[reference generation] " + SUMMARY),
}
for name, over in CASES.items():
    t, ci = build(**over)
    errs = levels(ci + lint(t, 7.0, 3, 2, 1), ERROR)
    check(f"caught (shorthand): {name}", bool(errs), "no error raised")

# 5. misc
t, ci = build(shots=SHOTS.replace("{{I have", "{{French| I have"))
check("per-line language override", "<d>[French] I have not" in t)
t, ci = build(shots=SHOTS + "\n>> 6 the shot cuts to black as a narrator (s:narrator) says in an off-screen voiceover: {{Fin.}} while lips remain closed.")
check("subject-less speaker gets next ID", "narrator (S3) says" in t and not ci, ci)
check("frame snapping", [frames_for_duration(x) for x in (5, 4, 8, 10, 15)] == [124, 107, 192, 243, 362],
      [frames_for_duration(x) for x in (5, 4, 8, 10, 15)])
print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
