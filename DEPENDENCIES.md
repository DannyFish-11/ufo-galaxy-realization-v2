# UFO Galaxy Realization v2 - Dependency Management

## Overview

This document describes the dependency management strategy for the UFO Galaxy Realization v2 project.

## Python Version

- **Required**: Python 3.11+
- **Recommended**: Python 3.11.4 or later

## Dependency Files

### Core Dependency Files

| File | Purpose | Location |
|------|---------|----------|
| `requirements.txt` | Module-specific dependencies | Each submodule |
| `requirements-lock.txt` | Complete locked dependencies | Project root |

### Module-Specific Requirements

| Module | Path | Dependencies Count |
|--------|------|-------------------|
| AgentCPM Eval | `external/agentcpm/eval/eval_data/` | 49 packages |
| Learning System | `enhancements/learning/` | 16 packages |
| Multi-Device Coordination | `enhancements/multidevice/` | 17 packages |
| Dashboard Backend | `dashboard/backend/` | 5 packages |

## Version Pinning Strategy

### Principles

1. **All versions are pinned** using `==` operator for reproducibility
2. **Latest stable versions** are used as of the last update
3. **Compatibility verified** across modules where shared dependencies exist
4. **Security updates** should be applied promptly

### Version Format

```
package-name==MAJOR.MINOR.PATCH
```

### Update Schedule

- **Security patches**: As needed
- **Minor updates**: Monthly review
- **Major updates**: Quarterly review with full testing

## Dependency Categories

### Core Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| numpy | 2.4.2 | Numerical computing |
| scipy | 1.17.0 | Scientific computing |
| pydantic | 2.12.5 | Data validation |

### Web Framework

| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | 0.129.0 | Web API framework |
| uvicorn | 0.40.0 | ASGI server |
| websockets | 16.0 | WebSocket support |

### Machine Learning

| Package | Version | Purpose |
|---------|---------|---------|
| scikit-learn | 1.8.0 | ML algorithms |
| tensorflow | 2.19.0 | Deep learning |
| networkx | 3.6.1 | Graph analysis |

### Testing & Development

| Package | Version | Purpose |
|---------|---------|---------|
| pytest | 9.0.2 | Testing framework |
| black | 26.1.0 | Code formatting |
| mypy | 1.19.1 | Type checking |
| flake8 | 7.3.0 | Linting |

## Cross-Module Dependencies

### Shared Dependencies

The following packages are used across multiple modules:

| Package | Learning | MultiDevice | Dashboard |
|---------|----------|-------------|-----------|
| fastapi | 0.129.0 | 0.129.0 | 0.104.1 |
| uvicorn | 0.40.0 | 0.40.0 | 0.24.0 |
| pydantic | 2.12.5 | 2.12.5 | 2.5.0 |
| httpx | - | 0.28.1 | 0.25.1 |
| websockets | - | 16.0 | 12.0 |

**Note**: Dashboard uses older versions for stability. Consider upgrading to match other modules.

## Installation

### Install All Dependencies

```bash
# From project root
pip install -r requirements-lock.txt
```

### Install Module-Specific Dependencies

```bash
# Learning System
pip install -r enhancements/learning/requirements.txt

# Multi-Device Coordination
pip install -r enhancements/multidevice/requirements.txt

# Dashboard Backend
pip install -r dashboard/backend/requirements.txt
```

### Virtual Environment Setup

```bash
# Create virtual environment
python -m venv venv

# Activate
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements-lock.txt
```

## Updating Dependencies

### Check for Updates

```bash
pip list --outdated
```

### Update a Single Package

1. Edit the relevant `requirements.txt`
2. Update the version number
3. Test thoroughly
4. Update `requirements-lock.txt`

### Full Dependency Refresh

```bash
# Generate new lock file
pip freeze > requirements-lock.txt
```

## Security Considerations

1. **Regular audits**: Run `pip audit` to check for vulnerabilities
2. **Trusted sources**: Only install from PyPI or verified private repositories
3. **Pin hashes**: Consider using `pip-compile` with hash verification for production

## Compatibility Matrix

| Python Version | numpy | scipy | tensorflow | fastapi | Status |
|---------------|-------|-------|------------|---------|--------|
| 3.11 | 2.4.2 | 1.17.0 | 2.19.0 | 0.129.0 | ✅ Supported |
| 3.12 | 2.4.2 | 1.17.0 | 2.19.0 | 0.129.0 | ✅ Supported |

## Troubleshooting

### Common Issues

#### Version Conflicts

If you encounter version conflicts:

```bash
# Use constraint files
pip install -c constraints.txt -r requirements.txt
```

#### Platform-Specific Dependencies

Some packages may require platform-specific installation:

```bash
# For TensorFlow on Apple Silicon
pip install tensorflow-macos
pip install tensorflow-metal
```

## Changelog

### 2025-06-10 - Initial Version Pinning

- Pinned all dependencies to specific versions
- Created unified requirements-lock.txt
- Updated all modules to use latest stable versions

## Contact

For dependency-related questions or issues, contact the development team.
