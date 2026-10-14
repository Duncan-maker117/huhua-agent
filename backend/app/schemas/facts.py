"""Shared, deliberately small contract for candidate evidence."""

FACT_SECTIONS = ("projects", "work_experience", "internship", "education", "campus", "open_source", "awards")
FACT_LABELS = {"projects": "name", "work_experience": "company", "internship": "company",
               "education": "school", "campus": "name", "open_source": "name", "awards": "name"}
FACT_FIELDS = {
    "projects": {"name", "role", "start_date", "end_date"},
    "work_experience": {"company", "title", "role", "start_date", "end_date"},
    "internship": {"company", "title", "role", "start_date", "end_date"},
    "education": {"school", "major", "degree", "grade", "start_date", "end_date", "highlights"},
    "campus": {"name", "role", "start_date", "end_date"},
    "open_source": {"name", "summary", "pr", "start_date", "end_date"},
    "awards": {"name", "level", "date"},
}
FACT_KINDS = frozenset({
    "role", "action", "method_tool", "deliverable", "result_metric",
    "result_qualitative", "scope_scale", "status_limit", "context", "team",
})
FACT_STATUSES = frozenset({"active", "superseded", "deleted"})
FACT_SOURCES = frozenset({"chat", "editor", "import"})
