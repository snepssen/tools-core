# Security

Please report a vulnerability privately through this repository's GitHub
Security Advisory page rather than opening a public issue.

These are local command-line tools and scripts, not network services. Any tool
here that opens a listener must bind only to the IPv4 loopback address. Do not
modify one to listen on a LAN or public interface without adding a full
authentication, authorization, origin-validation, and file-access design.

Review downloaded models, checkpoints, and Python packages before loading them.
PyTorch checkpoints may contain pickled Python data and should be treated as
executable content unless they come from a trusted source.
