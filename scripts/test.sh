#!/usr/bin/env sh
# Run the repository checks in Docker, so nothing has to be installed locally or in CI:
# tests + branch coverage + validation reports on current Python, then the tests on Python 3.9.
set -eu

repo_root=$(cd "$(dirname "$0")/.." && pwd)

run_checks() { # $1: Python version, the rest: arguments for ci/ci.py
    version=$1
    shift
    image="claude-skills-ci:py${version}"
    docker build --build-arg "PYTHON_VERSION=${version}" --tag "${image}" "${repo_root}/ci"
    docker run --rm --volume "${repo_root}:/repo:ro" "${image}" "$@"
}

run_checks 3.13 tests
run_checks 3.9 tests --no-coverage
