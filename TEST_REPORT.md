# 0.2.0 validation

Primary workflow: HTML → translated HTML. No browser or PDF renderer is used for HTML jobs.

Local validation: TypeScript typecheck and build pass; 11 Node tests pass; Python suite has 49 passing tests and 3 skipped optional real-PDF tests (52 total).

HTML coverage includes formula-node preservation (MathML), references, appendix, translated captions and table cells, inline formatting, embedded local images, input immutability, placeholder loss rejection, script removal, escaped translation markup, unsupported-prose detection, source staleness and URL/path restrictions. SDK integration exercises prepare/read/submit/export/status using the installed 0.2.1-rc.3 SDK. GitHub release workflow additionally tests 0.2.2-alpha.2; its result must be checked separately.

These are synthetic and interface tests, not full-paper translation-quality acceptance. DDPM full HTML translation has not been validated. Structural checks do not guarantee semantic accuracy, browser visual fidelity, or universal website compatibility.

Legacy PDF extraction remains experimental. The previously supplied DDPM PDF still has unresolved boundary issues; this release does not claim to fix general PDF formula detection. Optional real-PDF tests require DDPM_FIXTURE_PATH and do not bundle the user's paper.
