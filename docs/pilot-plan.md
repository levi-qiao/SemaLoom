# T08B unauthorized pilot plan

A47–A48 are **not** closed. Local PostgreSQL synthetic fixtures are not a real-enterprise pilot.

To run an authorized pilot, the owner must provide:

1. Written access to specific source systems and a data-minimization scope
2. Named policy expert review of any tax/procurement rules (demo rules are not valid law)
3. Production identity issuer, audience, revocation, and TLS termination
4. Retention, backup, and recovery RPO/RTO
5. Load envelope (concurrency, data volume) and SLO targets defined **before** measurement
6. Approval roles distinct from query roles

Until those exist, this repository only demonstrates the synthetic PoC. Do not treat demo tokens, demo policy, or `semaloom_*` databases as production-ready.
