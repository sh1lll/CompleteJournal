"""API sync adapters.

Design rules (assessment §5.7, §10):
  * READ-ONLY by construction — no order/placement endpoint is implemented in
    any adapter, ever. Adapters fetch fills/orders/accounts, nothing else.
  * Credentials come from the environment or keyring at call time; they are
    never written to the database or any file.
  * Every adapter maps platform fills to NormalizedExecution and feeds the
    same ingest() as CSV imports — one schema, many sources (decision D1).
  * Adapters accept an injectable httpx transport so the full mapping logic
    is testable without network access.

⚠️ Status: built against official/public API documentation; NOT yet run
against live platform endpoints (no credentials in the build environment).
Roadmap flag A5 tracks live validation.
"""
from . import projectx, tradovate  # noqa: F401
