#!/usr/bin/env sh
# Run all repository checks (tests, branch coverage, validation reports) in Docker, so nothing
# has to be installed locally or on the CI runner. Python and tools come from ci/Dockerfile.
set -eu

repo_root=$(cd "$(dirname "$0")/.." && pwd)
image="claude-skills-ci"

docker build --tag "${image}" "${repo_root}/ci"
docker run --rm --volume "${repo_root}:/repo:ro" "${image}" tests
