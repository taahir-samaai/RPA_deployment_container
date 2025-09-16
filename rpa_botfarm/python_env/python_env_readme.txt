# Python Environment Setup

This directory contains offline Python packages for deployment in secure enterprise environments.

## Directory Structure
```
python_env/
├── windows_libraries/          # Windows worker packages (.whl files)
├── redhat_libraries/           # Red Hat orchestrator packages (.whl + .tar.gz)
├── windows_requirements.in     # Windows dependencies
├── redhat_requirements.in      # Red Hat dependencies
└── README.md                   # This file
```

## Windows 11 Environment (Worker + Automation)

### Create Virtual Environment
```cmd
cd C:\path\to\your\project
python -m venv venv
venv\Scripts\activate
```

### Install from Offline Packages
```cmd
pip install --no-index --find-links python_env\windows_libraries -r python_env\windows_requirements.in
```

### Verify Installation
```cmd
python -c "import fastapi, selenium, requests; print('Windows packages installed successfully')"
```

## Red Hat Enterprise Linux 8.10 (Orchestrator Only)

### Create Virtual Environment
```bash
cd /path/to/your/project
python3.12 -m venv venv
source venv/bin/activate
```

### Install from Offline Packages
```bash
pip install --no-index --find-links python_env/redhat_libraries -r python_env/redhat_requirements.in
```

### Verify Installation
```bash
python3.12 -c "import fastapi, sqlalchemy, requests; print('Red Hat packages installed successfully')"
```

## Package Management Commands

### Update Packages (on machine with internet)
```bash
# Download latest Windows packages
pip download --dest windows_libraries --platform win_amd64 --python-version 3.12 --implementation cp --abi cp312 --only-binary=:all: -r windows_requirements.in

# Download latest Red Hat packages
pip download --dest redhat_libraries --python-version 3.12 bcrypt pyjwt
pip download --dest redhat_libraries --platform linux_x86_64 --python-version 3.12 --no-deps fastapi uvicorn pydantic requests apscheduler sqlalchemy tenacity python-dotenv
```

### List Installed Packages
```bash
pip list
```

### Generate Requirements Lock File
```bash
pip freeze > requirements-lock.txt
```

## Deployment Notes

- **Windows**: All packages are pre-compiled wheels (.whl) for faster installation
- **Red Hat**: Most packages are wheels, `bcrypt` is source (.tar.gz) and will compile during installation
- **No Internet Required**: All installations work offline using `--no-index --find-links`
- **Python Version**: Packages are compatible with Python 3.12.x

## Troubleshooting

### Permission Errors (Windows)
```cmd
# Run as Administrator or use --user flag
pip install --user --no-index --find-links python_env\windows_libraries -r python_env\windows_requirements.in
```

### Build Tools Missing (Red Hat)
```bash
# If bcrypt compilation fails, install build tools
sudo yum groupinstall "Development Tools"
sudo yum install python3-devel
```

### Verify Package Integrity
```bash
# Check for corrupted downloads
pip check
```