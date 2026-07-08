# Security Policy

HanClassStudio v0.1 is a local-first public alpha demo, not a production-ready hosted service.

## Reporting Security Issues

Please report security issues privately to the repository owner instead of opening a public issue. Include:

- affected files or workflow
- reproduction steps
- impact
- suggested mitigation, if known

## Sensitive Data Rules

Do not commit:

- API keys
- model provider keys
- `.env` files with secrets
- student data
- real classroom privacy materials
- private school or teacher documents
- generated `runtime/projects` output

`runtime/projects` is local generated output and should not be committed.

## Demo Data

Use synthetic or public teaching samples for issues, pull requests, screenshots, and demos.

