"""Cloud overlay post-gen: keep the image workflow only for the CI it belongs to."""

import shutil
from pathlib import Path

CI = "{{ cookiecutter.ci }}"

if CI != "github" and Path(".github").exists():
    shutil.rmtree(".github")
