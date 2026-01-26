# Demo Mode Reference

Dex includes a demo mode with pre-populated content so you can explore the system before adding your own data.

## Toggling Demo Mode

- `/demo on` - Enable demo mode (uses sample data)
- `/demo off` - Disable demo mode (use your real vault)
- `/demo status` - Check current mode
- `/demo reset` - Restore demo content to original state

## What Demo Mode Provides

Demo mode uses content from `System/Demo/` which includes:

**Demo Persona:** Alex Chen, Product Manager at TechCorp

**Sample Content:**
- 3 projects in various stages (Mobile App Launch, Customer Portal Redesign, API Partner Program)
- 5 people pages (internal and external contacts)
- A week of meeting notes
- Pre-populated tasks across P0-P3 priorities
- Week Priorities and daily plans

## When to Use Demo Mode

- **New users:** Explore how Dex works before adding your own content
- **Demoing to colleagues:** Show the PKM system with realistic data
- **Testing commands:** Experiment without affecting your real vault

When demo mode is ON, all commands read from and write to the demo folder. Your real vault data is untouched.
