# Capabilities and limits (v0.1)

Supported:

- Compile tax and procurement synthetic domain packs to an immutable bundle
- PostgreSQL object/metric point query with tenant scope and evidence
- In-process link composition across two PostgreSQL databases
- Claim evaluation with Decimal arithmetic and TRUE/FALSE/UNKNOWN
- Immutable release publish/activate on `semaloom_meta`
- Action plan / approve / execute against a synthetic draft store
- REST semantic endpoints; MCP tool list is descriptive
- Studio graph/inspector/mapping/draft APIs and static UI

Not supported / not claimed:

- Production identity (JWT issuer/audience) — demo bearer tokens are local-dev only
- Real tax law or real enterprise data (T08B)
- Arbitrary SQL, URL, or caller-asserted permissions as request inputs
- Cross-system compensating transactions
- Public PyPI or GitHub publication (this tree prepares A49; it does not publish)
