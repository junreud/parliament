# Galaxy app UI verification

The user authorized building this Android app and a browser observation → repair → revalidation pipeline. Follow the existing white design in `../docs/plans/2026-10-08-galaxy-app.md`.

- Own changes only inside `mobile/src/` and `mobile/android/app/src/main/` during an automatic repair. Other agents or the user may have changes in the parent repository. Do not revert or edit those changes.
- Run `npm run qa` for unit tests, build, browser flows, screenshots, videos and traces. `npm run qa:repair` may invoke the locally installed Codex CLI only after a reproducible failure, at most 3 times, and rechecks verification-file hashes.
- Never remove tests, weaken assertions, alter expected results, disable validation, or update verification configuration to claim success. Report `contract-changed` if protected files change.
- Review screenshot files visually. Browser timing traces are synthetic evidence; do not infer physical Galaxy FPS or real-user UX quality from screenshots.
- Fix reproducible functional errors. For substantial UX/design changes, provide a concrete proposal for the user to approve.
- Preview examples are clearly labeled and independent from live data. Never replace a failing API response with examples or infer real political events, effects, identities, or votes.
- Keep public requests read-only, HTTPS-only and response-validated. Open only approved official HTTPS source links. Do not add secrets, authentication tokens, telemetry, political-profile inference or unimplemented notification toggles.
- Record issue description, reproduction, relevant file, cause, severity, correction, before/after screenshots, verification and unresolved limitations.
- Do not commit, publish, send messages or deploy as part of automatic QA.
