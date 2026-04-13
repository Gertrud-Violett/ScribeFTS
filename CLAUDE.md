# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**NHI_Librarian** is a simple tool to organize documents using customizable metadata. It is licensed under the BSD 2-Clause License.

## Repository Structure

```
NHI_Librarian/
├── CLAUDE.md       # Claude Code guidance (this file)
├── LICENSE         # BSD 2-Clause License
└── README.md       # Project overview
```

## Development Guidelines

- Keep code simple and focused on document organization with customizable metadata.
- Follow the BSD 2-Clause License terms when contributing.
- Write clear, descriptive commit messages.

## Build, Lint, and Test

No build system or test suite has been set up yet. When they are added, document the commands here, for example:

```bash
# Install dependencies
# npm install   (Node.js)
# pip install -e .  (Python)

# Run tests
# npm test
# pytest

# Lint
# npm run lint
# flake8
```

## Code Style

- Use consistent naming conventions appropriate to the chosen language.
- Keep functions small and focused on a single responsibility.
- Prefer explicit over implicit behavior in metadata handling.

## Key Concepts

- **Document**: any file managed by the librarian.
- **Metadata**: customizable key-value pairs attached to a document (e.g., tags, author, date, category).
- **Library**: the collection of documents along with their metadata store.
