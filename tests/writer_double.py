"""Schema-valid no-selection model for deterministic source-recovery flow tests."""
from types import SimpleNamespace


class SourceWriter:
    """Exercise source recovery without simulating a failed primary model call.

    A valid object with no selected rows is distinct from None, a non-object,
    or an exception. It retains the existing observable EmptyWriterDraft path.
    """

    def with_structured_output(self, schema):
        async def invoke(messages):
            if schema.__name__ == 'OnePassOutput':
                return {'match_plan': {}, 'writer': {'items': []}}
            if schema.__name__ == 'WriterDraft':
                return {'items': []}
            if schema.__name__ == 'RepairOutput':
                return {'bullets': []}
            return {}
        return SimpleNamespace(ainvoke=invoke)
