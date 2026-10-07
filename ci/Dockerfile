# Toolbox for the repository checks (scripts/test.sh): Python 3.9, git and coverage. The repo is
# mounted at /repo when the container runs, never copied in.
FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GIT_OPTIONAL_LOCKS=0

# safe.directory: the mounted repo is owned by another user than the container's root.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install coverage \
    && git config --system --add safe.directory /repo

WORKDIR /repo
ENTRYPOINT ["python3", "ci/ci.py"]
