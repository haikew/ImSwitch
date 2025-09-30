# UV Usage Guide for ImSwitch

This document provides guidance on using UV with ImSwitch for faster package management and reproducible builds.

## Installation

Install UV following the official instructions:

```bash
# macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## Development Workflow

### Setting up a development environment

```bash
# Clone the repository
git clone https://github.com/openUC2/ImSwitch.git
cd ImSwitch

# Create a virtual environment
uv venv

# Activate the environment
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate  # Windows

# Install ImSwitch in development mode
uv pip install -e .[PyQt5,dev]
```

### Lock Files for Reproducible Builds

UV supports lock files for ensuring reproducible builds across different environments:

```bash
# Generate a lock file (when available in future UV versions)
uv lock

# Install from lock file
uv sync
```

## Performance Benefits

UV provides significant performance improvements over pip:

- **Faster installations**: 10-100x faster package installation
- **Better dependency resolution**: More reliable resolution of package conflicts
- **Improved caching**: Intelligent caching reduces repeated downloads
- **Parallel downloads**: Multiple packages downloaded simultaneously
- **Better error messages**: More informative error reporting

## Migration from pip

UV is designed as a drop-in replacement for pip. Most pip commands work with `uv pip`:

```bash
# Old pip commands
pip install package
pip install -r requirements.txt
pip install -e .

# New UV commands
uv pip install package
uv pip install -r requirements.txt
uv pip install -e .
```

## CI/CD Integration

For GitHub Actions and CI systems, UV installation is straightforward:

```yaml
- name: Install UV
  run: curl -LsSf https://astral.sh/uv/install.sh | sh

- name: Install dependencies
  run: |
    export PATH="$HOME/.local/bin:$PATH"
    uv pip install -e .[PyQt5]
```

## Troubleshooting

### Common Issues

1. **UV not found**: Ensure UV is in your PATH after installation
2. **Package conflicts**: UV's resolver is more strict than pip - this usually indicates real dependency issues
3. **Cache issues**: Clear UV cache with `uv cache clean` if needed

### Getting Help

- UV Documentation: https://docs.astral.sh/uv/
- ImSwitch Issues: https://github.com/openUC2/ImSwitch/issues