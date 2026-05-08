# # ScribeFTS
Simple tool to organize documents using customizable meta data, with full-text search via FTS5

## Tech Stack
- Python3.14 or above
- Language: English

## Directory Structure
Refer to ./docs/ARCHITECTURE.md for details

## Principles of Action
- Always start tasks with Plan mode if they involve more than 3 steps
- Do not mark a task as complete until its operation can be proven
- Do not write code without reading it first
- Make changes only where necessary, minimizing the impact
- Be honest when context is tight
- Use `genv` to activate the virtual environment before running any tests (custom command)
- Whenever ARCHITECTURE.md is updated, run consistency checks to ensure the codebase matches the documented structure.
- Add robust handling for encoding issues when reading a file with potentaial Japanese characters.