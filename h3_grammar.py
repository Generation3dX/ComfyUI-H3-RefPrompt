"""
MiniMax H3 Ref2VA prompt grammar: shorthand compiler + linter.

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
    "keyframe completion",
    "reference generation",
    "video editing",
    "video continuation",
    "audio reuse",
    "audio reference",
]

VISUAL_MARKERS = ["fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference"]
AUDIO_MARKERS = ["fully_copy", "partially_copy", "reference", "weak_reference"]

VISUAL_ALIASES = {
    "full": "fully_preserved",
    "partial": "partially_preserved",
    "transfer": "attribute_transfer",
    "weak": "weak_reference",
}
AUDIO_ALIASES = {
    "copy": "fully_copy",
    "full": "fully_copy",
    "partial": "partially_copy",
    "ref": "reference",
    "weak": "weak_reference",
}

KINDS = {"pic": "Picture", "vid": "Video", "aud": "Audio"}

CUT_PHRASES = (
    "the camera cuts to",
    "the shot cuts to",
    "the shot transitions to",
    "the shot changes to",
    "the shot switches to",
)

FPS = 24

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"

_LABEL_RE = re.compile(r"<(Subject|Picture|Video|Audio) ([1-9]\d*)>")
_VALID_TAG_RE = re.compile(r"^<(?:(?:Subject|Picture|Video|Audio) [1-9]\d*|/?d|scenetrans|cutoff)>$")
_ANY_TAG_RE = re.compile(r"<[^<>\n]{0,60}>")
_SPEAKER_RE = re.compile(r"\(S([1-9]\d*)((?:,S[1-9]\d*)*)\)")
_HEADER_RE = re.compile(r"(?m)^(" + "|".join(SECTIONS) + r"):")
_SHOT_RE = re.compile(r"\[Shot ([1-9]\d*)\]")
_TS_RE = re.compile(r" At (\d\d):(\d\d)\.(\d\d\d), ")


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
        return "\n".join([head] + lines)


def frames_for_duration(seconds: float) -> int:
    """Snap to H3's 17k+5 frame grid at 24 fps (same maths as the official template)."""
    f = max(5, round(seconds * FPS))
    return f + (5 - f % 17) % 17


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


# --------------------------------------------------------------------------
# Compiler: readable shorthand -> official six-section prompt
# --------------------------------------------------------------------------

class _Ctx:
    def __init__(self, language: str):
        self.subjects = {}   # lowercase name -> number
        self.speakers = {}   # lowercase key -> number
        self.language = language.strip() or "English"
        self.issues = []

    def err(self, section, msg):
        self.issues.append(Issue(ERROR, section, msg))

    def label(self, name: str, section: str):
        """Resolve 'pic1' / 'natalie' to an official label, or None."""
        key = name.lower()
        m = re.fullmatch(r"(pic|vid|aud)([1-9]\d*)", key)
        if m:
            return f"<{KINDS[m.group(1)]} {m.group(2)}>"
        if key in self.subjects:
            return f"<Subject {self.subjects[key]}>"
        self.err(section, f"unknown reference '@{name}'." + _suggest(key, self.subjects)
                 + " (Assets are @pic1 / @vid1 / @aud1; subjects must be defined in 'subjects'.)")
        return None

    def speaker(self, key: str, section: str, assign: bool):
        key = key.lower()
        if key not in self.speakers:
            if not assign:
                self.err(section, f"speaker '{key}' is referenced here but never speaks in the shots, "
                                  "so it has no (Sx) number.")
                return None
            self.speakers[key] = len(self.speakers) + 1
        return self.speakers[key]

    def expand(self, text: str, section: str, assign: bool = False, dialogue: bool = False) -> str:
        def tok(m):
            if m.group("spk") is not None:  # (s:key) or (s:a,b)
                nums = [self.speaker(k.strip(), section, assign) for k in m.group("spk").split(",")]
                if None in nums:
                    return m.group(0)
                return "(" + ",".join(f"S{n}" for n in nums) + ")"
            name, speaks = m.group("name"), m.group("s")
            lab = self.label(name, section)
            if lab is None:
                return m.group(0)
            if speaks:
                if not lab.startswith("<Subject"):
                    self.err(section, f"'@{name}(s)': only subjects can speak. For a voice with no subject "
                                      "use '(s:somename)'.")
                    return lab
                n = self.speaker(name, section, assign)
                return f"{lab} (S{n})" if n else lab
            return lab

        out = re.sub(r"\(s:(?P<spk>[\w ,]+)\)|@(?P<name>[A-Za-z_]\w*)(?P<s>\(s\))?", tok, text, flags=re.I)

        def dlg(m):
            body = m.group(1).strip()
            lang = self.language
            lm = re.match(r"([A-Za-z][A-Za-z \-]{1,30})\|\s*", body)
            if lm:
                lang, body = lm.group(1).strip(), body[lm.end():]
            if not dialogue:
                self.err(section, "dialogue {{...}} is only allowed in the shots; the spec forbids repeating "
                                  "spoken lines in other sections.")
            return f"<d>[{lang}] {body}</d>"

        return re.sub(r"\{\{(.*?)\}\}", dlg, out, flags=re.S)


