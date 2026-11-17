from __future__ import annotations


class MatchReason(str):
    """Formatted English evidence with its template and parameters preserved.

    Scoring APIs have historically returned strings. Retain that contract and
    keep the parameters available for report localization.
    """

    def __new__(cls, template: str, **parameters: object) -> MatchReason:
        reason = super().__new__(cls, template.format(**parameters) if parameters else template)
        reason.template = template
        reason.parameters = parameters
        return reason
