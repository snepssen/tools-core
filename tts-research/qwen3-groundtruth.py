#!/usr/bin/env python
"""Dump numeric ground truth from the working Python MLX Qwen3-TTS path.

    python qwen3-groundtruth.py --gateway-root PATH [--voice M1] [--steps 8]

This exists because the last TTS port was validated by ear and shipped a broken
library. Generated tokens were given restarting position ids; the model spoke
for a few seconds then emitted silence forever, and "does it sound about right"
never caught it. A tensor diff would have, in the first hour.

So: run the reference implementation, record what every stage actually produced,
and write it where `gfcheck` can hold the Swift port to it. Nothing here
reimplements the pipeline -- it wraps the real calls and records their real
arguments and results, so the dump cannot drift from the thing it documents.

Determinism matters more than realism here. The run is seeded, and the sampled
token sequence is dumped alongside the tensors, so the Swift port can be
*teacher-forced* with the same tokens and diffed stage by stage. Sampling
divergence is then not one of the variables.

Output: library/reference/qwen3-groundtruth/  (gitignored; tens of MB)
"""
import argparse, json, sys, time, pathlib
import numpy as np
import mlx.core as mx

REPO = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"
# A real library line, not a lorem ipsum: the port has to survive the register
# and the terminology it will actually be asked to speak.
LINE = ("You are now in Focus 12. A state of awareness far beyond your "
        "physical body.")

ap = argparse.ArgumentParser()
ap.add_argument("--gateway-root", required=True,
                help="Gateway Forge checkout containing voices/ and library/")
ap.add_argument("--voice", default="M1")
ap.add_argument("--steps", type=int, default=8,
                help="how many generation steps to record in full")
ap.add_argument("--max-tokens", type=int, default=400)
ap.add_argument("--seed", type=int, default=1729)
ap.add_argument("--text", default=LINE)
ap.add_argument("--out", default="library/reference/qwen3-groundtruth")
ap.add_argument("--max-elements", type=int, default=1_200_000,
                help="cap per tensor; larger rank-3 tensors are sliced along time")
args = ap.parse_args()

root = pathlib.Path(args.gateway_root).resolve()
out = root / args.out
out.mkdir(parents=True, exist_ok=True)

voice_dir = root / "voices" / args.voice
profile = json.loads((voice_dir / "profile.json").read_text())
ref_text = profile.get("referenceText", "").strip()
if not ref_text:
    sys.exit(f"voice {args.voice} has no referenceText -- transcribe it first "
             f"(mw transcribe --model parakeet-pro:nvidia_parakeet-v3)")
ref_wav = voice_dir / profile.get("referenceWav", "reference.wav")

# ---------------------------------------------------------------- recording
rec = {}          # name -> np.ndarray
meta = {}         # name -> description, so the dump explains itself