def compile_prompt(subjects: str, summary: str, retention: str, shots: str,
                   soundscape: str, music: str, task_types, language: str = "English"):
    """Returns (prompt_text, [Issue]). Compile errors are in the issue list."""
    ctx = _Ctx(language)
    raw = {k: _strip_comments(v) for k, v in dict(
        subjects=subjects, summary=summary, retention=retention, shots=shots,
        soundscape=soundscape, music=music).items()}

    # ---- pass 1: subject_definitions entries (names -> numbers) ----
    entries = []  # [lhs_kind, lhs_key, rhs]
    for line in raw["subjects"].split("\n"):
        if not line.strip():
            continue
        if line[0] in " \t" and entries:
            entries[-1][2] += " " + line.strip()
            continue
        if "=" not in line:
            ctx.err("subject_definitions", f"line has no '=': '{line.strip()[:60]}'. Write 'name = definition' "
                                           "(indent a line to continue the previous one).")
            continue
        lhs, rhs = (p.strip() for p in line.split("=", 1))
        key = lhs.lstrip("@").lower()
        rhs = re.sub(r"^is\s+", "", rhs)
        if not rhs:
            ctx.err("subject_definitions", f"'{lhs}' has an empty definition.")
            continue
        if re.fullmatch(r"(pic|vid|aud)[1-9]\d*", key):
            if any(e[1] == key for e in entries):
                ctx.err("subject_definitions", f"'@{key}' is defined twice; a label is defined exactly once.")
                continue
            entries.append(["asset", key, rhs])
        elif re.fullmatch(r"[a-z_]\w*", key):
            if key in ctx.subjects:
                ctx.err("subject_definitions", f"subject '{key}' is defined twice; a label is defined exactly once.")
                continue
            ctx.subjects[key] = len(ctx.subjects) + 1
            entries.append(["subject", key, rhs])
        else:
            ctx.err("subject_definitions", f"'{lhs}' is not a valid name (letters, digits, underscore).")

    literal = re.search(r"\(S\d+(?:,S\d+)*\)", "\n".join(raw.values()))

    # ---- pass 2: shots (assigns speaker numbers in order of vocal events) ----
    style_lines, shot_list, cur = [], [], None
    for line in raw["shots"].split("\n"):
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

    if shot_list:
        style = ctx.expand(_one_line(" ".join(style_lines)), "detailed_description", True, True)
        dd_lines = [style] if style else []
        bodies = []
        for i, sh in enumerate(shot_list, 1):
            body = ctx.expand(_one_line(" ".join(sh["lines"])), "detailed_description", True, True)
            bodies.append(body)
            if not body:
                ctx.err("detailed_description", f"shot {i} is empty.")
            if i == 1:
                if sh["t"]:
                    ctx.err("detailed_description", "the first '>>' must not have a time; [Shot 1] has no timestamp.")
                dd_lines.append(f"[Shot 1] {body}")
            else:
                if sh["t"] is None:
                    ctx.err("detailed_description", f"shot {i} needs a cut time, e.g. '>> 3.5 the shot cuts to ...'.")
                    dd_lines.append(f"[Shot {i}] {body}")
                else:
                    dd_lines.append(f"[Shot {i}] At {_fmt_ts(sh['t'])}, {body}")
        detailed = "\n".join(dd_lines)
    else:
        detailed = ctx.expand(raw["shots"].strip(), "detailed_description", True, True)
        bodies = [m for m in _SHOT_RE.split(detailed)[2::2]]
        if "[Shot 1]" not in detailed:
            ctx.err("detailed_description", "no shots found. Start each shot with a '>>' line "
                                            "('>>' for the first, '>> 3.5' for later cuts).")

    if literal and ctx.speakers:
        ctx.err("detailed_description", f"literal speaker ID '{literal.group(0)}' is mixed with auto-numbered "
                                        "speakers ('@name(s)' / '(s:name)'). Use one style only.")

    # ---- pass 3: everything else ----
    def_lines = []
    for kind, key, rhs in entries:
        lab = ctx.label(key, "subject_definitions")
        def_lines.append(f"{lab} is {ctx.expand(_one_line(rhs), 'subject_definitions')}")

    summ = _one_line(raw["summary"])
    if summ.startswith("["):
        ctx.err("summary", "don't type the [task type] prefix; it is generated from the task-type toggles.")
    chosen = [t for t in TASK_TYPES if t in set(task_types)]
    summ_out = f"[{' + '.join(chosen)}] {ctx.expand(summ, 'summary')}"

    ret_lines = []
    ret_re = re.compile(r"^@?(?P<key>[A-Za-z_]\w*)\s*(?:\((?P<paren>.*?)\))?\s*:\s*(?P<marker>[A-Za-z_]+)\s*"
                        r"(?:-|–|—)\s*(?P<note>.+)$")
    for line in raw["retention"].split("\n"):
        s = line.strip()
        if not s:
            continue
        if line[0] in " \t" and ret_lines:
            ret_lines[-1] += " " + ctx.expand(s, "retention_analysis")
            continue
        m = ret_re.match(s)
        if not m:
            ctx.err("retention_analysis", f"can't parse '{s[:60]}'. Format: 'name: full - what is kept' or "
                                          "'@pic2 ([Shot 1] first frame): full - ...'.")
            continue
        lab = ctx.label(m["key"], "retention_analysis")
        if lab is None:
            continue
        is_audio = lab.startswith("<Audio")
        valid = AUDIO_MARKERS if is_audio else VISUAL_MARKERS
        aliases = AUDIO_ALIASES if is_audio else VISUAL_ALIASES
        mk = m["marker"].lower()
        mk = aliases.get(mk, mk)
        if mk not in valid:
            fam = "audio" if is_audio else "visual"
            ctx.err("retention_analysis", f"'{m['marker']}' is not a valid {fam} marker for {lab}. Use one of: "
                    + ", ".join(sorted(set(aliases) | set(valid))) + "." + _suggest(mk, list(aliases) + valid))
            continue
        paren = m["paren"]
        if lab.startswith("<Subject"):
            if paren is None or paren.strip().lower() == "all":
                if paren is None:
                    idx = [i for i, b in enumerate(bodies, 1) if lab in b]
                else:
                    idx = list(range(1, len(bodies) + 1))
                if not idx:
                    ctx.err("retention_analysis", f"{lab} ('{m['key']}') never appears in any shot. Tag it in the "
                                                  "shots with '@" + m["key"] + "', or write '(all)' after its name.")
                paren = "appears in " + ", ".join(f"[Shot {i}]" for i in idx)
        head = lab + (f" ({ctx.expand(paren, 'retention_analysis')})" if paren else "")
        ret_lines.append(f"{head}: {mk} - {ctx.expand(m['note'].strip(), 'retention_analysis')}")

    snd = ctx.expand(_one_line(raw["soundscape"]), "overall_soundscape") or "N/A"
    mus = ctx.expand(_one_line(raw["music"]), "non_diegetic_music") or "N/A"

    text = "\n\n".join([
        "subject_definitions:\n" + "\n".join(def_lines),
        "summary:\n" + summ_out,
        "retention_analysis:\n" + "\n".join(ret_lines),
        "detailed_description:\n" + detailed,
        "overall_soundscape:\n" + snd,
        "non_diegetic_music:\n" + mus,
    ])
    for junk, why in (("{{", "unclosed dialogue '{{'"), ("}}", "stray '}}'"), (">>", "stray '>>' (must start a line)")):
        if junk in text:
            ctx.err("prompt", why + " left in the compiled prompt.")
    return text, ctx.issues


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
