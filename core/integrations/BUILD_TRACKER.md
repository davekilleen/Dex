# Productivity Integrations Build Tracker

**Orchestrator:** Sub-agent coordination via TODOs
**Status:** Historical — setup entry points consolidated into `/integrate-mcp`
**Started:** 2026-02-04

---

## Build Progress

### Notion Integration
- [ ] Test `@notionhq/notion-mcp-server` package
- [x] Route Notion setup through `/integrate-mcp` ✓
- [x] Create detection helper (check existing config) ✓
- [x] Create setup helper (guided flow) ✓
- [x] Hook into `/meeting-prep` ✓
- [x] Hook into person pages (template updated) ✓
- [x] Add to onboarding flow ✓

### Slack Integration
- [ ] Test `@kazuph/mcp-slack` package
- [x] Route Slack setup through `/integrate-mcp` ✓
- [x] Create detection helper (check existing config) ✓
- [x] Create setup helper (guided flow) ✓
- [x] Hook into `/meeting-prep` ✓
- [x] Hook into person pages (template updated) ✓
- [x] Add to onboarding flow ✓

### Google Integration
- [ ] Test `mcp-google` package
- [x] Route Google setup through `/integrate-mcp` ✓
- [x] Create detection helper (check existing config) ✓
- [x] Create setup helper (OAuth walkthrough) ✓
- [x] Hook into `/meeting-prep` ✓
- [x] Hook into person pages (template updated) ✓
- [x] Add to onboarding flow ✓

### Onboarding Integration
- [x] Add "What tools do you use?" step to onboarding ✓
- [x] Create integration orchestrator ✓
- [ ] Update onboarding MCP validation

### Update Flow (Existing Users)
- [x] Add integration detection to `/dex-update` ✓
- [x] Create comparison view for existing configs ✓
- [x] Allow keep/replace/skip choice ✓

---

## Architecture

```
User Flow:
┌─────────────────────────────────────────────────────────────┐
│ Onboarding Step: "What productivity tools do you use?"      │
│ [ ] Notion  [ ] Slack  [ ] Google Workspace  [ ] None/Later │
└─────────────────────────────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
      /integrate-mcp    /integrate-mcp    /integrate-mcp
         │                 │                 │
         └─────────────────┼─────────────────┘
                           ▼
              System/integrations/config.yaml
              (tracks which integrations are active)
```

```
Existing User Flow (/dex-update):
┌─────────────────────────────────────────────────────────────┐
│ "We've added productivity integrations!"                     │
│                                                              │
│ Detected in your config:                                    │
│ ✓ notion-mcp-server (v1.2.0)                               │
│                                                              │
│ Dex recommends: @notionhq/notion-mcp-server (v2.1.0)       │
│ Benefits: Official, better maintained, more features        │
│                                                              │
│ [Keep existing] [Try Dex version] [Skip for now]           │
└─────────────────────────────────────────────────────────────┘
```

---

## File Locations

| Component | Location |
|-----------|----------|
| Integration modules | `core/integrations/{notion,slack,google}/` |
| Setup guides | `.claude/skills/integrations/` |
| User config | `System/integrations/config.yaml` |
| Detection helper | `core/integrations/detect.py` |
| Onboarding step | `.claude/flows/onboarding.md` (new step) |
