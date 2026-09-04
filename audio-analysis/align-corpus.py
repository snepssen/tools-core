#!/usr/bin/env python3
"""Cut a single continuous corpus read into training clips.

    align-corpus.py <audio.wav> <words.json> <script.md> <out-dir> [--dry-run]

The reader reads the supplied script Markdown start to finish in one take.
That is the *right* way to record it -- one session, one mic position, one
voice -- and it leaves exactly one problem: 6,777 words of known text and a
67-minute wav with no marks in it.

Splitting by hand is the tempting shortcut and it is the one that broke the
first voice: hand-placed cuts land tight against the last word, the model
learns that utterances end abruptly, and it renders a severed breath. So the
boundaries here are never chosen by eye. ASR supplies word times, the *script*
supplies the words -- the transcript is only ever used for timing, never for
text -- and each cut is then pushed outward into the quietest point of the gap
it sits in.

Alignment is banded Needleman-Wunsch. Both streams are the same passage in the
same order, so the path never strays far from the diagonal; a band keeps it to
seconds rather than the full 47M-cell quadratic.
"""
import json, re, sys, os, struct, wave, subprocess, math

# ---------------------------------------------------------------- the script

def parse_script(path):
    """Blocks of the reading script, each split into utterances.

    An utterance is a sentence, except that short ones are joined until they
    reach `MIN_WORDS`. Block 2 is "One. Two. Three." -- as clips those are
    sub-second fragments with no prosodic context, and a voice trained on them
    learns to say numbers as isolated events rather than as a count.
    """
    MIN_WORDS, MAX_WORDS = 6, 40
    blocks, cur = [], None
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^## Block (\d+) — (.+)$", line.rstrip("\n"))
        if m:
            cur = {"no": int(m.group(1)), "title": m.group(2).strip(), "text": ""}
            blocks.append(cur)
        elif cur is not None:
            cur["text"] += line
    for b in blocks:
        text = " ".join(b["text"].split())
        # Sentence ends: . ! ? not followed by a digit (so "3.5" survives).
        parts, buf = [], ""
        for i, ch in enumerate(text):
            buf += ch
            if ch in ".!?":
                nxt = text[i + 1] if i + 1 < len(text) else " "
                nxt2 = text[i + 2] if i + 2 < len(text) else " "
                if nxt == " " and not nxt2.isdigit():
                    parts.append(buf.strip()); buf = ""
        if buf.strip():
            parts.append(buf.strip())
        merged = []
        for p in parts:
            if merged and (len(words_of(merged[-1])) < MIN_WORDS
                           and len(words_of(merged[-1])) + len(words_of(p)) <= MAX_WORDS):
                merged[-1] = merged[-1] + " " + p
            else:
                merged.append(p)
        b["utterances"] = merged
    return blocks

# ------------------------------------------------------------ normalisation

_ONES = ["zero","one","two","three","four","five","six","seven","eight","nine",
         "ten","eleven","twelve","thirteen","fourteen","fifteen","sixteen",
         "seventeen","eighteen","nineteen"]
_TENS = ["","","twenty","thirty","forty","fifty","sixty","seventy","eighty","ninety"]

