# Pre-execution implementation failure 1

The first execution terminated on the first generated instance before any result table was written. The repository generator names racks `rack-0`, `rack-1`, `rack-2`, whereas the frozen simulation-backed wireless-state library uses `rack-a`, `rack-b`, `rack-c`. This produced a missing directed-link KeyError before outcome generation.

Protocol, hypotheses, seed blocks, endpoints, target levels, methods, and statistics were not changed. The runner was corrected only to relabel generated node rack identifiers deterministically: `rack-0→rack-a`, `rack-1→rack-b`, `rack-2→rack-c`. The corrected runner is re-hashed before execution.
