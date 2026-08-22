# Meeting sources

A meeting source is a choice, not a fork in the code. Adding one should mean
writing an adapter, never editing `/process-meetings`, onboarding, or the flows.

This is the contract that makes that true.

## The shape

```
provider payload  ->  adapter  ->  MeetingRecord  ->  landing zone  ->  existing detector
```

Only the adapter knows which provider it came from. Everything to the right of
it is provider-neutral, and a test fails the build if a provider name appears in
`record.py`, `attribution.py`, `landing_zone.py` or `calendar_lookup.py`.

## The record

`core/meeting_sources/record.py`. Two decisions in it carry the weight.

**Absence is representable.** `title` and `attendees` are routinely empty from
real providers: a recorder that titles and attributes from a calendar it cannot
read returns neither. A record that forced them would push adapters into
inventing values, and an invented attendee becomes an invented commitment two
steps later. Empty means unknown, and callers must treat it that way. That is
what `attribution_is_reliable` is for.

**Provenance is mandatory.** `source` and `source_id` are what dedup and
person-page touch tracking run on. They are written to the note as two separate
frontmatter keys, `source: <name>` and `<name>_id: <id>`. Folding the id into
the source line makes the note look new on every sweep.

## Writing an adapter

One function: provider payload in, `MeetingRecord` out. Look at
`granola_adapter.py` and `wispr_adapter.py` together, because they disagree at
almost every edge and that is the point:

| | Granola | Wispr |
|---|---|---|
| Title | Supplied | None; derived from the body and flagged |
| Attendees | With emails | None |
| Action items | Curated checkboxes | Prose under a "Next Steps" heading |

Two rules learned from those two:

- **Take action items from where the provider actually puts them, and nowhere
  else.** Reading the whole summary sweeps up decisions and observations as
  though they were commitments, which is how a meeting note produces tasks
  nobody agreed to.
- **Do not import work already marked done.** Handing someone back something
  they have finished is worse than missing it.

## Attendance

`attribution.resolve(record, calendar_events)` uses the matcher Dex already
ships, `match_capture_to_calendar`: nearest start within five minutes,
tie-broken on title and participant overlap.

A capture that matches gains real attendees and the calendar's title. One that
does not keeps its warning and records why, because "no entry within the window"
and "the calendar could not be read" call for different responses.

Three refusals, each of which would otherwise state something false about who
was in a room:

- A derived title is never offered to the matcher as corroboration. It
  tie-breaks on title, and a title we invented is not evidence.
- Matching an event that lists nobody leaves attendance unresolved. The match is
  real; the attendance is not thereby known.
- A calendar that cannot be read is never reported as a meeting with no
  attendees. `calendar_lookup` returns `None` for every failure, and callers
  must distinguish that from an empty list.

**Trap:** the matcher parses timestamps and rejects any that does not declare an
offset. Passing a `datetime` rather than an ISO string makes every capture come
back `unmatched / capture_timestamp_missing_timezone`, which is
indistinguishable from a genuinely absent calendar entry. Attribution then
silently never works while appearing to.

## Acquisition, and who holds the credential

Fetching is per-provider by nature, but one property of it is worth deciding
deliberately: **who holds the credential.**

- **Dex-held** (an API key, or OAuth through the connection manager): the source
  can be swept on a schedule and works whichever MCP client the vault is opened
  in.
- **Host-held** (a credential inside an MCP client's connector store): the
  source can only be read while a human is signed in to that client, and moving
  the vault to another client breaks it silently.

Prefer Dex-held. A provider exposing a standards-compliant remote MCP server can
be Dex-held even when the obvious route is a host connector.

However it is fetched, write into the landing zone (`core.paths.MEETINGS_DIR`)
and stop. The existing detector picks the note up unchanged.

## Honest failure

A sweep that cannot reach its provider must say so. Reporting "no new meetings"
when the real answer is "the recorder was unreachable" turns an outage into a
quiet week, and nobody investigates a quiet week.
