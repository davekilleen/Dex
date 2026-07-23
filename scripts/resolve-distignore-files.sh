#!/bin/sh
# Resolve .distignore rules against a pre-enumerated, sorted file list.

set -eu

DISTIGNORE=$1
ALL_FILES=$2
EXCLUDED_FILES=$3
INCLUDED_FILES=$4

: > "$EXCLUDED_FILES"
while IFS= read -r line; do
  line=${line%%#*}
  line=$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
  [ -z "$line" ] && continue
  case "$line" in
    */)
      awk -v prefix="$line" 'index($0, prefix) == 1 { print }' "$ALL_FILES" \
        >> "$EXCLUDED_FILES"
      ;;
    *)
      git ls-files --cached --others --exclude-standard -- "$line" \
        >> "$EXCLUDED_FILES"
      ;;
  esac
done < "$DISTIGNORE"

LC_ALL=C sort -u -o "$EXCLUDED_FILES" "$EXCLUDED_FILES"
LC_ALL=C comm -23 "$ALL_FILES" "$EXCLUDED_FILES" > "$INCLUDED_FILES"
