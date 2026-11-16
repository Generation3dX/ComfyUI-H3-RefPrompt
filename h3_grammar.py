"""
MiniMax H3 Ref2VA prompt grammar: compiler from references + shot text, and linter.

Pure Python, no ComfyUI imports, so it can be unit-tested standalone.

Grammar source: MiniMax-AI/MiniMax-H3  skills/h3-prompt-writing/references/
ref-en.txt (full-reference mode) and base-en.txt (shots, speakers, dialogue).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

SECTIONS = [
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
]

TASK_TYPES = [
    "video editing",
    "video continuation",
    "keyframe completion",
    "reference generation",
    "audio reuse",
    "audio reference",
]

VISUAL_MARKERS = ["fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference"]
AUDIO_MARKERS = ["fully_copy", "partially_copy", "reference", "weak_reference"]

# role -> (how the subject definition cites its asset, what the retention line says is kept)
SUBJECT_ROLES = {
    ("image", "character"): ("whose appearance comes from", "the identity and appearance"),
    ("image", "environment"): ("as shown in", "the layout, materials and lighting of the environment"),
    ("image", "prop"): ("as shown in", "the object's shape, colours and materials"),
    ("image", "outfit"): ("as shown in", "the outfit's cut, colours and materials"),
    ("image", "style"): ("as shown in", "the visual style, colour palette and lighting"),
    ("video", "character"): ("whose appearance comes from", "the identity and appearance"),
    ("video", "motion"): ("whose motion comes from", "the movement and its timing"),
}
# subjects that need no tag in the shots: they apply to every shot unless tagged in some
EVERY_SHOT_ROLES = {"environment", "style"}

ASSET_ASPECTS = {
    "staging layout": "the camera viewpoint and the placement of the subjects",
    "first frame": "the composition, subjects and lighting of the frame",
    "last frame": "the composition, subjects and lighting of the frame",
    "camera and pacing": "the camera movement, cuts and pacing",
    "edit source": "the parts of the source video that are not edited",
    "continue from": "the subjects, setting and motion at the end of the source video",
}

# markers whose default retention line can't say what is kept or what changes
VAGUE_MARKERS = {"partially_preserved", "attribute_transfer", "weak_reference", "partially_copy"}

VISUAL_NOTES = {
    "fully_preserved": "{} are retained.",
    "partially_preserved": "{} are partly retained.",
    "attribute_transfer": "{} are transferred to the target subject.",
    "weak_reference": "only a broad similarity of {} is kept.",
}

AUDIO_NOTES = {
    "voice": {"reference": "its voice timbre guides the delivery of {who} without copying the original signal.",
              "fully_copy": "{a} is reused as the spoken audio of {who}.",
              "partially_copy": "part of {a} is reused as the spoken audio of {who}.",
              "weak_reference": "only a broad similarity to its voice is kept."},
    "music": {"reference": "only its music style, tempo and instrumentation are referenced.",
              "fully_copy": "{a} is reused 1:1 as the audience-only score.",
              "partially_copy": "part of {a} is reused in the audience-only score.",
              "weak_reference": "only a broad similarity of mood and genre is kept."},
    "ambience": {"reference": "only its ambience texture is referenced.",
                 "fully_copy": "{a} is reused 1:1 as the ambience layer.",
                 "partially_copy": "part of {a} is reused in the ambience layer.",
                 "weak_reference": "only a broad similarity of atmosphere is kept."},
    "soundtrack": {"reference": "only its sound character is referenced.",
                   "fully_copy": "{a} is reused 1:1 as the target video's complete audio track.",
                   "partially_copy": "part of {a} is reused in the target video's audio.",
                   "weak_reference": "only a broad similarity of sound is kept."},
}
AUDIO_USE = {"reference": "", "weak_reference": "",
             "fully_copy": ", reused in the target video", "partially_copy": ", partly reused in the target video"}
# sentences opening the audio section that matches the layer, per spec section 6
SECTION_SENTENCES = {
    "music": {"reference": "The score follows the music style of {a}.",
              "fully_copy": "{a} is directly reused as the complete audience-only score.",
              "partially_copy": "Part of {a} is reused in the audience-only score.",
              "weak_reference": "The score loosely resembles the mood of {a}."},
    "ambience": {"reference": "The ambience follows the texture of {a}.",
                 "fully_copy": "The ambience layer of {a} is copied throughout the video.",
                 "partially_copy": "Part of the ambience of {a} is reused.",
                 "weak_reference": "The ambience loosely resembles {a}."},
}

CUT_PHRASES = (
    "the camera cuts to",
    "the shot cuts to",
    "the shot transitions to",
    "the shot changes to",
    "the shot switches to",
)

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"

_LABEL_RE = re.compile(r"<(Subject|Picture|Video|Audio) ([1-9]\d*)>")
_VALID_TAG_RE = re.compile(r"^<(?:(?:Subject|Picture|Video|Audio) [1-9]\d*|/?d|scenetrans|cutoff)>$")
_ANY_TAG_RE = re.compile(r"<[^<>\n]{0,60}>")
_SPEAKER_RE = re.compile(r"\(S([1-9]\d*)((?:,S[1-9]\d*)*)\)")
_HEADER_RE = re.compile(r"(?m)^(" + "|".join(SECTIONS) + r"):")
_SHOT_RE = re.compile(r"\[Shot ([1-9]\d*)\]")
_TS_RE = re.compile(r" At (\d\d):(\d\d)\.(\d\d\d), ")
_NAME_RE = re.compile(r"[A-Za-z_]\w*")
# shot text tokens; a sentence ends at . ! or ? followed by a space, outside {{...}}
_TOKEN_RE = re.compile(r"\(s:(?P<spk>[\w ,]+)\)|@(?P<name>[A-Za-z_]\w*)(?P<s>\(s\))?|\{\{(?P<line>.*?)\}\}|(?P<end>[.!?])(?=\s|$)",
                       flags=re.I | re.S)


@dataclass
class Issue:
    level: str
    section: str
    msg: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.section}: {self.msg}"


@dataclass
class Result:
    prompt: str = ""
    issues: list = field(default_factory=list)
    legend: list = field(default_factory=list)

    @property
    def errors(self):
        return [i for i in self.issues if i.level == ERROR]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == WARN]

    def report(self) -> str:
        e, w = len(self.errors), len(self.warnings)
        head = "H3 Ref2VA lint: " + ("OK" if not e and not w else f"{e} error(s), {w} warning(s)")
        order = {ERROR: 0, WARN: 1, INFO: 2}
        lines = [str(i) for i in sorted(self.issues, key=lambda i: order[i.level])]
        return "\n".join([head] + lines + ([""] + self.legend if self.legend else []))


def _suggest(word: str, options) -> str:
    m = difflib.get_close_matches(word, list(options), n=1, cutoff=0.5)
    return f" Did you mean '{m[0]}'?" if m else ""


def _fmt_ts(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 60000:02d}:{(ms % 60000) // 1000:02d}.{ms % 1000:03d}"


def _parse_time(tok: str):
    m = re.fullmatch(r"(?:(\d+):)?(\d+(?:\.\d+)?)s?", tok)
    if not m:
        return None
    return int(m.group(1) or 0) * 60 + float(m.group(2))


def _strip_comments(text: str) -> str:
    return "\n".join(l for l in (text or "").replace("\r\n", "\n").split("\n") if not l.lstrip().startswith("//"))


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _join(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _shot_list(nums):
    return ", ".join(f"[Shot {n}]" for n in nums)


# --------------------------------------------------------------------------
# Compiler: references + shot text -> official six-section prompt
# --------------------------------------------------------------------------

class _Ctx:
    def __init__(self, language: str, names: dict, issues: list, cues=()):
        self.names = names     # lowercase name -> label
        self.cues = set(cues)  # labels of reused tracks whose verbal cues have no speaker
        self.speakers = {}     # lowercase key -> number
        self.language = language.strip() or "English"
        self.issues = issues

    def err(self, section, msg):
        self.issues.append(Issue(ERROR, section, msg))

    def label(self, name: str, section: str):
        key = name.lower()
        if key in self.names:
            return self.names[key]
        self.err(section, f"unknown reference '@{name}'." + _suggest(key, self.names)
                 + " Every @name must be the name of a connected reference.")
        return None

    def speaker(self, key: str, section: str, assign: bool):
        key = key.lower()
        if key not in self.speakers:
            if not assign:
                self.err(section, f"'{key}' never speaks in the shots, so it has no (Sx) number. "
                                  f"Mark their lines with @{key}(s) or (s:{key}).")
                return None
            self.speakers[key] = len(self.speakers) + 1
        return self.speakers[key]

    def expand(self, text: str, section: str, assign: bool = False, dialogue: bool = False) -> str:
        """Expands @name, @name(s), (s:key) and {{line}}. In the shots, a line's speaker is the one subject
        named before it in the same sentence, unless @name(s) or (s:key) says who it is."""
        pieces = []
        mentions = []      # (piece index, key) of subjects named since the sentence start or the last line
        marked = False     # @name(s) or (s:key) since the sentence start or the last line
        spoken = False     # a line in this sentence already has a speaker
        cue = False        # a music or soundtrack <Audio N> is named before the line: a cue inside it has no speaker
        pos = 0
        for m in _TOKEN_RE.finditer(text):
            pieces.append(text[pos:m.start()])
            pos = m.end()
            if m["end"]:
                pieces.append(m["end"])
                mentions, marked, spoken, cue = [], False, False, False
            elif m["line"] is not None:
                body = m["line"].strip()
                if not dialogue:
                    self.err(section, "dialogue {{...}} is only allowed in the shots; the spec forbids repeating "
                                      "spoken lines in other sections.")
                elif not marked and not cue:
                    keys = list(dict.fromkeys(k for _, k in mentions))
                    if len(keys) == 1:
                        n = self.speaker(keys[0], section, assign)
                        pieces[max(i for i, k in mentions if k == keys[0])] += f" (S{n})"
                    elif keys:
                        self.err(section, f"who says '{body[:40]}'? {', '.join('@' + k for k in keys)} are all named "
                                          "before it; mark the speaker with @name(s).")
                    elif not spoken:
                        self.err(section, f"who says '{body[:40]}'? Name the speaker in the same sentence, e.g. "
                                          "'@joni says {{...}}', or for someone without a reference, "
                                          "'a child (s:child) says {{...}}'.")
                lang = self.language
                lm = re.match(r"([A-Za-z][A-Za-z \-]{1,30})\|\s*", body)
                if lm:
                    lang, body = lm.group(1).strip(), body[lm.end():]
                pieces.append(f"<d>[{lang}] {body}</d>")
                mentions, marked, spoken, cue = [], False, True, False
            elif m["spk"] is not None:  # (s:key) or (s:a,b)
                nums = [self.speaker(k.strip(), section, assign) for k in m["spk"].split(",")]
                pieces.append(m.group(0) if None in nums else "(" + ",".join(f"S{n}" for n in nums) + ")")
                marked = True
            else:
                name = m["name"]
                lab = self.label(name, section)
                if lab is None:
                    pieces.append(m.group(0))
                elif m["s"]:
                    if not lab.startswith("<Subject"):
                        self.err(section, f"'@{name}(s)': only subjects can speak. For a voice with no subject "
                                          "use '(s:somename)'.")
                        pieces.append(lab)
                    else:
                        n = self.speaker(name, section, assign)
                        pieces.append(f"{lab} (S{n})" if n else lab)
                        marked = True
                else:
                    pieces.append(lab)
                    if lab.startswith("<Subject"):
                        mentions.append((len(pieces) - 1, name.lower()))
                    cue = cue or lab in self.cues
        pieces.append(text[pos:])
        return "".join(pieces)


def _label_refs(refs, issues):
    """Number the assets the way MiniMax H3 Reference to Video presents them: images, then videos, then
    audio, where each video's soundtrack takes its <Audio j> before the standalone audio.
    Returns (subjects, assets, names): subject groups, non-subject entries, and the @name -> label map."""
    def err(msg):
        issues.append(Issue(ERROR, "references", msg))

    counts = {"image": 0, "video": 0, "audio": 0}
    entries = []
    for r in [r for r in refs if r["kind"] == "image"] + [r for r in refs if r["kind"] == "video"]:
        counts[r["kind"]] += 1
        entries.append(dict(r, label=f"<{'Picture' if r['kind'] == 'image' else 'Video'} {counts[r['kind']]}>"))
    for e in list(entries):
        if e["kind"] == "video" and e.get("soundtrack"):
            counts["audio"] += 1
            entries.append({"kind": "audio", "role": "soundtrack", "name": e["name"] + "_audio", "description": "",
                            "what_is_kept": "", "keep": e["soundtrack"], "video": e["label"],
                            "label": f"<Audio {counts['audio']}>"})
    for r in refs:
        if r["kind"] == "audio":
            counts["audio"] += 1
            entries.append(dict(r, label=f"<Audio {counts['audio']}>"))

    subjects, assets, names = {}, [], {}
    for e in entries:
        key = e["name"].strip().lower()
        if not key:
            err(f"the {e['kind']} reference {e['label']} has no name. Give each reference a name to use as @name.")
            continue
        if not _NAME_RE.fullmatch(key):
            err(f"'{e['name']}' is not a valid name (letters, digits and underscore, not starting with a digit).")
            continue
        if (e["kind"], e["role"]) in SUBJECT_ROLES:
            if key in names and key not in subjects:
                err(f"the name '{key}' is used by two references. Only subject references (character, environment, "
                    "prop, outfit, style, motion) may share a name, which merges them into one subject.")
                continue
            if key not in subjects:
                subjects[key] = {"label": f"<Subject {len(subjects) + 1}>", "refs": []}
                names[key] = subjects[key]["label"]
            subjects[key]["refs"].append(e)
        else:
            if key in names:
                err(f"the name '{key}' is used by two references; only subject references may share a name.")
                continue
            names[key] = e["label"]
            assets.append(e)
    return subjects, assets, names


def _parse_shots(raw):
    style_lines, shot_list, cur = [], [], None
    for line in raw.split("\n"):
        s = line.strip()
        if s.startswith(">>"):
            rest = s[2:].strip()
            t = None
            if rest:
                first = rest.split(None, 1)
                pt = _parse_time(first[0])
                if pt is not None:
                    t, rest = pt, (first[1] if len(first) > 1 else "")
            cur = {"t": t, "lines": [rest] if rest else []}
            shot_list.append(cur)
        elif cur is None:
            style_lines.append(s)
        else:
            cur["lines"].append(s)
    return style_lines, shot_list


def compile_prompt(refs, summary: str, shots: str, soundscape: str, music: str, language: str = "English"):
    """refs: dicts with kind (image/video/audio), role, name, description, what_is_kept, keep, and per role
    shots (staging layout), speaker (voice) or soundtrack (video soundtrack marker, or None).
    Returns (prompt_text, [Issue], legend lines)."""
    issues = []
    subjects, assets, names = _label_refs(refs, issues)
    ctx = _Ctx(language, names, issues, [a["label"] for a in assets if a["kind"] == "audio" and a["role"] != "voice"])
    raw = {k: _strip_comments(v) for k, v in dict(summary=summary, shots=shots, soundscape=soundscape, music=music).items()}

    # ---- detailed_description (assigns speaker numbers in order of vocal events) ----
    literal = re.search(r"\(S\d+(?:,S\d+)*\)", "\n".join(raw.values()))
    style_lines, shot_list = _parse_shots(raw["shots"])
    if not shot_list:
        ctx.err("detailed_description", "no shots found. Start each shot with a '>>' line "
                                        "('>>' for the first, '>> 3.5' for a cut at 3.5 s).")
    style = ctx.expand(_one_line(" ".join(style_lines)), "detailed_description", True, True)
    if not style:
        ctx.err("detailed_description", "write the style in one or two sentences before the first '>>'.")
    bodies = []
    for i, sh in enumerate(shot_list, 1):
        body = ctx.expand(_one_line(" ".join(sh["lines"])), "detailed_description", True, True)
        if not body:
            ctx.err("detailed_description", f"shot {i} is empty.")
        if i == 1 and sh["t"]:
            ctx.err("detailed_description", "the first '>>' must not have a time; [Shot 1] has no timestamp.")
        if i > 1 and sh["t"] is None:
            ctx.err("detailed_description", f"shot {i} needs a cut time, e.g. '>> 3.5 the shot cuts to ...'.")
        bodies.append(body)
    if literal and ctx.speakers:
        ctx.err("detailed_description", f"literal speaker ID '{literal.group(0)}' is mixed with auto-numbered "
                                        "speakers ('@name(s)' / '(s:name)'). Use one style only.")
    n_shots = len(bodies)
    for a in assets:
        if a["role"] == "first frame" and bodies and a["label"] not in bodies[0]:
            bodies[0] = f"The shot begins from {a['label']}. " + bodies[0]
        if a["role"] == "last frame" and bodies and a["label"] not in bodies[-1]:
            bodies[-1] = bodies[-1] + f" The shot ends on {a['label']}."
    dd_lines = [style] if style else []
    for i, (sh, body) in enumerate(zip(shot_list, bodies), 1):
        stamp = f"At {_fmt_ts(sh['t'])}, " if i > 1 and sh["t"] is not None else ""
        dd_lines.append(f"[Shot {i}] {stamp}{body}")

    def notes(e, default):
        if e["what_is_kept"].strip():
            return ctx.expand(_one_line(e["what_is_kept"]), "retention_analysis")
        if e["keep"] in VAGUE_MARKERS and not (e["kind"] == "audio" and e["keep"] == "weak_reference"):
            issues.append(Issue(WARN, "retention_analysis", f"'{e['name']}' is {e['keep']} but what_is_kept is empty, so "
                                                            f"the line only says '{default}' Say what is kept and what changes."))
        return default

    def desc(e, section="subject_definitions"):
        return ctx.expand(_one_line(e["description"]).rstrip("."), section)

    tasks = set()
    def_lines, ret_lines, music_lines, sound_lines = [], [], [], []

    # ---- subjects ----
    for key, s in subjects.items():
        lab, first = s["label"], s["refs"][0]
        d = next((desc(e) for e in s["refs"] if e["description"].strip()), "")
        if not d:
            ctx.err("subject_definitions", f"'{key}' has no description. Describe its main features, "
                                           "e.g. 'the young woman with long dark hair and a blue cardigan'.")
            d = key
        sources = {}
        for e in s["refs"]:
            sources.setdefault(SUBJECT_ROLES[(e["kind"], e["role"])][0], []).append(e["label"])
        cites = " and ".join(f"{phrase} {_join(labels)}" for phrase, labels in sources.items())
        def_lines.append(f"{lab} is {d}, {cites}.")
        tasks.add("reference generation")
        shown = [i for i, b in enumerate(bodies, 1) if lab in b]
        if not shown:
            if first["role"] in EVERY_SHOT_ROLES:
                shown = list(range(1, n_shots + 1))
            elif n_shots:
                ctx.err("retention_analysis", f"'{key}' ({lab}) never appears in the shots. Tag it with @{key} "
                                              "where it is seen.")
        aspects = SUBJECT_ROLES[(first["kind"], first["role"])][1]
        note = notes(first, VISUAL_NOTES[first["keep"]].format(aspects))
        ret_lines.append(f"{lab} (appears in {_shot_list(shown)}): {first['keep']} - {note}")

    # ---- pictures, videos, audio ----
    for e in assets:
        lab, role, keep = e["label"], e["role"], e["keep"]
        d = desc(e) if e["description"].strip() else ""
        showing = f", showing {d}" if d else ""
        if e["kind"] in ("image", "video"):
            if role == "staging layout":
                spec = e.get("shots", "1").strip().lower()
                if spec == "all":
                    nums = list(range(1, n_shots + 1))
                else:
                    nums = [int(n) for n in re.findall(r"\d+", spec)]
                    if not nums or any(not 1 <= n <= n_shots for n in nums):
                        ctx.err("references", f"staging layout '{e['name']}': shots '{e.get('shots', '')}' must be "
                                              f"shot numbers between 1 and {n_shots}, or 'all'.")
                where = _join([f"[Shot {n}]" for n in nums]) if nums else "[Shot 1]"
                definition = f"{lab} is the staging-layout reference for {where}, defining the camera viewpoint and the placement of the subjects{showing}."
                paren = f"{_shot_list(nums or [1])} staging layout"
                tasks.add("reference generation")
            elif role == "first frame":
                definition = f"{lab} is the first frame of [Shot 1]{showing}."
                paren = "[Shot 1] first frame"
                tasks.add("keyframe completion")
            elif role == "last frame":
                definition = f"{lab} is the last frame of [Shot {max(n_shots, 1)}]{showing}."
                paren = f"[Shot {max(n_shots, 1)}] last frame"
                tasks.add("keyframe completion")
            elif role == "camera and pacing":
                definition = f"{lab} is the camera-movement and pacing reference for the target video{showing}."
                paren = "camera movement and pacing"
                tasks.add("reference generation")
            elif role == "edit source":
                definition = f"{lab} is the source video for the target video edit{showing}."
                paren = "source video"
                tasks.add("video editing")
            else:  # continue from
                definition = f"{lab} is the source video that the target video continues from{showing}."
                paren = "continuation source"
                tasks.add("video continuation")
            def_lines.append(definition)
            ret_lines.append(f"{lab} ({paren}): {keep} - {notes(e, VISUAL_NOTES[keep].format(ASSET_ASPECTS[role]))}")
            continue

        tasks.add("audio reuse" if keep in ("fully_copy", "partially_copy") else "audio reference")
        voiced = d and f", {d}"
        if role == "voice":
            key = e["speaker"].strip().lower()
            who, who_id = (names[key] if key in subjects else f"the {key}"), ""
            if not key:
                ctx.err("references", f"the voice '{e['name']}' ({lab}) needs a speaker: the name of the subject "
                                      "it voices, or the key used in (s:key) in the shots.")
            else:
                n = ctx.speaker(key, "references", False)
                who_id = f"{who} (S{n})" if n else who
            if keep in ("fully_copy", "partially_copy"):
                definition = f"{lab} is the spoken audio of {who_id}{AUDIO_USE[keep]}{voiced}."
            else:
                definition = f"{lab} is the voice-timbre reference for {who_id}{voiced}."
            default = AUDIO_NOTES["voice"][keep].format(a=lab, who=who)
        elif role == "soundtrack":
            definition = f"{lab} is the synchronized audio track of {e['video']}{AUDIO_USE[keep]}."
            default = AUDIO_NOTES["soundtrack"][keep].format(a=lab)
        else:
            what = "background music" if role == "music" else "ambience track"
            if keep in ("fully_copy", "partially_copy"):
                definition = f"{lab} is the {what}{AUDIO_USE[keep]}{voiced}."
            else:
                definition = f"{lab} is the {what} reference{voiced}."
            default = AUDIO_NOTES[role][keep].format(a=lab)
            (music_lines if role == "music" else sound_lines).append(SECTION_SENTENCES[role][keep].format(a=lab))
        def_lines.append(definition)
        ret_lines.append(f"{lab}: {keep} - {notes(e, default)}")

    # ---- summary ----
    summ = ctx.expand(_one_line(raw["summary"]), "summary")
    if not summ:
        ctx.err("summary", "write a one-paragraph summary of the video.")
    if summ.startswith("["):
        ctx.err("summary", "don't type the [task type] prefix; it is worked out from the reference roles.")
    for e in assets:
        lead = f"The target video is an edited version of {e['label']}."
        if e["role"] == "edit source" and not summ.startswith(lead):
            summ = f"{lead} {summ}".strip()
    if not tasks:
        ctx.err("summary", "connect at least one reference.")
    summ_out = f"[{' + '.join(t for t in TASK_TYPES if t in tasks)}] {summ}"

    snd = " ".join(sound_lines + [ctx.expand(_one_line(raw["soundscape"]), "overall_soundscape")]).strip() or "N/A"
    mus = " ".join(music_lines + [ctx.expand(_one_line(raw["music"]), "non_diegetic_music")]).strip() or "N/A"

    text = "\n\n".join([
        "subject_definitions:\n" + "\n".join(def_lines),
        "summary:\n" + summ_out,
        "retention_analysis:\n" + "\n".join(ret_lines),
        "detailed_description:\n" + "\n".join(dd_lines),
        "overall_soundscape:\n" + snd,
        "non_diegetic_music:\n" + mus,
    ])
    for junk, why in (("{{", "unclosed dialogue '{{'"), ("}}", "stray '}}'"), (">>", "stray '>>' (must start a line)")):
        if junk in text:
            ctx.err("prompt", why + " left in the compiled prompt.")

    legend = ["References:"]
    for key, s in subjects.items():
        legend.append(f"  @{key} = {s['label']} ({', '.join(e['label'] + ' ' + e['role'] for e in s['refs'])})")
    for e in assets:
        legend.append(f"  @{e['name'].strip().lower()} = {e['label']} ({e['role']})")
    if ctx.speakers:
        legend.append("Speakers: " + ", ".join(f"(S{n}) {k}" for k, n in ctx.speakers.items()))
    return text, issues, legend


# --------------------------------------------------------------------------
# Linter: validates a final six-section prompt against the official format
# --------------------------------------------------------------------------

def lint(text: str, duration: float | None = None, n_images: int | None = None,
         n_videos: int | None = None, n_audios: int | None = None):
    issues = []

    def add(level, section, msg):
        issues.append(Issue(level, section, msg))

    text = (text or "").replace("\r\n", "\n")

    # ---- section headers ----
    for m in re.finditer(r"(?m)^([ \t]*)([A-Za-z][A-Za-z_ \-]{4,30}?)[ \t]*:", text):
        raw_name = m.group(2)
        norm = re.sub(r"[ \-]+", "_", raw_name.strip().lower())
        exact = (m.group(1) == "" and raw_name in SECTIONS and text[m.end() - 1] == ":"
                 and m.end() - m.start() == len(raw_name) + 1)
        if exact:
            continue
        close = difflib.get_close_matches(norm, SECTIONS, n=1, cutoff=0.8)
        if close:
            add(ERROR, "structure", f"section header '{m.group(0).strip()}' must be written exactly "
                                    f"'{close[0]}:' at the start of a line.")

    found = [(m.group(1), m.start(), m.end()) for m in _HEADER_RE.finditer(text)]
    names = [f[0] for f in found]
    for s in SECTIONS:
        if names.count(s) == 0:
            add(ERROR, "structure", f"section '{s}:' is missing.")
        elif names.count(s) > 1:
            add(ERROR, "structure", f"section '{s}:' appears {names.count(s)} times.")
    if [n for n in names if n in SECTIONS] != SECTIONS and sorted(names) == sorted(SECTIONS):
        add(ERROR, "structure", "sections are out of order. Required order: " + ", ".join(SECTIONS) + ".")
    if found and text[:found[0][1]].strip():
        add(WARN, "structure", "there is text before 'subject_definitions:'; the format starts with that header.")

    sec = {}
    for i, (name, _s, e) in enumerate(found):
        end = found[i + 1][1] if i + 1 < len(found) else len(text)
        sec.setdefault(name, text[e:end].strip())

    # ---- tags, everywhere ----
    for m in _ANY_TAG_RE.finditer(text):
        if not _VALID_TAG_RE.match(m.group(0)):
            add(ERROR, "tags", f"'{m.group(0)}' is not a valid tag. Valid: <Subject N>, <Picture N>, <Video N>, "
                               "<Audio N>, <d>…</d>, <scenetrans>, <cutoff> (exact case, one space, no leading zero).")
    stripped = _ANY_TAG_RE.sub("", text)
    if "<" in stripped or ">" in stripped:
        add(WARN, "tags", "stray '<' or '>' outside a tag (unclosed tag?).")
    for m in re.finditer(r"(?<![<\w])(Subject|Picture|Video|Audio) (\d+)(?!>)", text):
        add(WARN, "tags", f"bare '{m.group(0)}' without angle brackets; the model only binds '<{m.group(0)}>'.")
    for m in re.finditer(r"[\[(]\s*(Subject|Picture|Video|Audio)\s*\d+\s*[\])]", text):
        add(ERROR, "tags", f"'{m.group(0)}' uses the wrong brackets; labels use angle brackets.")
    for m in re.finditer(r"\[\s*shot\s*\d+\s*\]", text, flags=re.I):
        if not _SHOT_RE.fullmatch(m.group(0)):
            add(ERROR, "tags", f"'{m.group(0)}' must be written exactly like '[Shot 2]'.")
    for m in re.finditer(r"[\[(]\s*s\s*\d+\s*[\])]", text, flags=re.I):
        if not _SPEAKER_RE.fullmatch(m.group(0)):
            add(ERROR, "tags", f"'{m.group(0)}' is not a valid speaker ID; write '(S1)'.")

    def labels_in(s):
        return [f"<{k} {n}>" for k, n in _LABEL_RE.findall(s or "")]

    # ---- subject_definitions ----
    defined, cited = [], set(labels_in(sec.get("subject_definitions", "")))
    sd = sec.get("subject_definitions")
    if sd is not None:
        if not sd:
            add(ERROR, "subject_definitions", "section is empty.")
        for line in [l.strip() for l in sd.split("\n") if l.strip()]:
            m = re.match(r"<(Subject|Picture|Video|Audio) ([1-9]\d*)>", line)
            if not m:
                add(ERROR, "subject_definitions", f"every line must start with a label: '{line[:50]}…'")
                continue
            lab = m.group(0)
            if lab in defined:
                add(ERROR, "subject_definitions", f"{lab} is defined more than once.")
            defined.append(lab)
            if not line[m.end():].startswith(" is "):
                add(WARN, "subject_definitions", f"{lab}: definitions read '{lab} is …'.")
            if m.group(1) == "Subject" and not re.search(r"<(Picture|Video|Audio) \d+>", line):
                add(WARN, "subject_definitions", f"{lab} names no source asset (<Picture N> / <Video N>), so the "
                                                 "model has nothing to bind it to.")
        subj = [int(l[9:-1]) for l in defined if l.startswith("<Subject")]
        if subj != list(range(1, len(subj) + 1)):
            add(WARN, "subject_definitions", "subjects should be numbered 1, 2, 3… in order.")

    for name in SECTIONS[1:]:
        for lab in dict.fromkeys(labels_in(sec.get(name, ""))):
            if lab not in cited:
                add(ERROR, name, f"{lab} is used but never defined or cited in subject_definitions.")

    # ---- asset counts ----
    all_labels = labels_in(text)
    for kind, count, what in (("Picture", n_images, "image"), ("Video", n_videos, "video"), ("Audio", n_audios, "audio")):
        if count is None:
            continue
        used = sorted({int(l.split()[1][:-1]) for l in all_labels if l.startswith(f"<{kind}")})
        for n in used:
            if n > count:
                add(ERROR, "assets", f"<{kind} {n}> is referenced but only {count} {what} reference(s) are wired.")
        for n in range(1, count + 1):
            if n not in used:
                add(WARN, "assets", f"{what} reference {n} is wired but <{kind} {n}> never appears in the prompt.")

    # ---- summary ----
    sm = sec.get("summary")
    types = []
    if sm is not None:
        m = re.match(r"\[([^\]]*)\]", sm)
        if not m:
            add(ERROR, "summary", "must begin with a task-type prefix such as '[reference generation]'.")
        else:
            parts = [p.strip() for p in m.group(1).split("+")]
            for p in parts:
                if p not in TASK_TYPES:
                    add(ERROR, "summary", f"'{p}' is not a task type." + _suggest(p, TASK_TYPES)
                        + " Valid: " + ", ".join(TASK_TYPES) + ".")
            if len(set(parts)) != len(parts):
                add(ERROR, "summary", "a task type is repeated.")
            if m.group(1) != " + ".join(parts):
                add(ERROR, "summary", "combine task types with ' + ' (one space each side).")
            types = parts
            rest = sm[m.end():]
            if not rest.strip():
                add(ERROR, "summary", "no text after the task-type prefix.")
            elif not rest.startswith(" "):
                add(WARN, "summary", "put one space after the task-type prefix.")
            if "video editing" in types and not re.match(
                    r" The target video is an edited version of <Video \d+>\.", rest):
                add(WARN, "summary", "video-editing summaries begin 'The target video is an edited version of <Video N>.'")
            if "\n" in sm.strip():
                add(WARN, "summary", "summary should be one paragraph.")
        has = lambda k: any(l.startswith(f"<{k}") for l in all_labels)
        if ({"video editing", "video continuation"} & set(types)) and not has("Video"):
            add(ERROR, "summary", "video editing / continuation is declared but no <Video N> is used.")
        if ({"audio reuse", "audio reference"} & set(types)) and not has("Audio"):
            add(WARN, "summary", "an audio task type is declared but no <Audio N> is used.")
        if "keyframe completion" in types and not any(l.startswith("<Picture") for l in defined):
            add(WARN, "summary", "keyframe completion is declared but no <Picture N> has its own definition line "
                                 "as a frame anchor.")

    # ---- detailed_description ----
    dd = sec.get("detailed_description")
    n_shots, shot_bodies, speakers_dd = 0, {}, []
    if dd is not None:
        marks = list(_SHOT_RE.finditer(dd))
        nums = [int(m.group(1)) for m in marks]
        n_shots = len(nums)
        if not marks:
            add(ERROR, "detailed_description", "no [Shot 1] marker found.")
        else:
            if nums != list(range(1, len(nums) + 1)):
                add(ERROR, "detailed_description", f"shots must be numbered 1, 2, 3… in order; found {nums}.")
            if not dd[:marks[0].start()].strip():
                add(WARN, "detailed_description", "in Ref2VA the style is stated in one or two sentences BEFORE [Shot 1].")
            last_t = 0.0
            for i, m in enumerate(marks):
                end = marks[i + 1].start() if i + 1 < len(marks) else len(dd)
                body = dd[m.end():end]
                shot_bodies[nums[i]] = body
                ts = _TS_RE.match(body)
                if i == 0:
                    if re.match(r"\s*At \d", body):
                        add(ERROR, "detailed_description", "[Shot 1] must not have a timestamp.")
                    continue
                if not ts:
                    add(ERROR, "detailed_description", f"[Shot {nums[i]}] must be followed by ' At MM:SS.mmm, ' "
                                                       "(e.g. '[Shot 2] At 00:03.500, the shot cuts to …').")
                    continue
                t = int(ts.group(1)) * 60 + int(ts.group(2)) + int(ts.group(3)) / 1000
                if t <= last_t:
                    add(ERROR, "detailed_description", f"[Shot {nums[i]}] cut time {_fmt_ts(t)} is not later than the previous cut.")
                if duration and t >= duration:
                    add(ERROR, "detailed_description", f"[Shot {nums[i]}] cuts at {_fmt_ts(t)}, at or past the "
                                                       f"{duration:g}s video length; the shot would never play.")
                last_t = t
                after = body[ts.end():].lstrip().lower()
                if not after.startswith(CUT_PHRASES):
                    add(WARN, "detailed_description", f"[Shot {nums[i]}] should open with a cut phrase after the "
                                                      "timestamp, e.g. 'the shot cuts to …'.")
        # dialogue
        depth, pos = 0, 0
        seg_start = 0
        for m in re.finditer(r"<d>|</d>", dd):
            if m.group(0) == "<d>":
                if depth:
                    add(ERROR, "detailed_description", "<d> opened inside another <d> (missing </d>).")
                depth, pos = 1, m.end()
                lead = dd[seg_start:m.start()]
                sm_ = list(_SHOT_RE.finditer(lead))
                if sm_:
                    lead = lead[sm_[-1].end():]
                if not (_SPEAKER_RE.search(lead) or re.search(r"<Audio \d+>", lead)):
                    add(WARN, "detailed_description", "a <d> line has no speaker ID (Sx) or <Audio N> source before it: '"
                        + dd[m.end():m.end() + 40].strip() + "…'")
            else:
                if not depth:
                    add(ERROR, "detailed_description", "</d> without a matching <d>.")
                    continue
                depth = 0
                seg_start = m.end()
                inner = dd[pos:m.start()]
                if not re.match(r"\[[^\[\]]+\] \S", inner):
                    add(ERROR, "detailed_description", f"dialogue must start with a language tag, '<d>[English] …': '{inner[:40]}'")
                core = re.sub(r"(<scenetrans>|<cutoff>|\s)+$", "", inner)
                if core == inner.rstrip() and core[-1:] not in ".?!。？！":
                    add(WARN, "detailed_description", f"dialogue should end with . ? or ! before </d>: '…{inner[-30:]}'")
        if depth:
            add(ERROR, "detailed_description", "<d> is never closed with </d>.")
        if dd.count("<scenetrans>") % 2:
            add(WARN, "detailed_description", "<scenetrans> should appear at both connecting points of a line that crosses a cut.")
        if re.search(r"(says?|said|shouts?|replies|asks?|whispers?|exclaims?)[,:]?\s+[\"“]", dd):
            add(WARN, "detailed_description", "spoken words appear in quotation marks; dialogue must be inside "
                                              "<d>[Language] …</d> (quotes are for on-screen text).")
        if re.search(r"voice-?over", dd, flags=re.I) and "says in an off-screen voiceover" not in dd:
            add(WARN, "detailed_description", "voiceover uses the exact phrase 'says in an off-screen voiceover'.")
        for m in _SPEAKER_RE.finditer(dd):
            for n in re.findall(r"S(\d+)", m.group(0)):
                if int(n) not in speakers_dd:
                    speakers_dd.append(int(n))
        if speakers_dd != list(range(1, len(speakers_dd) + 1)):
            add(WARN, "detailed_description", f"speaker IDs should be assigned S1, S2… in order of first speech; found order {speakers_dd}.")
        words = len(re.findall(r"\b[\w'’-]+\b", _ANY_TAG_RE.sub(" ", dd)))
        if not 350 <= words <= 500:
            add(INFO, "detailed_description", f"{words} words; generation tasks normally run 350–500 "
                                              "(dialogue-dense or editing prompts may differ).")

    for name in SECTIONS:
        if name != "detailed_description" and "<d>" in sec.get(name, ""):
            add(ERROR, name, "dialogue <d> belongs only in detailed_description.")
    for m in _SPEAKER_RE.finditer(sec.get("subject_definitions", "")):
        for n in re.findall(r"S(\d+)", m.group(0)):
            if int(n) not in speakers_dd:
                add(ERROR, "subject_definitions", f"(S{n}) is used here but nobody speaks as (S{n}) in detailed_description.")

    # ---- retention_analysis ----
    ra = sec.get("retention_analysis")
    if ra is not None:
        seen = []
        if _SPEAKER_RE.search(ra):
            add(ERROR, "retention_analysis", "speaker IDs (Sx) must not appear in retention_analysis.")
        line_re = re.compile(r"^<(Subject|Picture|Video|Audio) ([1-9]\d*)>(?: \((.+?)\))?: (\S+) - (\S.*)$")
        for line in [l.strip() for l in ra.split("\n") if l.strip()]:
            m = line_re.match(line)
            if not m:
                add(ERROR, "retention_analysis", f"malformed line: '{line[:60]}…'. Format: "
                                                 "'<Subject 1> (appears in [Shot 1]): fully_preserved - …'.")
                continue
            kind, n, paren, marker = m.group(1), m.group(2), m.group(3), m.group(4)
            lab = f"<{kind} {n}>"
            if lab in seen:
                add(ERROR, "retention_analysis", f"{lab} has more than one line.")
            seen.append(lab)
            valid = AUDIO_MARKERS if kind == "Audio" else VISUAL_MARKERS
            if marker not in valid:
                add(ERROR, "retention_analysis", f"{lab}: '{marker}' is not a valid marker." + _suggest(marker, valid)
                    + f" Valid for {kind}: " + ", ".join(valid) + ".")
            for s in _SHOT_RE.findall(paren or ""):
                if n_shots and int(s) > n_shots:
                    add(ERROR, "retention_analysis", f"{lab} cites [Shot {s}] but there are only {n_shots} shot(s).")
            if kind == "Subject":
                if not (paren or "").startswith("appears in [Shot"):
                    add(WARN, "retention_analysis", f"{lab} should say where it appears: '(appears in [Shot 1], [Shot 2])'.")
                else:
                    listed = {int(s) for s in _SHOT_RE.findall(paren)}
                    extra = [k for k, b in shot_bodies.items() if lab in b and k not in listed]
                    if extra:
                        add(WARN, "retention_analysis", f"{lab} is tagged in shot(s) {extra} that its line doesn't list.")
            if kind == "Audio":
                if marker in ("fully_copy", "partially_copy") and types and "audio reuse" not in types:
                    add(WARN, "retention_analysis", f"{lab} is copied ({marker}) but the summary lacks the 'audio reuse' task type.")
                if marker == "reference" and types and "audio reference" not in types:
                    add(WARN, "retention_analysis", f"{lab} is a 'reference' but the summary lacks the 'audio reference' task type.")
        for lab in defined:
            if lab not in seen:
                add(ERROR, "retention_analysis", f"{lab} is defined but has no retention line (one line per label).")
        for lab in seen:
            if lab not in defined:
                add(WARN, "retention_analysis", f"{lab} has a retention line but no definition line of its own.")

    # ---- audio sections ----
    for name in ("overall_soundscape", "non_diegetic_music"):
        v = sec.get(name)
        if v is None:
            continue
        if not v:
            add(ERROR, name, "section is empty; write a description or 'N/A'.")
        elif v.lower() in ("n/a", "na", "none", "no music", "-") and v != "N/A":
            add(WARN, name, f"write exactly 'N/A' (found '{v}').")
    if sec.get("overall_soundscape") == "N/A":
        add(INFO, "overall_soundscape", "'N/A' here means complete silence throughout the video.")

    return issues
