# Preserve Claude review failure diagnostics

The official packaged Claude review backend rejected a real completed Qwen response as a nonzero transport outcome. Its only recorded diagnostic was the final verdict tag in the error result text, so the result envelope's failure subtype and exit status were lost. The actual failed case is standalone fan-out bfc2cec03f235d94270139f2e8e0ec91 in the disposable local routing fixture; it is not a product acceptance verdict.

## Acceptance Criteria

- **R1:** A Claude result rejected as an error retains bounded, non-secret structured diagnostic fields needed to distinguish CLI exit failure, error result subtype, API status, and malformed result shape in Flow's normal failure output and receipts.
- **R2:** Error envelopes, malformed JSON, nonzero CLI exits, and model-unavailable results remain failures even when their text contains a SHIP tag. Explicit model pins still prevent fallback.
- **R3:** Focused regression tests exercise the failing diagnostic path through the packaged Flow review command and preserve the existing successful review and refund behavior.

## Boundaries

Keep the implementation generic and minimal. Preserve official workflow ownership, APIs, counter semantics and reviewer read-only tools. Do not introduce another review pipeline, change provider infrastructure, weaken verdict validation, or publish upstream.
