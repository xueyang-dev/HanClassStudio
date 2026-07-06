# Artifact Ownership

| Folder | Owner | Kind | Rebuildable |
|---|---|---|---|
| `uploads/` | user | source | no |
| `sources/` | intake/parser | source contract | yes, from uploads |
| `analysis/` | machine analysis | derived facts | yes |
| `specs/` | strategist / user / agent | source design and execution contract | partially |
| `blueprints/` | strategist / user / agent | source courseware structure | partially |
| `assets/` | media generator / user | runtime source | partially |
| `courseware/` | renderer | derived | yes |
| `quality/` | quality gate | derived report | yes |
| `exports/` | exporter | derived delivery snapshot | yes |

Agents should edit `specs/`, `blueprints/`, and carefully controlled `assets/data/` manifests. Do not edit derived folders to fake success.

