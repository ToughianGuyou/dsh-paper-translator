# Dependency and font notes

The original implementation in this package is offered under AGPL-3.0-or-later.
PyMuPDF 1.26.6 / MuPDF are provided separately by their vendors under AGPL or commercial licensing. This source archive does not bundle their wheels or native binaries. Their licensing conditions remain applicable to deployment and redistribution.

- PyMuPDF licensing: https://pymupdf.readthedocs.io/en/latest/about.html and https://pymupdf.readthedocs.io/en/latest/license.html
- MuPDF licensing: https://mupdf.com/licensing
- Default PDF font: `fitz.Font('cjk')`, the Droid Sans Fallback embedded resource supplied by installed MuPDF. Font bytes are embedded in generated PDFs. Distribution notices and exact font provenance are in the installed MuPDF distribution. A local font can be selected using `fontPath`; operators must have the necessary embedding rights.
- Harness/Cordis/Schemastery dependencies are resolved from the installation; they retain their own package licenses.

No external model, OCR executable, translation API client, cloud upload service or API credential is included in this plugin.

- Beautiful Soup 4 (MIT) parses HTML; FontTools (MIT) supports experimental PDF font inspection. These Python dependencies are installed separately, not bundled as wheels.
