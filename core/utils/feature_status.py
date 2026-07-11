"""Shared feature-status response contract for Dex MCP servers.

Vocabulary:
- ``ok``: the feature is enabled and working.
- ``off``: the user deliberately did not enable or configure the feature. This
  is healthy, must never use an error tone, and must never nag the user.
- ``not_installed``: a required app, binary, or dependency is absent.
- ``broken``: the feature is configured and expected to work, but is failing.
- ``unknown``: the state could not be determined because the check itself failed.
"""

STATES = ("ok", "off", "not_installed", "broken", "unknown")


def feature_status(
    feature: str,
    state: str,
    user_message: str,
    detail: str | None = None,
    **extra,
) -> dict:
    """Build a feature-status payload while preserving caller-supplied fields."""
    if state not in STATES:
        raise ValueError(f"Invalid feature state: {state}")

    result = {
        "success": state == "ok",
        "feature": feature,
        "feature_status": state,
        "user_message": user_message,
    }
    if detail is not None:
        result["detail"] = detail
    result.update(extra)
    return result
