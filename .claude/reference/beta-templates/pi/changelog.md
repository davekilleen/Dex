# Pi Integration Changelog

All notable changes to the Pi integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Planned
- Template library for common tools
- One-click sharing of custom skills
- Automatic testing framework
- Visual workflow builder

---

## [0.1.0] - 2026-02-03

### Added
- **Initial Pi integration** - Core meta-programming layer for Dex
- **MCP bridge** - Task and calendar access for Pi-built tools
- **Beta activation system** - Feature flags for controlled rollout
- **Core commands**:
  - `/pi-status` - Check integration status
  - `/pi-build` - Create new tools and skills
  - `/pi-improve` - Enhance existing custom tools
  - `/pi-ideas` - Get suggestions for what to build
  - `/pi-list` - List custom creations
  - `/pi-help` - Detailed documentation
  - `/pi-feedback` - Submit beta feedback
  - `/pi-request` - Request new features
- **Skill scaffolding** - Automatic file structure for new skills
- **Error handling** - Graceful failures with actionable messages
- **Beta documentation** - [[README]], troubleshooting, examples

### Technical Notes
- Pi-built skills are stored in `.claude/skills/pi-custom/`
- Custom workflows are stored in `System/Pi/workflows/`
- Feedback is logged to `System/Pi/feedback.md`

---

## Version Numbering

- **0.x.x** - Beta period (expect breaking changes)
- **1.0.0** - Stable release (coming after beta feedback integration)

---

## Reporting Issues

If you encounter bugs or unexpected behavior:

1. Note the version number above
2. Include steps to reproduce
3. Share any error messages
4. Use `/pi-feedback` or the beta Discord channel
