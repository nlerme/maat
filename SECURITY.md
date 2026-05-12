# Security

MAAT executes untrusted student code in Docker containers. The default configuration disables networking, drops Linux capabilities, enables `no-new-privileges`, uses PID/CPU/RAM limits, uses a non-root container user, mounts a read-only root filesystem and provides a restricted tmpfs `/tmp`.

This improves isolation, but Docker must not be considered a perfect security boundary against a determined attacker. Source filtering is a pedagogical defense-in-depth layer and can be bypassed.

Do not expose MAAT as a hostile public multi-tenant service without stronger isolation such as gVisor, nsjail or virtual machines.

Report security issues privately to the maintainer listed in the configuration or repository metadata.
