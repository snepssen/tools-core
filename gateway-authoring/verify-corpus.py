#!/usr/bin/env python3
"""Check every cut clip actually says what its transcript claims.

    verify-corpus.py <corpus-dir> <retranscript-dir> <script.md> [--drop]

The aligner takes its text from the script and its timing from ASR. That is
the right way round -- a mishearing cannot poison the training text -- but it
means a timing error is silent: the clip is labelled with words it does not
contain, and nothing in the cutting stage can notice. So the clips are read
back independently and compared to what they were labelled with.

Word error rate, not string equality. The ASR writes "color" and "judgment"
and turns "twenty" into "20"; those are its spelling, not the reader's
mistakes. What matters is a clip whose words are largely not the ones on it.
"""
import os, re, sys, csv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib.machinery import SourceFileLoader
_ac = SourceFileLoader("_ac", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir,
    "audio-analysis", "align-corpus.py")).load_module()
words_of = _ac.words_of

# Spellings the ASR prefers. Counting these as errors would bury the real ones.
_SAME = {"color": "colour", "judgment": "judgement", "towards": "toward",
         "synchronized": "synchronised", "recognize": "recognise",
         "realize": "realise", "gray": "grey", "ok": "okay",
         "goodnight": "good", "hemisync": "hemi"}

def norm(ws):
    return [_SAME.get(w, w) for w in ws]

def wer(ref, hyp):
    """Levenshtein over words, as a fraction of the reference length."""
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1] / len(ref)

def covers_script(labels, script_md):
    """Every scripted word still present in the labels, in order.

    Splitting and joining move text between clips. Neither should ever lose a
    word or invent one, and this is the only check that would notice if they
    did -- the audio comparison below cannot tell a dropped label from a line
    the reader skipped.
    """
    blocks = _ac.parse_script(script_md)
    want = [w for b in blocks for u in b["utterances"] for w in words_of(u)]
    got = [w for _, t in sorted(labels.items()) for w in words_of(t)]
    if want == got:
        return None
    for i, (a, b) in enumerate(zip(want, got)):
        if a != b:
            return (f"labels diverge from the script at word {i}: "
                    f"script {' '.join(want[i:i+6])!r} vs labels {' '.join(got[i:i+6])!r}")
    return f"labels hold {len(got)} words, script has {len(want)}"


