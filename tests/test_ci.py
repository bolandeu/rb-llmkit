"""Воркфлоу Gitea Actions: гейт стандарта запускается в CI (Standard, CI), и импорт пакета остаётся лёгким."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".gitea" / "workflows" / "ci.yml"
# Тег шаблона cli-generator, по которому приведён пакет.
TEMPLATE_TAG = "v1.27.3"
GATE = (
    'uvx --from "git+https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator.git'
    f'@{TEMPLATE_TAG}#subdirectory=gate" rb-release check'
)


def test_no_github_workflow() -> None:
    assert not (ROOT / ".github").exists()


def test_workflow_runs_the_gate_on_the_docker_runner() -> None:
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["gate"]
    assert job["runs-on"] == "docker"
    assert "ci-cache:/cache" in job["container"]["volumes"]
    checkout = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0
    assert job["steps"][-1]["run"].strip() == GATE


def _steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["gate"]["steps"]


def test_scanners_are_installed_before_the_gate_at_pinned_versions() -> None:
    steps = _steps()
    gate = next(i for i, step in enumerate(steps) if str(step.get("run", "")).strip() == GATE)
    scripts = [step["run"] for step in steps[:gate] if "run" in step]
    for tool in ("osv-scanner", "gitleaks"):
        script = next(s for s in scripts if f"/cache/bin/{tool}-" in s)
        urls = re.findall(r"https://github\.com/\S+", script)
        assert urls
        assert all(re.search(r"/download/v\d+\.\d+\.\d+/", url) for url in urls)
        assert "latest" not in script


def test_scanners_are_cached_per_pinned_version() -> None:
    script = next(step["run"] for step in _steps() if "gitleaks" in step.get("run", ""))
    lines = script.splitlines()
    for tool, version in (("osv-scanner", "2.7.0"), ("gitleaks", "8.30.1")):
        cached = f"/cache/bin/{tool}-{version}"
        var = next(line.split("=")[0] for line in lines if line.endswith(f"={cached}"))
        download = next(line for line in lines if line.startswith(f"[ -x ${var} ] ||"))
        assert f"/download/v{version}/" in download
        assert f"ln -sf ${var} /usr/local/bin/{tool}" in lines


def test_import_stays_light_and_free_of_the_old_clients() -> None:
    """Импорт пакета не тянет LiteLLM и Instructor и остаётся под 300 мс (AGENTS.md)."""
    script = (
        "import json, sys, time\n"
        "started = time.perf_counter()\n"
        "import llmkit\n"
        "print(json.dumps({\n"
        "    'seconds': time.perf_counter() - started,\n"
        "    'heavy': sorted(\n"
        "        name for name in sys.modules\n"
        "        if name.split('.')[0] in ('litellm', 'instructor')\n"
        "    ),\n"
        "}))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)  # noqa: S603
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["heavy"] == []
    assert report["seconds"] < 0.3
