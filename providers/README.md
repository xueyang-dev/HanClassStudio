# HanClassStudio provider fixtures

This directory contains first-party **sandbox fixtures** used to verify the
Provider Registry installation lifecycle. The fixtures are not PaddleOCR,
Ollama, Tesseract, LM Studio, or any other third-party tool, and this project
does not download, install, execute, or redistribute those tools through the
sandbox executor.

The Provider Registry links to this directory as source evidence. Third-party
names, code, models, and trademarks remain the property of their respective
rights holders. A registry lifecycle transition must never be interpreted as a
production Provider being installed or available.

`fixtures/local-image-basic-v1.json` is the phase-1 Provider Hub capability
package fixture. It is a small, non-executable JSON document with a fixed
checksum. The real Hub task runner copies it through isolated staging, validates
its Runtime/Model Package/Workflow Pack declarations, commits it atomically,
and runs deterministic health/smoke checks. It is not an image model and its
successful installation must not be presented as third-party model execution.
