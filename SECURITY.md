# Security

MAAT executes untrusted student code in Docker containers with network disabled, dropped capabilities, no-new-privileges, PID/CPU/RAM limits, a read-only root filesystem and tmpfs for `/tmp`. Source filtering is a pedagogical defense-in-depth measure and must not be considered a complete sandbox. Do not expose MAAT as a multi-tenant public service without a stronger isolation layer such as gVisor, nsjail or virtual machines.
