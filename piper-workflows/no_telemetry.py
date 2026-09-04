"""Turn off ONNX Runtime's telemetry before anything creates a session.

ONNX Runtime ships Microsoft's 1DS/Aria client compiled in, and on this
machine its uploader thread segfaults: `TransmissionPolicyManager::uploadAsync`
-> `OfflineStorage_SQLite::GetAndReserveRecords` -> EXC_BAD_ACCESS on a null
pointer, on a worker thread, *after* the useful work is finished. The visible
symptom is a check-in that exports a perfectly good 63 MB model and then dies
with "Segmentation fault: 11" before rendering a single sample, because
`set -e` cannot tell a crash on the way out from a crash that mattered.

`import piper` loads onnxruntime, so this has to be imported before piper is.
Importing this module is the whole effect -- there is nothing to call.
"""
import onnxruntime as _ort

_ort.disable_telemetry_events()
