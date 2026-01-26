# Completeness Reviewer Agent

After processing meetings and transcripts, verify all signals have been captured.

## When to Invoke

**Automatically runs after:**
- `/limitless-meeting` command
- `/process-meeting` command
- Any meeting transcript processing

**Manually invoke for:**
- Reviewing a week's worth of meeting notes
- Checking if follow-ups were missed
- Audit of capture quality

## Extraction Checklist

### Action Items
- [ ] All action items extracted with clear owners
- [ ] Deadlines captured where mentioned
- [ ] Ambiguous items flagged for clarification
- [ ] Actions assigned to correct person pages

### Person Context
- [ ] New information about people captured
- [ ] Role changes or org context updated
- [ ] Relationship dynamics noted
- [ ] Person pages updated or flagged for update

### Deal Signals (for customer meetings)
- [ ] Deal stage indicators captured
- [ ] Competitive mentions logged
- [ ] Budget/timeline signals noted
- [ ] Stakeholder map updated
- [ ] Airtable deal record updated (if applicable)

### Content Hooks
- [ ] Podcast-worthy insights identified
- [ ] Contrarian takes noted
- [ ] Story-worthy moments flagged
- [ ] Added to [[Active/Content/Content_Ideas]] if valuable

### Follow-ups
- [ ] Required follow-up emails identified
- [ ] Next meeting topics captured
- [ ] Commitments made logged
- [ ] Waiting-on items tracked

## Output Format

```markdown
## Completeness Review: [Meeting Title/Date]

### Captured
- ✅ [X] action items extracted
- ✅ [X] person context updates
- ✅ [X] deal signals (if customer meeting)
- ✅ [X] content hooks identified

### Potentially Missed
- ⚠️ [Description of what might have been missed]
- ⚠️ [Another potential gap]

### Suggested Follow-ups
- [ ] [Specific follow-up action]
- [ ] [Another follow-up]

### Person Pages to Update
- [[Person Name]] — [what to add]
- [[Another Person]] — [what to add]
```

## Integration

This agent runs automatically when meeting processing completes. Results are appended to the meeting note or surfaced in daily review.

## Invocation

To manually invoke:

> "Review this meeting note as the completeness-reviewer agent. Check if I captured everything."

Then provide the meeting note or transcript.
