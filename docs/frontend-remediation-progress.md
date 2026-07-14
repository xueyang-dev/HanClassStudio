# Frontend remediation progress

This record tracks the incremental frontend hardening work on top of the latest
`main` baseline (`5ea6764`). Each slice keeps the backend ProjectState and
`available_actions` contract authoritative.

| Iteration | Scope | Status | Validation |
| --- | --- | --- | --- |
| 1 | Deep-link project loading skeleton; viewable/editable/executable stage access | Implemented | Frontend state contract; production build |
| 2 | Backend action availability; one next workflow action; localized stage/gate/blocker/media/agent states; execution-button guards | Implemented | API route focus tests; frontend state contract; production build |
| 3 | Settings dialog focus lifecycle and provider write-after-edit semantics | Implemented | Frontend state contract; production build |
| 4 | Responsive workflow navigation, provider mobile controls, blocker resolution CTA, and advanced-information hierarchy | Implemented | Frontend state contract; production build |
| 5 | Editable-stage enforcement, localized revision errors, and first loading-component extraction | Implemented | Frontend state contract; production build |
| 6 | Backend-confirmed Provider summary, retryable save after failed initialization, native dialog lifecycle for onboarding/force export, and six-stage localization parity | Implemented | Frontend state contract; i18n key parity audit; production build |
| 7 | Browser acceptance regressions: State-first summary 404 guard, responsive pipeline overflow, dialog descriptions, duplicate list keys, favicon, and atomic provider-settings writes | Implemented | Playwright desktop/mobile audit; 432 backend tests; E2E |

## Browser acceptance

**Conclusion: PASS**

The bundled in-app browser channel could not be initialized because its
injection script attempts to redefine the host `process` property. A temporary
copy that skipped that assignment was rejected by the channel trust bridge, so
the plugin cache was left unchanged. Equivalent verification was completed in
the repository's Playwright stack with Chrome for Testing 149.0.7827.55 on
macOS 26.5.2 arm64.

Services and test fixtures:

- Web UI: `http://127.0.0.1:5174`
- API: `http://127.0.0.1:8012`
- Incomplete deep-link fixture: project `614c21453f7b`
- Complete/force-export fixture: project `bc9c58a0683c`
- Temporary evidence root: `/tmp/hanclassstudio-browser-audit-20260714`

Verified scenarios:

- Deep-link loading showed `.project-loading` and no new-lesson heading before
  the project response. Invalid `stage=does-not-exist` safely resolved to the
  persisted profile stage; the active step had no `disabled` or
  `aria-disabled="true"` conflict.
- The quality page exposed only the backend-declared next action as enabled;
  unavailable media/render actions were disabled. A stale fixture disabled
  render and showed localized “需要重新运行 / 质量结果已过期” messaging.
- `not_started`, `not_run`, `blocked`, and `stale` were visually distinct in
  their respective fixtures. Six-language snapshots (`zh`, `en`, `ja`, `ko`,
  `ar`, `ru`) contained no raw backend enum tokens or English backend blocker
  phrases. English words such as “Not started” are the intended translation.
- Provider summary showed configured and available counts separately. Initial
  settings load generated 0 PUT requests; a real edit generated one PUT. An
  intentionally aborted edit showed the localized connection error, and the
  next edit generated a successful PUT, cleared the error, and showed “设置已
  保存到服务器”. No request payload contained a plain API key.
- Settings, onboarding, and force-export dialogs all had native modal semantics,
  `aria-modal="true"`, labelled-by and described-by references, focus entry,
  Tab/Shift+Tab containment, Escape closure, scroll lock, and cleanup. Settings
  and force-export mouse cancellation restored the trigger focus.
- 1280×800, 768×800, and 390×844 screenshots showed no document or pipeline
  horizontal overflow. Desktop top controls stayed on one line; mobile showed
  the compact `第 N/6 步` navigator and a two-column pipeline grid. Provider
  selection remained a native select on mobile. Advanced information stayed in
  a collapsed `<details>` section.
- Normal pages had no console/page/network errors. The only logged browser
  network error was the deliberate `ERR_FAILED` from the aborted-provider-save
  test; the retry completed normally.

Evidence and logs:

- Browser channel diagnosis: `/tmp/hanclassstudio-browser-audit-20260714/browser-channel-diagnosis.txt`
- Main audit JSON and telemetry: `/tmp/hanclassstudio-browser-audit-20260714/final-browser-audit.json`
- Corrected six-language enum audit: `/tmp/hanclassstudio-browser-audit-20260714/language-audit.json`
- Provider failure/retry telemetry: `/tmp/hanclassstudio-browser-audit-20260714/provider-retry-final.json`
- Stale-state audit after duplicate-key fix: `/tmp/hanclassstudio-browser-audit-20260714/stale-browser-audit-after-fix.json`
- Dialog semantics and keyboard telemetry: `/tmp/hanclassstudio-browser-audit-20260714/dialog-audit.json`
- E2E output: `/tmp/hanclassstudio-browser-audit-20260714/e2e-atomic.log`
- Screenshots: `/tmp/hanclassstudio-browser-audit-20260714/screens/final/`

The browser channel itself remains unavailable in this host environment, and
the acceptance used an isolated temporary runtime rather than production data.
No visual, keyboard, or state-management claim was made from static tests
alone.