def _spell(n):
    """A number as the reader would say it.

    The ASR writes numerals -- "20", "1997" -- where the script writes words,
    and a naive digit-by-digit expansion turns "twenty" into "two zero", which
    is two mismatches on the most frequent vocabulary in the whole corpus. The
    app counts constantly; getting this wrong is not cosmetic.
    """
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        return [_TENS[n // 10]] + ([_ONES[n % 10]] if n % 10 else [])
    if n < 1000:
        return [_ONES[n // 100], "hundred"] + (_spell(n % 100) if n % 100 else [])
    if 1100 <= n < 2000 and n % 100:            # years: "nineteen ninety seven"
        return _spell(n // 100) + _spell(n % 100)
    return _spell(n // 1000) + ["thousand"] + (_spell(n % 1000) if n % 1000 else [])

def words_of(text):
    """Comparison tokens. Hyphens split, numerals spelled, everything else dropped.

    "Twenty-One" and the ASR's "twenty one" have to become the same two
    tokens or every Focus level name costs the alignment two mismatches.
    """
    out = []
    for raw in re.split(r"[^A-Za-z0-9']+", text.lower()):
        if not raw:
            continue
        if raw.isdigit():
            out += _spell(int(raw)) if len(raw) <= 4 else [_ONES[int(c)] for c in raw]
        else:
            out.append(raw.strip("'"))
    return [w for w in out if w]

# --------------------------------------------------------------- alignment

def align(a, b, band=400):
    """Banded global alignment. Returns b-index for each a-index, or None.

    Match +2, mismatch -1, gap -1: mismatch has to beat two gaps, or the ASR
    hearing "surface you" for "surface beneath you" opens a hole instead of
    charging one substitution.
    """
    n, m = len(a), len(b)
    NEG = float("-inf")
    prev = {}
    # column 0
    for j in range(0, min(band, m) + 1):
        prev[j] = -j
    ptr = []
    for i in range(1, n + 1):
        lo = max(0, int(i * m / n) - band)
        hi = min(m, int(i * m / n) + band)
        cur, row = {}, {}
        for j in range(lo, hi + 1):
            best, how = NEG, None
            if j - 1 in prev:                              # diagonal
                s = prev[j - 1] + (2 if a[i - 1] == b[j - 1] else -1)
                best, how = s, "d"
            if j in prev and prev[j] - 1 > best:           # gap in b
                best, how = prev[j] - 1, "u"
            if j - 1 in cur and cur[j - 1] - 1 > best:     # gap in a
                best, how = cur[j - 1] - 1, "l"
            if how is None:
                continue
            cur[j], row[j] = best, how
        if not cur:
            raise SystemExit(f"alignment fell out of the band at word {i}")
        prev, _ = cur, ptr.append(row)
    # trace back from the best end cell
    j = max(prev, key=lambda k: prev[k])
    i = n
    out = [None] * n
    while i > 0:
        how = ptr[i - 1].get(j)
        if how == "d":
            out[i - 1] = j - 1; i -= 1; j -= 1
        elif how == "u":
            i -= 1
        elif how == "l":
            j -= 1
        else:
            break
    return out

# ------------------------------------------------------------------- audio

def envelope(path, hop_ms=10):
    """Per-hop RMS in dB, via ffmpeg. Cheap enough to run over the whole file."""
    rate = probe_rate(path)
    n = int(rate * hop_ms / 1000)
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-af",
           f"aformat=channel_layouts=mono,asetnsamples=n={n}:p=0,"
           f"astats=metadata=1:reset=1,ametadata=print:"
           f"key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    v = []
    for line in out.splitlines():
        m = re.search(r"RMS_level=(-?[\d.]+|-inf)", line)
        if m:
            v.append(-120.0 if m.group(1) == "-inf" else float(m.group(1)))
    return v, hop_ms

def probe_rate(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                          "-show_entries", "stream=sample_rate", "-of",
                          "csv=p=0", path], capture_output=True, text=True).stdout
    return int(out.strip())

def quietest(env, hop_ms, lo_ms, hi_ms):
    """Time of the quietest hop in a window, in ms. None if the window is empty."""
    lo, hi = int(lo_ms / hop_ms), int(hi_ms / hop_ms)
    lo, hi = max(0, lo), min(len(env) - 1, hi)
    if hi <= lo:
        return None
    k = min(range(lo, hi + 1), key=lambda x: env[x])
    return k * hop_ms


def edges(env, hop_ms, thresh, s_ms, e_ms, search=600):
    """The true first and last hop of phonation near an ASR-derived span.

    **ASR word times are anchors, not boundaries.** Parakeet reports on a
    40ms grid and lets each word's end run up to the next word's start, so the
    median gap between one utterance's last word and the next's first came out
    at zero -- there is no gap there to search for a quiet point in. Cutting on
    those numbers puts the knife inside the following breath.

    So the times only say *roughly where to look*; the envelope says where the
    speech actually is.
    """
    n = len(env)
    def hop(ms): return max(0, min(n - 1, int(ms / hop_ms)))
    i0, i1 = hop(s_ms), hop(e_ms)
    span = int(search / hop_ms)
    # First hop above threshold at or after the anchor, else search backwards.
    start = next((i for i in range(i0, min(n, i1 + 1)) if env[i] > thresh), None)
    if start is None:
        start = next((i for i in range(i0, max(-1, i0 - span), -1) if env[i] > thresh), i0)
    else:
        back = next((i for i in range(start, max(-1, start - span), -1)
                     if env[i] <= thresh), None)
        if back is not None:
            start = back + 1
    # Last hop above threshold at or before the anchor, else search forwards.
    end = next((i for i in range(i1, start - 1, -1) if env[i] > thresh), None)
    if end is None:
        end = next((i for i in range(i1, min(n, i1 + span)) if env[i] > thresh), i1)
    else:
        fwd = next((i for i in range(end, min(n, end + span)) if env[i] <= thresh), None)
        if fwd is not None:
            end = fwd - 1
    return start * hop_ms, (end + 1) * hop_ms

def chunks_of(utt):
    """An utterance broken at its own punctuation, with each piece's word count.

    Split points for an over-long clip have to be places the reader actually
    paused, and the script already marks those with commas and full stops.
    Splitting anywhere else puts a boundary mid-clause, which is a worse thing
    to teach a voice than a long clip.
    """
    parts, buf = [], ""
    for ch in utt:
        buf += ch
        if ch in ",;:.!?":
            parts.append(buf); buf = ""
    if buf.strip():
        parts.append(buf)
    out = []
    for p in parts:
        n = len(words_of(p))
        if n == 0 and out:                       # stray punctuation
            out[-1] = (out[-1][0] + p, out[-1][1])
        elif n:
            out.append((p.strip(), n))
    return out


def split_long(utt, times, env, hop, max_ms, thresh, depth=0):
    """Break an utterance that ran too long, at the deepest pause it contains.

    `times` is one (start, end) per word of `utt`. VITS trains on whole
    utterances, so a 27-second clip costs memory quadratically and contributes
    one training example for the price of five. But splitting is only allowed
    where the reader left a real silence at a real clause boundary -- if no
    candidate has one, the long clip is kept rather than cut somewhere the
    voice would learn to breathe wrongly.
    """
    s_ms, e_ms = times[0][0], times[-1][1]
    if e_ms - s_ms <= max_ms or depth > 3:
        return [(utt, times)]
    cs = chunks_of(utt)
    if len(cs) < 2:
        return [(utt, times)]
    total = sum(n for _, n in cs)
    if total != len(times):
        return [(utt, times)]
    # A candidate needs a real silence, not merely the quietest point available.
    # Splitting at the least-loud moment of an unbroken clause gives the first
    # half no tail at all -- and a clip that ends mid-phonation is the severed
    # breath, which is a worse fault than a long clip.
    MIN_SILENCE = 200
    best, off = None, 0
    for k, (_, n) in enumerate(cs[:-1]):
        off += n
        if not 0.2 < off / total < 0.8:
            continue
        mid = (times[off - 1][1] + times[off][0]) / 2
        lo = max(0, int((mid - 250) / hop)); hi = min(len(env), int((mid + 250) / hop) + 1)
        win = env[lo:hi]
        if not win:
            continue
        run = best_run = 0
        for v in win:
            run = run + 1 if v <= thresh else 0
            best_run = max(best_run, run)
        if best_run * hop < MIN_SILENCE:
            continue
        q = min(win)
        if best is None or q < best[0]:
            best = (q, off, k)
    if best is None:
        return [(utt, times)]
    _, off, k = best
    left = " ".join(t for t, _ in cs[:k + 1]).strip()
    right = " ".join(t for t, _ in cs[k + 1:]).strip()
    return (split_long(left, times[:off], env, hop, max_ms, thresh, depth + 1)
            + split_long(right, times[off:], env, hop, max_ms, thresh, depth + 1))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    if len(args) != 4:
        raise SystemExit(__doc__)
    audio, wordsjson, script_md, outdir = args
    blocks = parse_script(script_md)

    stream, owner = [], []
    for b in blocks:
        for ui, utt in enumerate(b["utterances"]):
            for w in words_of(utt):
                stream.append(w); owner.append((b["no"], ui))

    asr = [w for s in json.load(open(wordsjson))["segments"] for w in s.get("words", [])]
    # An ASR "word" can normalise to several tokens ("1997"); expand so the two
    # index spaces line up, splitting the interval evenly between them.
    hw, ht = [], []
    for w in asr:
        toks = words_of(w["text"])
        if not toks:
            continue
        span = (w["end"] - w["start"]) / len(toks)
        for k, t in enumerate(toks):
            hw.append(t); ht.append((w["start"] + k * span, w["start"] + (k + 1) * span))

    print(f"script {len(stream)} words, heard {len(hw)} words")
    path = align(stream, hw)
    matched = sum(1 for i, j in enumerate(path) if j is not None and stream[i] == hw[j])
    print(f"aligned {matched}/{len(stream)} exactly ({100*matched/len(stream):.1f}%)")

    env, hop = envelope(audio)
    dur_ms = len(env) * hop
    ranked = sorted(env)
    floor = ranked[len(ranked) // 20]
    # Speech threshold. Well above the floor so a breath does not read as a
    # word, well below the median so a soft consonant still does.
    thresh = floor + 14
    print(f"envelope {len(env)} hops of {hop}ms = {dur_ms/60000:.1f} min, "
          f"floor {floor:.1f} dB, speech threshold {thresh:.1f} dB")

    # Per-word times, carried through so a long utterance can be split later.
    items = []
    for b in blocks:
        for ui, utt in enumerate(b["utterances"]):
            idx = [i for i, o in enumerate(owner) if o == (b["no"], ui)]
            times, last = [], None
            for i in idx:
                j = path[i]
                times.append(ht[j] if j is not None else None)
                if j is not None:
                    last = ht[j]
            # A word the ASR never matched still has to carry a time, or the
            # utterance it belongs to is lost. "Goodnight" against a heard
            # "good night" is not a reason to drop the last line of the corpus.
            fwd = None
            for k in range(len(times) - 1, -1, -1):
                if times[k] is None:
                    times[k] = fwd
                else:
                    fwd = times[k]
            back = None
            for k in range(len(times)):
                if times[k] is None:
                    times[k] = back
                else:
                    back = times[k]
            items.append((b, ui, utt, times))

    # Neighbours lend a time to any utterance that matched nothing at all.
    for k, (b, ui, utt, times) in enumerate(items):
        if all(t is None for t in times):
            prev = next((items[x][3][-1] for x in range(k - 1, -1, -1)
                         if items[x][3][-1]), (0, 0))
            nxt = next((items[x][3][0] for x in range(k + 1, len(items))
                        if items[x][3][0]), (dur_ms, dur_ms))
            items[k] = (b, ui, utt, [(prev[1], nxt[0])] * len(times))

    MAX_MS = 13000
    pieces = []
    for b, ui, utt, times in items:
        for part, ts in split_long(utt, times, env, hop, MAX_MS, thresh):
            pieces.append((b, ui, part, ts[0][0], ts[-1][1]))
    splits = len(pieces) - len(items)

    # **The two ends are not symmetric, and that asymmetry is the point.**
    # A clip that ends tight against its last word teaches the model that
    # phonation stops dead, and it renders a severed breath -- the defect that
    # sank the first voice. So the tail keeps the decay, out to 700ms. The head
    # is trimmed close: leading silence is not harmless padding, it is training
    # data, and a model fed it learns to open every utterance with a pause.
    HEAD_PAD, TAIL_MIN, TAIL_MAX = 120, 120, 700
    # Resolve every piece to real phonation first. Neighbour clamps have to be
    # against *these*, not against the ASR times: an ASR word end runs up to
    # the next word's start, so clamping to it puts the head of the next clip
    # exactly on the onset it was supposed to leave room before.
    true = [list(edges(env, hop, thresh, s_ms, e_ms)) for _, _, _, s_ms, e_ms in pieces]
    # `edges` searches 600ms either side of its anchor, so two neighbours can
    # both claim the same sound. Hand it to whichever one it belongs to by
    # cutting at the quietest hop between their anchors -- an overlap left in
    # place makes one clip end inside a word and the next begin inside it.
    for k in range(len(true) - 1):
        if true[k][1] > true[k + 1][0]:
            mid = quietest(env, hop, pieces[k][4] - 200, pieces[k + 1][3] + 200)
            if mid is None:
                mid = (true[k][1] + true[k + 1][0]) / 2
            true[k][1] = min(true[k][1], mid)
            true[k + 1][0] = max(true[k + 1][0], mid)
    # Where the reader ran two sentences together there is no boundary to find,
    # and forcing one leaves the first clip ending mid-phonation and the second
    # opening on a consonant already in progress. Both are training data. Join
    # them instead: the text is adjacent in the script, so the joined pair is
    # still an exact transcript of what was said.
    MIN_GAP, MERGE_CAP = 120, 20000
    merged, joined = [], 0
    for k, (b, ui, utt, s_ms, e_ms) in enumerate(pieces):
        if merged:
            pb, pui, putt, ps, pe = merged[-1]
            lo, hi = int(pe / hop), int(true[k][0] / hop)
            run = 0
            for v in env[max(0, lo):max(0, hi) + 1]:
                if v <= thresh:
                    run += hop
                else:
                    run = 0
                if run >= MIN_GAP:
                    break
            # Block boundaries are joined too. A block break is where the
            # reader is *most* likely to have paused, so when the envelope says
            # they did not, they genuinely read straight on -- and the join is
            # attributed to the first block, which is bookkeeping, not
            # training input.
            if run < MIN_GAP and true[k][1] - ps <= MERGE_CAP:
                merged[-1] = (pb, pui, (putt + " " + utt).strip(), ps, true[k][1])
                joined += 1
                continue
        merged.append((b, ui, utt, true[k][0], true[k][1]))
    if joined:
        print(f"joined {joined} clip pairs the reader never paused between")
    pieces = [(b, ui, utt, s, e) for b, ui, utt, s, e in merged]
    true = [[s, e] for _, _, _, s, e in merged]

    cuts = []
    for k, (b, ui, utt, _, _) in enumerate(pieces):
        s_true, e_true = true[k]
        prev_e = true[k - 1][1] if k else 0
        next_s = true[k + 1][0] if k + 1 < len(pieces) else dur_ms
        # Always leave *some* room before the onset. A clip that opens on the
        # burst of a /t/ with nothing in front of it teaches the model to start
        # from a standing start; 40ms of the neighbour's tail overlapping into
        # this clip costs nothing, because they are separate files.
        lo = max(0, min(prev_e, s_true - 40), s_true - HEAD_PAD)
        hi = quietest(env, hop, min(next_s, e_true + TAIL_MIN),
                      min(next_s, e_true + TAIL_MAX))
        if hi is None or hi < e_true:
            hi = max(e_true, min(next_s, e_true + TAIL_MIN))
        cuts.append((b, ui, utt, min(lo, s_true), min(dur_ms, hi)))

    os.makedirs(os.path.join(outdir, "clips"), exist_ok=True)
    meta, man = [], ["id\tblock\tstatus\tdetail\tseconds"]
    kept = dropped = 0
    # Number the halves of a split utterance from 'a', both of them. Suffixing
    # only the second makes "40-004" and "40-004b" look like a whole clip and a
    # stray, when they are two halves of one line.
    parts = {}
    for b, ui, *_ in cuts:
        parts[(b["no"], ui)] = parts.get((b["no"], ui), 0) + 1
    seen = {}
    for b, ui, utt, s_ms, e_ms in cuts:
        key = (b["no"], ui)
        n = seen.get(key, 0); seen[key] = n + 1
        cid = f"{b['no']:02d}-{ui:03d}" + (chr(ord('a') + n) if parts[key] > 1 else "")
        if e_ms - s_ms < 400:
            man.append(f"{cid}\t{b['no']}\tdropped\ttoo short\t"); dropped += 1; continue
        if not dry:
            # -ss before -i: input seeking. With PCM this is both exact and
            # instant; output seeking decodes the whole 67 minutes each time,
            # which turns 600 cuts into an afternoon.
            subprocess.run(["ffmpeg", "-v", "error", "-y",
                            "-ss", f"{s_ms/1000:.3f}", "-t", f"{(e_ms-s_ms)/1000:.3f}",
                            "-i", audio,
                            # Homebrew's ffmpeg has no soxr, so swr is asked for
                            # its good settings explicitly rather than left on
                            # defaults: a 22.05k training corpus is resampled
                            # once and lives with the result.
                            # One global -1 dB, not per-clip normalisation.
                            # The read touches 0 dBFS in 81 samples and a
                            # resampler makes intersample overs out of those;
                            # levelling each clip separately would instead flatten
                            # the difference between a firm line and a soft one,
                            # which is exactly the dynamic the voice is for.
                            "-af", "highpass=f=55:p=2,volume=-1dB,aresample=22050:"
                                   "filter_size=256:phase_shift=10:cutoff=0.91:"
                                   "dither_method=triangular_hp",
                            "-ac", "1", "-c:a", "pcm_s16le",
                            os.path.join(outdir, "clips", f"{cid}.wav")], check=True)
        meta.append(f"{cid}|{utt}|{utt}")
        man.append(f"{cid}\t{b['no']}\tkept\t\t{(e_ms-s_ms)/1000:.2f}")
        kept += 1
    open(os.path.join(outdir, "metadata.csv"), "w", encoding="utf-8").write("\n".join(meta) + "\n")
    open(os.path.join(outdir, "manifest.tsv"), "w", encoding="utf-8").write("\n".join(man) + "\n")
    lens = sorted(float(l.split("\t")[4]) for l in man[1:] if l.split("\t")[2] == "kept")
    total = sum(lens)
    print(f"split {splits} over-long utterances")
    print(f"kept {kept}, dropped {dropped}, {total/60:.1f} min of clips "
          f"({100*total*1000/dur_ms:.0f}% of the read)")
    if lens:
        print(f"clip seconds: min {lens[0]:.2f}  p10 {lens[len(lens)//10]:.2f}  "
              f"med {lens[len(lens)//2]:.2f}  p90 {lens[len(lens)*9//10]:.2f}  max {lens[-1]:.2f}")
    for l in man[1:]:
        f = l.split("\t")
        if f[2] == "dropped":
            print(f"  dropped {f[0]}: {f[3]}")


if __name__ == "__main__":
    main()
