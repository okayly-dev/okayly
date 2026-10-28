import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_dockerfile_has_runtime_safety_settings():
    dockerfile = read("Dockerfile")

    assert re.search(r"(?m)^USER\s+\S+", dockerfile)
    assert "EXPOSE 8000" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert not re.search(r"(?im)^COPY\s+.*\.env", dockerfile)


def test_dockerignore_excludes_local_and_secret_files():
    ignored = set(read(".dockerignore").splitlines())

    assert {".env", ".git", ".venv"} <= ignored


def test_compose_publishes_only_caddy_ports():
    compose = read("docker-compose.yml")
    app_block, caddy_block = compose.split("  caddy:", 1)

    assert "ports:" not in app_block
    assert '"80:80"' in caddy_block
    assert '"443:443"' in caddy_block
    assert not re.search(r'"(?:8000|\d+):8000"', compose)


def test_example_environment_has_an_empty_key_and_no_key_like_values():
    example = read("deploy/env.example")
    values = {}
    for line in example.splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value

    assert values["MODEL_API_KEY"] == ""
    assert not any(re.fullmatch(r"[A-Za-z0-9_-]{24,}", value) for value in values.values())


def test_deployment_files_contain_no_private_or_machine_specific_data():
    paths = [ROOT / "Dockerfile", ROOT / "docker-compose.yml", *sorted((ROOT / "deploy").glob("**/*"))]
    forbidden_brand = "odo" + "vista"
    secret_assignment = re.compile(r"(?i)(?:api[_-]?key|secret|token|password)[ \t]*=[ \t]*\S+")

    for path in paths:
        if not path.is_file():
            continue
        contents = path.read_text(encoding="utf-8")
        assert "/" + "Users/" not in contents
        assert forbidden_brand not in contents.lower()
        assert not secret_assignment.search(contents)
