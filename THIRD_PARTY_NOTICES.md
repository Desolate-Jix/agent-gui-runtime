# Third-party notices

This file covers only the optional OmniParser learning shadow integration. OmniParser source code, model weights, virtual environments, and optional dependencies are **not distributed with this repository** and are not included in the root project license.

## OmniParser

- Upstream: [microsoft/OmniParser](https://github.com/microsoft/OmniParser)
- Use in this project: optional, read-only `screen_parser_result_v1` learning evidence from a contact-sheet smoke path.
- Authorization boundary: OmniParser output is review-only. It is not click authorization, does not enable execution binding, and cannot bypass current-capture UIA/OCR/vision Gate checks.

The upstream repository and its components must be reviewed by the user before local installation. The current integration records the following license ambiguity and component boundaries for follow-up:

- The upstream root `LICENSE` is stated as **CC-BY-4.0**, while the upstream README displays an **MIT** badge. This repository does not resolve that ambiguity or relicense upstream material.
- The detector component is identified as **AGPL-3.0**.
- The caption component is identified as **MIT**.

Obtain the exact upstream revision, model weights, and dependency licenses yourself. Do not treat the presence of a local ignored checkout or model cache as a distribution of those materials. Do not describe the third-party components as ISC or as the license of this project.
