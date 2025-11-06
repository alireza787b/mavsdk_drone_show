# Contributing to MAVSDK Drone Show

Thank you for your interest in contributing to MAVSDK Drone Show! This document provides guidelines and instructions for contributing.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Documentation](#documentation)
- [Testing](#testing)
- [Questions?](#questions)

---

## Code of Conduct

By participating in this project, you agree to:

- Be respectful and inclusive
- Welcome newcomers and help them learn
- Focus on what is best for the community
- Show empathy towards other community members

---

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports:
1. Check existing issues to avoid duplicates
2. Collect relevant information (version, environment, logs)
3. Provide clear reproduction steps

Create an issue with:
- Clear, descriptive title
- Detailed description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version, etc.)
- Relevant logs or screenshots

### Suggesting Features

Feature suggestions are welcome! Please:
1. Check if the feature already exists or is planned
2. Provide clear use case and benefits
3. Consider implementation complexity
4. Discuss in an issue before implementing

### Code Contributions

We welcome:
- Bug fixes
- New features
- Performance improvements
- Documentation improvements
- Test coverage improvements
- Code refactoring

---

## Development Setup

### Prerequisites

- **Python:** 3.11, 3.12, or 3.13
- **Node.js:** 14.x or higher
- **Git:** Latest version
- **Docker:** (for SITL testing)

### Setup Steps

1. **Fork the repository**
   ```bash
   # Fork on GitHub, then clone your fork
   git clone https://github.com/YOUR_USERNAME/mavsdk_drone_show.git
   cd mavsdk_drone_show
   ```

2. **Add upstream remote**
   ```bash
   git remote add upstream https://github.com/alireza787b/mavsdk_drone_show.git
   ```

3. **Create a branch**
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/issue-description
   ```

4. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Install frontend dependencies**
   ```bash
   cd app/dashboard/drone-dashboard
   npm install
   cd ../../..
   ```

---

## Pull Request Process

### 1. Before Creating a PR

- [ ] Create your feature/fix in a new branch
- [ ] Test your changes in SITL environment
- [ ] Update documentation if needed
- [ ] Add/update tests if applicable
- [ ] Run code quality checks

### 2. Creating the PR

1. **Commit your changes**
   ```bash
   git add .
   git commit -m "feat: add new feature X"
   # or
   git commit -m "fix: resolve issue with Y"
   ```

   **Commit message format:**
   - `feat:` - New feature
   - `fix:` - Bug fix
   - `docs:` - Documentation changes
   - `refactor:` - Code refactoring
   - `test:` - Test additions/changes
   - `chore:` - Build/tooling changes

2. **Push to your fork**
   ```bash
   git push origin feature/your-feature-name
   ```

3. **Open a Pull Request**
   - Go to GitHub and click "New Pull Request"
   - Target: `main-candidate` branch
   - Fill out the PR template completely
   - Link related issues

### 3. PR Review Process

- Maintainers will review your PR
- Address any requested changes
- Once approved, maintainers will merge

### 4. After Merging

- Delete your feature branch
- Pull latest changes from upstream
  ```bash
  git checkout main-candidate
  git pull upstream main-candidate
  ```

---

## Coding Standards

### Python

- Follow **PEP 8** style guide
- Use meaningful variable and function names
- Add docstrings to functions and classes
- Keep functions focused and concise
- Avoid global variables when possible

**Example:**
```python
def calculate_trajectory_point(position, velocity, time):
    """
    Calculate trajectory point at given time.

    Args:
        position (tuple): Initial (x, y, z) position
        velocity (tuple): Velocity vector (vx, vy, vz)
        time (float): Time in seconds

    Returns:
        tuple: Position at given time (x, y, z)
    """
    x = position[0] + velocity[0] * time
    y = position[1] + velocity[1] * time
    z = position[2] + velocity[2] * time
    return (x, y, z)
```

### JavaScript/React

- Use functional components with hooks
- Follow existing code style
- Use meaningful component and variable names
- Add PropTypes for type checking
- Keep components focused and reusable

**Example:**
```javascript
import React from 'react';
import PropTypes from 'prop-types';

const DroneStatus = ({ droneId, battery, position }) => {
  return (
    <div className="drone-status">
      <h3>Drone {droneId}</h3>
      <p>Battery: {battery}%</p>
      <p>Position: {position.x}, {position.y}, {position.z}</p>
    </div>
  );
};

DroneStatus.propTypes = {
  droneId: PropTypes.number.isRequired,
  battery: PropTypes.number.isRequired,
  position: PropTypes.shape({
    x: PropTypes.number,
    y: PropTypes.number,
    z: PropTypes.number
  }).isRequired
};

export default DroneStatus;
```

### CSS

- Use CSS variables for theming
- Support both light and dark modes
- Follow existing naming conventions
- Keep selectors specific but not over-specific

---

## Documentation

### When to Update Documentation

Update documentation when you:
- Add a new feature
- Change existing behavior
- Fix a significant bug
- Add/change configuration options
- Modify APIs or interfaces

### Documentation Locations

- **README.md** - Project overview (edit sparingly)
- **docs/** - Comprehensive guides
- **CHANGELOG.md** - Version changes
- **Code comments** - Inline documentation

### Documentation Style

- Use clear, concise language
- Provide examples when helpful
- Use proper markdown formatting
- Include code blocks with syntax highlighting
- Link to related documentation

---

## Testing

### SITL Testing

All changes should be tested in SITL environment:

```bash
# Follow SITL setup guide
# docs/guides/sitl-comprehensive.md

# Test your changes with:
# - Single drone
# - Multiple drones (5-10)
# - Various mission types
```

### Test Checklist

- [ ] Python code runs without errors
- [ ] Frontend builds successfully
- [ ] No new ESLint warnings
- [ ] Features work as expected in SITL
- [ ] No regression in existing features
- [ ] Documentation is accurate

---

## Version Management

If your changes affect version numbers:

1. **Don't bump version yourself** - Maintainers handle this
2. **Update CHANGELOG.md** - Add entry under "Unreleased"
3. **Follow versioning guide** - See [docs/VERSIONING.md](docs/VERSIONING.md)

---

## Questions?

### Get Help

- **Documentation:** Start with [docs/README.md](docs/README.md)
- **GitHub Issues:** Search existing issues or create new one
- **Email:** p30planets@gmail.com
- **LinkedIn:** [Alireza Ghaderi](https://www.linkedin.com/in/alireza787b/)

### Response Time

- We aim to respond to issues and PRs within 1-2 weeks
- Simple fixes may be merged faster
- Complex features may take longer to review

---

## Recognition

Contributors will be recognized:
- In release notes for significant contributions
- In project documentation
- Through GitHub's contributor statistics

---

## License

By contributing, you agree that your contributions will be licensed under the same license as the project (CC BY-SA 4.0).

---

**Thank you for contributing to MAVSDK Drone Show!** 🚁

Your contributions help make drone swarm technology more accessible and robust for everyone.

---

© 2025 Alireza Ghaderi | Licensed under CC BY-SA 4.0
