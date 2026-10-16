# Project Environment

## Python

This project uses a dedicated virtual environment. **Always use the venv Python
directly — never the global `python`/`py`/`pip`.** Do not probe the global
interpreter first; packages are only installed in the venv.

- Virtual environment location: `.venv`
- Python executable: `d:\projects\trading\.venv\Scripts\python.exe`
- To run Python: `& "d:\projects\trading\.venv\Scripts\python.exe"`
- To run pytest: `& "d:\projects\trading\.venv\Scripts\python.exe" -m pytest`
- To install packages: `& "d:\projects\trading\.venv\Scripts\python.exe" -m pip install ...`

## Shell

- The command shell is **PowerShell**.
- Do NOT use `&&` to chain commands - it is invalid in PowerShell. Use `;` or make separate calls.
- Use `& "path\to\exe"` syntax to invoke executables with special paths.
- Set working directory via the `cwd` parameter, not `cd`.
