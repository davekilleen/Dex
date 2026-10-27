# Dex Helper source

Mac app that asks for Calendar and Reminders permission under
`ai.heydex.DexHelper`. Dex opens this app through LaunchServices so the
permission ask belongs to the helper, not the editor.

```
bash build.sh          # macOS only; skips elsewhere
```

The dev build ad-hoc signs with `codesign --sign -`. Rebuilding resets
the Calendar and Reminders grant. Developer ID and notarization are a
later release step that needs explicit founder approval. See
`docs/macos-privacy-helper.md`.
