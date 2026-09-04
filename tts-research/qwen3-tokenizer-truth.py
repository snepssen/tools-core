#!/usr/bin/env python
"""Dump the reference tokenizer's output for a battery of strings.

    python qwen3-tokenizer-truth.py --gateway-root PATH

The Qwen text tokenizer is the one component of the port with no tensor to diff
against, so it gets its own ground truth: real library wording, the exact chat
strings ICL builds, and the edge cases byte-level BPE is known to get wrong.

Output is small and **checked in** (`library/reference/qwen3-tokenizer.json`),
unlike the 65 MB tensor dump -- so `gfcheck` can hold the Swift tokenizer to it
on every build, without the model being on disk. The tokenizer needs no MLX, so
it lives in GatewayCore and stays inside the `swift run gfcheck` path.
"""
import argparse, json, pathlib, re, sys
from transformers import AutoTokenizer

REPO = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"
ap = argparse.ArgumentParser()
ap.add_argument("--gateway-root", required=True,
                help="Gateway Forge checkout containing voices/ and library/")
args = ap.parse_args()
root = pathlib.Path(args.gateway_root).resolve()
tok = AutoTokenizer.from_pretrained(REPO)

cases: list[str] = []

def add(*xs):
    for x in xs:
        if x not in cases:
            cases.append(x)

# 1. The chat strings ICL actually builds, verbatim from the reference.
profile = json.loads((root / "voices/M1/profile.json").read_text())
ref_text = profile["referenceText"].strip()
line = ("You are now in Focus 12. A state of awareness far beyond your "
        "physical body.")
add(f"<|im_start|>assistant\n{ref_text}<|im_end|>\n",
    f"<|im_start|>assistant\n{line}<|im_end|>\n<|im_start|>assistant\n",
    ref_text, line)

# 2. Real library wording -- the register and terminology this will actually
#    be asked to speak, including the protected instrument names.
for f in sorted((root / "library/segments").glob("*.gws")):
    for raw in f.read_text().splitlines():
        m = re.match(r"\s*say\s+(.*)", raw)
        if m:
            t = re.sub(r"\{([^{}|]*)(\|[^{}]*)?\}", r"\1", m.group(1)).strip()
            if t:
                add(t)
cases_from_library = len(cases)

# 3. Edge cases. Byte-level BPE fails in specific, boring, repeatable ways, and
#    a tokenizer that is right on prose can still be wrong on every one of
#    these. The em dash and the curly apostrophe are in the library already.
add("", " ", "  ", "\n", "\n\n", " \n ", "\t", "   leading", "trailing   ",
    "a  b", "Focus 10", "Focus 21.", "10", "100", "1234567890",
    "F27", "C15-VOID", "3-D", "0.37 Hz", "99.25/100.75",
    "don't", "isn't", "you're", "we've", "I'll", "we'd", "it's", "Don't",
    "DON'T", "don’t", "you’re",  # curly apostrophe -- different tokens
    "Energy Conversion Box", "Resonant Tuning", "Hemi-Sync",
    "the Park — and beyond", "wider, then narrower, higher, then lower",
    "…", "...", "«»", "café", "naïve", "Zürich", "日本語", "🙂",
    "<|im_start|>", "<|im_end|>", "<|endoftext|>",
    "<|im_start|>assistant", "a<|im_end|>b",
    "ALL CAPS SENTENCE", "MixedCase word", "hyphen-ated",
    "(parenthesis)", "[bracket]", "\"quoted\"", "'single'",
    "one. two. three.", "semi;colon", "colon: here")

out = {"repo": REPO, "tokenizer_class": tok.__class__.__name__,
       "library_cases": cases_from_library, "cases": []}
for text in cases:
    ids = tok.encode(text)
    out["cases"].append({"text": text, "ids": ids,
                         "roundtrip": tok.decode(ids)})

# The two id slices ICL depends on: it strips 3 role tokens from the front and
# a fixed tail. If those offsets are wrong the prefill is silently misaligned,
# so they are recorded as facts rather than left implicit in the Swift.
ref_ids = tok.encode(f"<|im_start|>assistant\n{ref_text}<|im_end|>\n")
tgt_ids = tok.encode(f"<|im_start|>assistant\n{line}<|im_end|>\n<|im_start|>assistant\n")
out["icl"] = {
    "ref_text": ref_text, "target_text": line,
    "ref_ids": ref_ids, "ref_text_ids": ref_ids[3:-2],
    "target_ids": tgt_ids, "text_ids": tgt_ids[3:-5],
    "role_ids": tgt_ids[:3],
}

p = root / "library/reference/qwen3-tokenizer.json"
p.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
print(f"{len(cases)} cases ({cases_from_library} from the library) -> {p}")
print(f"  {p.stat().st_size/1024:.0f} KB")
print(f"  ref_text_ids {len(out['icl']['ref_text_ids'])}, "
      f"text_ids {len(out['icl']['text_ids'])}, role {out['icl']['role_ids']}")
