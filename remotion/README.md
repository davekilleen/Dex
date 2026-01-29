# Dex Videos

Generate promotional and demo videos for Dex using Remotion.

## Quick Start

```bash
cd remotion
npm run dev    # Opens Remotion Studio
```

## Render Videos

```bash
npm run render         # 1920x1080 standard
npm run render:square  # 1080x1080 LinkedIn
npm run render:vertical # 1080x1920 shorts/reels
npm run render:all     # All formats
```

Output goes to `out/` folder.

## Creating New Videos

Ask Claude to create a new video:

```
/create-video [description]
```

Claude will:
1. Create a new composition in `src/`
2. Register it in `Root.tsx`
3. Add render scripts to `package.json`

## Current Videos

| Composition | Duration | Description |
|-------------|----------|-------------|
| `DexIntro` | 14s | Product intro: title, features, setup steps, CTA |
| `DexIntro-Square` | 14s | Same content, square format |
| `DexIntro-Vertical` | 14s | Same content, vertical format |

## Tech Stack

- **Remotion** - React-based video rendering
- **TypeScript** - Type safety
- **React 19** - Latest React

## Folder Structure

```
src/
├── Root.tsx         # Composition registry
├── DexIntro/        # Intro video
│   ├── index.tsx    # Main sequence
│   ├── TitleScene.tsx
│   ├── FeaturesScene.tsx
│   ├── HowItWorksScene.tsx
│   └── CTAScene.tsx
```
