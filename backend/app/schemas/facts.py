"""Shared, deliberately small contract for candidate evidence."""

FACT_SECTIONS = ("projects", "work_experience", "internship", "education")
FACT_KINDS = frozenset({
    "role", "action", "method_tool", "deliverable", "result_metric",
    "result_qualitative", "scope_scale", "status_limit", "context", "team",
})
FACT_STATUSES = frozenset({"active", "superseded", "deleted"})
FACT_SOURCES = frozenset({"chat", "editor", "import"})
