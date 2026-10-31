# 0.2.2 validation

Primary workflow: HTML → translated HTML. No browser or PDF renderer is used for HTML jobs.

Local validation: TypeScript typecheck and build pass; 15 Node tests pass; Python suite has 53 passing tests and 3 skipped optional real-PDF tests (56 total).

HTML coverage includes formula-node preservation (MathML), references, appendix, translated captions and table cells, inline formatting, embedded local images, input immutability, placeholder loss rejection, script removal, escaped translation markup, unsupported-prose detection, source staleness and URL/path restrictions. SDK integration exercises prepare/read/submit/export/status using the installed 0.2.1-rc.3 SDK. GitHub release workflow additionally tests 0.2.2-alpha.2; its result must be checked separately.

These are synthetic and interface tests, not full-paper translation-quality acceptance. DDPM full HTML translation has not been validated. Structural checks do not guarantee semantic accuracy, browser visual fidelity, or universal website compatibility.

Legacy PDF extraction remains experimental. The previously supplied DDPM PDF still has unresolved boundary issues; this release does not claim to fix general PDF formula detection. Optional real-PDF tests require DDPM_FIXTURE_PATH and do not bundle the user's paper.

Environment regression tests: launch the real worker with Python -S to simulate missing site-packages, verify all missing packages and the actual executable are returned before any job directory is created; verify PowerShell/POSIX interpreter-path quoting, nonexistent interpreters and nonzero interpreter exits. Windows Store alias behavior is diagnosed by launch/exit/protocol errors; no Windows machine has been exercised in this local validation.

Encoding regression: real worker subprocesses run under forced cp936, cp932, cp949 and cp1251 pipe encodings with PYTHONUTF8=0. Tests preserve Chinese, Japanese, Korean, Cyrillic and emoji through prepare/read/submit/export/status, retain formula nodes, verify output files at exact Unicode paths, and preserve Unicode dependency-error fields. Bridge tests reject invalid UTF-8 inside valid-looking JSON, verify the subprocess encoding, and preserve multibyte output across writes. These checks passed locally on Linux. A new Windows CI job executes the worker encoding and environment tests; its result is separate from local validation.