def put(name, arr, note=""):
    """Record one tensor. bf16 is widened to f32 on the way out -- numpy cannot
    view a bfloat16 buffer, and the Swift side will be compared in f32 anyway."""
    if arr is None:
        return
    # Some reference calls return a tuple (audio, lengths); record the array
    # part rather than failing, and say so in the note.
    if isinstance(arr, (tuple, list)):
        arr = next((x for x in arr if isinstance(x, mx.array)), None)
        if arr is None:
            return
    if isinstance(arr, mx.array):
        src = str(arr.dtype).replace("mlx.core.", "")
        if arr.dtype in (mx.bfloat16, mx.float16):
            arr = arr.astype(mx.float32)
        a = np.array(arr)
    else:
        a = np.asarray(arr)
        src = str(a.dtype)
    # The decoder's late stages are 518400 x 96 -- 199 MB each, and there are
    # several. Record a time-prefix instead of the whole thing: a convolution
    # stack is diffed just as well on its first frames, and those are the ones
    # carrying the causal-padding edge where the mistakes actually live. The
    # full shape is recorded alongside so nothing silently looks complete.
    full = list(a.shape)
    if a.size > args.max_elements and a.ndim == 3:
        keep = max(1, args.max_elements // max(1, a.shape[0] * a.shape[2]))
        if keep < a.shape[1]:
            a = a[:, :keep, :]
    rec[name] = a
    meta[name] = {"shape": list(a.shape), "dtype": str(a.dtype),
                  "source_dtype": src, "note": note}
    if list(a.shape) != full:
        meta[name]["full_shape"] = full
        meta[name]["note"] = note + f" (first {a.shape[1]} of {full[1]} frames)"

def wrap(obj, attr, name, note, on_call=None, limit=None):
    """Record a method's output without changing what it does.

    Dunder methods are patched on the *type*, not the instance: Python looks
    `__call__` up on the class, so an instance attribute is simply ignored --
    the taps on the talker and the code predictor silently recorded nothing
    until this was fixed, which is its own small lesson about assuming a hook
    fired because the run succeeded."""
    dunder = attr.startswith("__") and attr.endswith("__")
    target = type(obj) if dunder else obj
    orig = getattr(target, attr)
    state = {"n": 0}
    def inner(*a, **k):
        r = orig(*a, **k)
        # Patching a dunder means patching the *class*, and classes like
        # CausalConv1d have dozens of live instances. Record only the one we
        # were pointed at, or every conv in the decoder writes over the tap.
        if dunder and a and a[0] is not obj:
            return r
        i = state["n"]; state["n"] += 1
        if limit is None or i < limit:
            (on_call or (lambda idx, args_, kwargs_, res: put(
                f"{name}" if limit is None else f"{name}.{idx:03d}", res, note)))(i, a, k, r)
        return r
    setattr(target, attr, inner)
    return state

# ------------------------------------------------------------------- load
print(f"loading {REPO} …", flush=True)
t0 = time.time()
from mlx_audio.tts.utils import load
from mlx_audio.utils import load_audio
model = load(REPO)
print(f"loaded in {time.time()-t0:.1f}s", flush=True)

cfg = model.config.talker_config
put("config.probe", np.array([cfg.hidden_size, cfg.num_hidden_layers,
                              cfg.num_attention_heads, cfg.num_key_value_heads,
                              cfg.head_dim, cfg.intermediate_size,
                              cfg.vocab_size, cfg.text_vocab_size,
                              cfg.num_code_groups], dtype=np.int32),
    "hidden, layers, heads, kv_heads, head_dim, ffn, codec_vocab, text_vocab, code_groups")

# The mrope table is pure arithmetic and the single likeliest thing to get
# wrong silently, so it is dumped standalone for a direct comparison before any
# weight is loaded on the Swift side.
rot = model.talker.model.rotary_emb if hasattr(model.talker, "model") else model.talker.rotary_emb
pos = mx.arange(0, 64)[None, :].astype(mx.int32)
pos3 = mx.stack([pos, pos, pos], axis=0)
cos, sin = rot(mx.zeros((1, 64, cfg.hidden_size), dtype=mx.float32), pos3)
put("mrope.cos", cos, "cos for positions 0..63, [1,64,head_dim], interleaved mrope [24,20,20]")
put("mrope.sin", sin, "sin for positions 0..63")
put("mrope.inv_freq", rot._inv_freq, "1/(theta^(2i/d)), theta=1e6")

# --------------------------------------------------------------- wire taps
sampled_first, sampled_code = [], []

def tap_sample(idx, a, k, r):
    # _sample_token is called once per step for codebook 0, then 15 more times
    # for the code predictor. Record every one, in order.
    v = int(np.array(r).reshape(-1)[0])
    (sampled_first if idx % 16 == 0 else sampled_code).append(v)

wrap(model.speech_tokenizer, "encode", "codec.ref_codes",
     "speech tokenizer encoder: reference wav -> [1,16,T] codes")

def tap_decode(i, a, k, r):
    # a[0] is the codes actually handed to the decoder -- the reference codes
    # and the generated ones concatenated. Recording the decoder's real input
    # avoids reconstructing it from the sampled tokens and getting the
    # concatenation subtly wrong.
    put(f"codec.decode_in.{i:02d}", a[0], "codes passed to the decoder, [1,16,T]")
    put(f"codec.decode_out.{i:02d}", r, "waveform the decoder returned")
wrap(model.speech_tokenizer, "decode", "codec.decode", "", on_call=tap_decode, limit=4)

# The decoder is the largest single component of the port, so tap its internal
# boundaries too. Diffing 1200 lines of Swift against one end-to-end waveform
# would mean bisecting by hand when it disagrees; these turn it into a sequence
# of small, individually falsifiable steps.
# The encoder's four stages: SEANet conv stack -> transformer -> downsample ->
# RVQ *encode* (nearest-neighbour codebook search, not a lookup). Tapped for the
# same reason the decoder's were -- so the port is a sequence of small
# falsifiable steps rather than one 1200-line leap at a waveform.
_enc = getattr(model.speech_tokenizer, "encoder_model", None)
if _enc is not None:
    _emods = dict(_enc.named_modules())
    for _name in ("encoder", "encoder_transformer", "downsample"):
        if _name in _emods:
            wrap(_emods[_name], "__call__", f"enc.{_name}",
                 f"encoder stage: {type(_emods[_name]).__name__}", limit=1)
    if "quantizer" in _emods:
        wrap(_emods["quantizer"], "encode", "enc.quantizer",
             "RVQ encode: latent -> [1,32,T] codes, trimmed to 16", limit=1)

# The decoder is wrapped in mlx.gc_func, so its children are reachable by name
# through named_modules() rather than as plain attributes.
_dec = model.speech_tokenizer.decoder
_mods = dict(_dec.named_modules())
wrap(_mods["quantizer"], "decode", "dec.dequant",
     "RVQ dequantisation: [1,16,T] codes -> [1,codebook_dim,T] latent", limit=1)
for _name, _label in [("pre_conv", "causal conv into latent_dim, NLC"),
                      ("pre_transformer", "8-layer decoder transformer, NLC")]:
    wrap(_mods[_name], "__call__", f"dec.{_name}", _label, limit=1)
for _name, _mod in sorted(_mods.items()):
    if _name.startswith("decoder.") and _name.count(".") == 1:
        wrap(_mod, "__call__", f"dec.stage.{_name.split('.')[1]}",
             f"decoder stage: {type(_mod).__name__}", limit=1)
    elif _name.startswith("upsample.") and _name.count(".") == 2:
        wrap(_mod, "__call__", "dec.up." + _name.split(".", 1)[1],
             f"upsample layer: {type(_mod).__name__}", limit=1)
wrap(model, "extract_speaker_embedding", "speaker.embedding",
     "ECAPA-style x-vector from the reference wav, [1,enc_dim]")

# The mel frontend is its own bug surface -- window, padding, log floor,
# filterbank normalisation -- and it feeds the speaker encoder, so dump it
# separately. The filterbank alone is pure arithmetic and can be diffed with no
# audio at all, the same way the rope table can be diffed with no weights.
import mlx_audio.tts.models.qwen3_tts.qwen3_tts as q3
from mlx_audio.dsp import mel_filters as _mel_filters
put("mel.filters", _mel_filters(sample_rate=24000, n_fft=1024, n_mels=128,
                                f_min=0.0, f_max=12000.0,
                                norm="slaney", mel_scale="slaney"),
    "slaney mel filterbank [128, 513], fmin 0, fmax 12000")

_orig_mel = q3.mel_spectrogram
def _mel(*a, **k):
    r = _orig_mel(*a, **k)
    put("speaker.mel", r, "log-mel of the reference wav, [1, frames, 128]")
    return r
q3.mel_spectrogram = _mel
model.__class__.extract_speaker_embedding.__wrapped__ = None

def tap_talker(i, a, k, r):
    # a[0] is self (patched on the class), a[1] is inputs_embeds.
    put(f"talker.in.{i:03d}", a[1], "inputs_embeds for this step")
    put(f"talker.logits.{i:03d}", r[0], "codebook-0 logits")
    # The prefill step's full hidden sequence is the expensive one; after that
    # only the last position is ever read.
    put(f"talker.hidden.{i:03d}", r[1] if i == 0 else r[1][:, -1:, :],
        "hidden state (full sequence on the prefill step, last position after)")

def tap_codepred(i, a, k, r):
    put(f"codepred.in.{i:04d}", a[1], "code predictor input for one group")
    put(f"codepred.logits.{i:04d}", r[0], "logits for one codebook group")
    put(f"codepred.step.{i:04d}", np.array([k.get("generation_step", -1)], dtype=np.int32),
        "generation_step, which selects the group head")

talker_state = wrap(model.talker, "__call__", "talker", "talker forward",
                    on_call=tap_talker, limit=args.steps)
code_state = wrap(model.talker.code_predictor, "__call__", "codepred",
                  "code predictor forward", on_call=tap_codepred,
                  limit=args.steps * (cfg.num_code_groups - 1))

wrap(model, "_sample_token", "sample", "", on_call=tap_sample, limit=10**9)

orig_prep = model._prepare_icl_generation_inputs
def prep(*a, **k):
    r = orig_prep(*a, **k)
    put("prefill.input_embeds", r[0], "the ICL prefill: role + codec prefix + (text+codec_pad | codec+tts_pad)")
    put("prefill.trailing_text_hidden", r[1], "non-streaming: just tts_pad_embed")
    put("prefill.tts_pad_embed", r[2], "tts pad embedding, added on every step after the text runs out")
    put("prefill.ref_codes", r[3], "reference codes reused as the decode prefix")
    return r
model._prepare_icl_generation_inputs = prep

# ------------------------------------------------------------------- run
mx.random.seed(args.seed)
audio_ref = load_audio(str(ref_wav), sample_rate=24000)
put("input.ref_audio", audio_ref, f"{ref_wav.name}, mono 24 kHz")

print(f"generating: {args.text[:60]}…", flush=True)
t0 = time.time()
chunks = []
for r in model.generate(text=args.text, ref_audio=str(ref_wav), ref_text=ref_text,
                        temperature=0.9, top_k=50, top_p=1.0,
                        max_tokens=args.max_tokens, verbose=False):
    chunks.append(np.array(r.audio).reshape(-1))
gen_s = time.time() - t0
wave = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
put("output.waveform", wave, "final audio, mono 24 kHz")
put("sampled.codebook0", np.array(sampled_first, dtype=np.int32),
    "the codebook-0 token sampled at each step -- teacher-force the Swift port with these")
put("sampled.codegroups", np.array(sampled_code, dtype=np.int32),
    "codebook 1..15 tokens, 15 per step, in order")

if talker_state["n"] == 0 or code_state["n"] == 0:
    sys.exit("taps recorded nothing -- the wrappers did not fire, so this dump "
             "would be a silent lie. Fix the hook before trusting any diff.")

speech_s = len(wave) / 24000.0
words = len(args.text.split())
manifest = {
    "repo": REPO, "voice": args.voice, "text": args.text, "ref_text": ref_text,
    "seed": args.seed, "steps_recorded": args.steps, "max_tokens": args.max_tokens,
    "generate_seconds": round(gen_s, 2), "audio_seconds": round(speech_s, 2),
    "words": words,
    "words_per_second": round(words / speech_s, 3) if speech_s > 0 else None,
    "mlx_version": mx.__version__,
    "talker_calls": talker_state["n"], "codepred_calls": code_state["n"],
    "tensors": meta,
}
# Flat little-endian binaries plus an index, not .npz.
#
# An .npz is a zip of .npy files, and the consumer is Swift: reading it would
# mean writing a zip reader and an npy header parser before a single tensor
# could be compared, and both of those are places to introduce a bug into the
# thing that exists to catch bugs. A raw f32/i32 blob per tensor is read with
# one `Data(contentsOf:)`, and numpy reads it back just as easily
# (`np.fromfile(p, dtype).reshape(shape)`).
blobs = out / "tensors"
for stale in blobs.glob("*.bin"):
    stale.unlink()
blobs.mkdir(parents=True, exist_ok=True)
total = 0
for name, a in rec.items():
    if a.dtype.kind == "f":
        a = a.astype("<f4")
    elif a.dtype.kind in "iu":
        a = a.astype("<i4")
    else:
        raise SystemExit(f"{name}: unsupported dtype {a.dtype}")
    (blobs / f"{name}.bin").write_bytes(a.tobytes(order="C"))
    meta[name]["file"] = f"tensors/{name}.bin"
    meta[name]["stored_dtype"] = "f4" if a.dtype.kind == "f" else "i4"
    meta[name]["count"] = int(a.size)
    total += a.nbytes
manifest["tensors"] = meta
manifest["layout"] = ("little-endian C-order blobs; f4 = Float32, i4 = Int32; "
                      "shape and count are in this index")
(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
old_npz = out / "groundtruth.npz"
if old_npz.exists():
    old_npz.unlink()

print(f"\n{len(rec)} tensors -> {blobs} ({total/1e6:.1f} MB)")
print(f"audio {speech_s:.1f}s in {gen_s:.1f}s · {words} words · "
      f"{words/speech_s:.2f} words/s" if speech_s > 0 else "NO AUDIO")
