# AGENTS.md

## Repository Overview
This is a personal GitHub Profile README repository (`Siborne/Siborne`). The main file of interest is `README.md`.

## Commands & Workflow
- **No build steps**: This is a static markdown repository with external embedded services (Capsule Render, Typing SVG, GitHub Stats, Snake animation).
- **Updates**: Modify `README.md` directly. Changes to the repository trigger GitHub Actions for the contribution snake (assuming a workflow exists, though it is not present in the local root; it may be on another branch).
- **Preview**: Render `README.md` in a Markdown viewer. Be careful with HTML layout alignment (`<div align="center">`, etc.) as GitHub renders HTML in Markdown strictly.

## Editing Guidelines
- Maintain the existing HTML structure and `align="center"` divs.
- Preserve the external widget URLs and only modify query parameters if updating them.
- Any new assets should be placed in the `assets/` directory.