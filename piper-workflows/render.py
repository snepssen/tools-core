#!/usr/bin/env python3
"""piper's CLI, with ONNX Runtime telemetry off first.

Same shape as train.py: a wrapper rather than a flag, because the fix has to
land before the library it fixes is imported. See no_telemetry.
"""
import sys

import no_telemetry  # noqa: F401  -- imported for its effect

from piper.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
