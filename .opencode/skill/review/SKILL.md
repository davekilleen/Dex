---
name: review
description: "Deprecation alias for `daily-review`. The end-of-day review was renamed; `/review` now redirects to `daily-review` and will be removed after one release. Use when the user types `/review` out of habit — hand straight off to `daily-review`, which owns end-of-day review and learning capture. Not for running the review here; use `daily-review`."
---

# /review → /daily-review (deprecation alias)

`/review` has been renamed to `/daily-review`. This alias exists only so existing
`/review` habits and any saved references keep working for one release; it will be
removed after that.

**Do this:** run the `daily-review` skill now — it owns the end-of-day review,
learning capture, and tomorrow's-focus flow. Mention once, lightly, that `/review`
is now `/daily-review` so the user learns the new name, then proceed with the
`daily-review` flow. Do not re-implement the review here; `daily-review` is canonical
and handles its own usage tracking.