def phonation_seconds(path, rel=0.06):
    """Seconds of actual sound, silence excluded."""
    import wave, struct
    with wave.open(path) as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    s = struct.unpack("<%dh" % (len(raw) // 2), raw)
    n = max(1, int(sr * 0.010))
    frames = [max(abs(v) for v in s[i:i + n]) / 32768.0 for i in range(0, len(s) - n, n)]
    if not frames:
        return 0.0
    peak = max(frames) or 1e-9
    return sum(1 for f in frames if f > rel * peak) * 0.010


def syllables(text):
    return sum(max(1, sum(1 for ch in w.lower() if ch in "aeiouy")) for w in text.split())


def duration_outliers(corpus, labels, factor=1.9):
    """Clips holding more speech than their words can account for.

    **The word-error comparison is blind to a disfluency.** ASR normalises a
    stutter away -- "y-you" transcribes as "you" -- so a clip carrying a
    repeated onset passes with a perfect WER and a matching word count, which
    is exactly the shape of defect that teaches a voice to stutter.

    Duration is not blind to it. A repetition is roughly a syllable of extra
    sound with no extra text, so it shows as an unusually slow clip. Compared
    against the corpus's own median rather than an absolute figure, because
    a reading has whatever pace it has.
    """
    import os
    rows = []
    for cid, text in labels.items():
        path = os.path.join(corpus, "clips", cid + ".wav")
        if not os.path.exists(path):
            continue
        n = syllables(text)
        if n < 4:
            continue
        seconds = phonation_seconds(path)
        if seconds < 0.4:
            continue
        rows.append((seconds / n, cid, text))
    if not rows:
        return 0, []
    rows.sort()
    median = rows[len(rows) // 2][0]
    return median, [r for r in rows if r[0] > median * factor]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    drop = "--drop" in sys.argv
    if len(args) != 3:
        raise SystemExit(__doc__)
    corpus, heard, script_md = args
    def read_metadata(path):
        out = {}
        if not os.path.exists(path):
            return out
        for line in open(path, encoding="utf-8"):
            f = line.rstrip("\n").split("|")
            if len(f) >= 2:
                out[f[0]] = f[1]
        return out

    labels = read_metadata(os.path.join(corpus, "metadata.csv"))
    # Held-back clips keep their text here. Without it the coverage invariant
    # reports every intentional drop as the script diverging, which is a false
    # alarm loud enough to stop anyone reading the real ones.
    held = read_metadata(os.path.join(corpus, "held-back", "metadata.csv"))
    rows, missing = [], []
    for cid, text in sorted(labels.items()):
        p = os.path.join(heard, cid + ".txt")
        if not os.path.exists(p):
            missing.append(cid); continue
        got = open(p, encoding="utf-8").read()
        rows.append((cid, wer(norm(words_of(text)), norm(words_of(got))), text, got))
    if not rows:
        raise SystemExit("nothing to compare")
    problem = covers_script({**labels, **held}, script_md)
    print("script coverage:", problem or "labels reproduce the script exactly")
    rows.sort(key=lambda r: -r[1])
    n = len(rows)
    clean = sum(1 for r in rows if r[1] == 0)
    ok = sum(1 for r in rows if r[1] <= 0.05)
    bad = [r for r in rows if r[1] > 0.20]
    total = sum(r[1] for r in rows) / n
    print(f"compared {n} clips" + (f" ({len(missing)} not transcribed)" if missing else ""))
    print(f"  word-perfect      {clean:4d}  ({100*clean/n:.1f}%)")
    print(f"  within 5% WER     {ok:4d}  ({100*ok/n:.1f}%)")
    print(f"  over 20% WER      {len(bad):4d}  ({100*len(bad)/n:.1f}%)")
    print(f"  mean WER          {total:.4f}")
    # **Length disagreement is the signal, not WER.** A high WER on the
    # phonetic drills is the ASR failing at "sixths" and "twelfths", which is
    # what those blocks are for. A clip that *contains* words its label does
    # not -- a stumble, a repeat, a boundary that leaked into the neighbour --
    # teaches the voice to say them, and no amount of correct substitution
    # elsewhere makes up for it.
    suspect = []
    for cid, w, text, got in rows:
        d = len(norm(words_of(got))) - len(norm(words_of(text)))
        if abs(d) >= 2:
            suspect.append((cid, d, w, text, ' '.join(got.split())))
    print(f"\nlength mismatches (clip holds more or less than its label): {len(suspect)}")
    for cid, d, w, text, got in suspect:
        print(f"  {cid}  {d:+d} words, WER {w:.2f}")
        print(f"    labelled: {text[:104]}")
        print(f"    heard:    {got[:104]}")
    for cid, w, text, got in rows[:8]:
        if w == 0:
            break
        if any(cid == s0[0] for s0 in suspect):
            continue
        print(f"\n  {cid}  WER {w:.2f}")
        print(f"    labelled: {text[:110]}")
        print(f"    heard:    {' '.join(got.split())[:110]}")

    median, slow = duration_outliers(corpus, labels)
    print(f"\nspeech per syllable: median {median*1000:.0f} ms")
    print(f"  clips holding more sound than their words account for: {len(slow)}")
    for rate, cid, text in slow[:8]:
        print(f"    {cid}  {rate*1000:.0f} ms/syll ({rate/median:.2f}x)  {text[:60]}")

    if drop and suspect:
        # Set aside rather than delete. A clip whose transcript and audio
        # disagree is not garbage -- it is evidence about the read, and the
        # next pass may want to look at what the reader actually did there.
        held = os.path.join(corpus, "held-back")
        os.makedirs(held, exist_ok=True)
        ids = {c for c, *_ in suspect}
        for cid in ids:
            src = os.path.join(corpus, "clips", cid + ".wav")
            if os.path.exists(src):
                os.replace(src, os.path.join(held, cid + ".wav"))
        rows = list(open(os.path.join(corpus, "metadata.csv"), encoding="utf-8"))
        keep = [l for l in rows if l.split("|")[0] not in ids]
        gone = [l for l in rows if l.split("|")[0] in ids]
        open(os.path.join(corpus, "metadata.csv"), "w", encoding="utf-8").writelines(keep)
        # Their text moves with them, so coverage still has something to check.
        with open(os.path.join(held, "metadata.csv"), "a", encoding="utf-8") as f:
            f.writelines(gone)
        man = os.path.join(corpus, "manifest.tsv")
        out = []
        for l in open(man, encoding="utf-8"):
            f = l.rstrip("\n").split("\t")
            if f[0] in ids:
                f[2], f[3] = "held", "audio and label disagree in length"
            out.append("\t".join(f))
        open(man, "w", encoding="utf-8").write("\n".join(out) + "\n")
        print(f"\nheld back {len(ids)} clips into {held}/")

if __name__ == "__main__":
    main()
