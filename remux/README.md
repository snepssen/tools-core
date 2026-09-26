# Remux

Put audio and video in another container without re-encoding or discarding
a stream.

```sh
python3 remux/remux.py recording.mp4 recording.mkv --plan
python3 remux/remux.py recording.mp4 recording.mkv
python3 remux/remux.py recording.mkv recording.mp4 --plan --json
```

The output extension chooses **MKV, MP4, MOV, WebM or M4A**. Every audio and
video track must fit. For example, H.264/AAC can be copied from MP4 to MKV,
but H.264 cannot be copied into WebM: that request is refused. M4A accepts
compatible audio-only inputs; this tool does not remove video to make one.

Subtitles must fit unchanged too. MP4/MOV accept `mov_text`; MKV accepts the
listed text and picture subtitle codecs in the command. SRT-to-MP4 would
require subtitle conversion and is refused. MKV attachments can be copied;
cover-image streams, data streams and unrecognised combinations are refused.
The compatibility list is intentionally limited; a refusal does not mean
the container could never support the format.

`--plan` reads the input and explains the proposed copies without writing.
Without it, FFmpeg writes a temporary output beside the destination, the
tool checks every output stream's type and codec against the input, and
only then publishes the result. The destination must not exist and its
parent directory must already exist. An existing file is never overwritten,
even if it appears during processing. Publishing uses a hard link; a
filesystem that cannot create one fails without publishing the output.
The source is never modified. A normal failure or cancellation removes the
temporary output; force-killing the process can leave a `.remux-*` directory.

Container metadata and chapters are requested for copying, but containers
represent them differently; this does not guarantee every tag or timestamp
is represented identically. A container-generated extra stream fails the
inventory check. Audio/video/subtitle encoding is never enabled. Integration
tests compare every packet hash on generated multi-track and subtitle media;
the runtime check compares stream inventories, not every packet hash.

Requires Python 3.8+, FFmpeg and ffprobe on PATH (or in the upstream locator's
standard installation locations). No Python packages. Input must be a local
file; there is no download, queue or account setup. JSON is a single object.
Status 0 means success, 1 means refusal/failure, 2 means invalid arguments,
and 130 means cancellation.

## Source and maintenance

The probing code and audio/video compatibility table come unchanged from
[siphon](https://snepssen.github.io/siphon/). The standalone interface applies
stricter all-stream copy rules and safe output publication.
`engine/MANIFEST.json` records the upstream version, commit and hashes.

```sh
python3 scripts/from-projects.py --project siphon --from ../siphon
python3 scripts/from-projects.py --check --only remux
```

Verified using real FFmpeg/ffprobe on macOS. The standalone command has not
been exercised on Windows or Linux.
