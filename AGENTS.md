# FleetSentinel — Agent Instructions

Shared instructions for any coding agent working in this repo (Claude Code, Codex,
OMC, OMX, Gajae Code). Keep this file tool-neutral so every agent reads the same rules.

## Commit conventions

Do not add AI or tool co-author / attribution trailers to commits. Banned examples:

- `Co-authored-by: OmX <omx@oh-my-codex.dev>`
- `Co-Authored-By: Claude`, `Co-Authored-By: Codex`, `Co-Authored-By: Gajae`
- `🤖 Generated with Claude Code` and similar tool signature lines

Do not name the tool or agent in the commit body either — no `oh-my-codex`,
`oh-my-claudecode`, `OMC`, `OMX`, `gajae-code`, `gjc`, or agent names such as
`code-reviewer` / `architect`. Which tool wrote the change is not history worth keeping.

Nothing strips these automatically — there is no commit-msg hook. Write the message
clean in the first place.

Decision trailers stay welcome, since they record *why* rather than *who*:

```
Constraint:   the active constraint that shaped the decision
Rejected:     alternative considered | reason for rejection
Confidence:   high | medium | low
Scope-risk:   narrow | moderate | broad
Tested:       what was actually verified
Not-tested:   known verification gap
```

## File access

Never read `.env`, `.env.local`, `.env.production`, `*.env`, or any `.env.*` that is
not an `example` / `sample` file — including indirectly via shell, scripts, or
containers. Only `*.env.example` and `*.env.sample` may be read.

## Local tooling

Agent state directories (`.claude/`, `.omc/`, `.omx/`, `.codex/`, `.gjc/`) are
gitignored. Keep per-developer tool setup out of the repo.

## Document viewing & HTML authoring

When asked to "show / view / 보여줘" a document (Markdown **or** HTML), publish it to a
GitHub **gist** via `gh` and return the link — do not dump raw text:

- Markdown (`.md`): `gh gist create <file>` → return the gist page URL (renders tables, code, mermaid; mobile-friendly).
- HTML (`.html`): `gh gist create <file>` → return `https://gistpreview.github.io/?<gist-id>`.
- Gists are secret (unlisted) by default. Anyone with the URL can read — never put secrets in one. Publish only the file(s) explicitly named.

Author every HTML document/diagram **mobile-first and self-contained** so it renders on phone and desktop via gistpreview:

- `<meta name="viewport" content="width=device-width, initial-scale=1">` and `*{ box-sizing:border-box }`.
- Inline all CSS/JS (single self-contained file — no external deps).
- Fluid sizing: prefer `%`/`rem`/`clamp()` + a centered `max-width` (~1100px) wrapper over fixed `px`; legible type; support `@media (prefers-color-scheme: dark)`.
- No horizontal overflow on phones: stack horizontal rows to a column under ~600px; put `min-width:0` on flex children holding wide `<pre>`/tables; use `white-space:pre-wrap; word-break:break-word` for code blocks.
