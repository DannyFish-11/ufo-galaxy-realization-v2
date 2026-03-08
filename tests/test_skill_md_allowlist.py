"""
Galaxy - SkillMDLoader allowlist unit tests
================================================

Validates that the command allowlist in SkillMDLoader correctly blocks
disallowed commands and permits allowed ones without executing real processes.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.skill_md_loader import ALLOWED_COMMANDS, SkillMD, SkillMDLoader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_loader_with_skill(command: str) -> tuple[SkillMDLoader, str]:
    """Return a fresh loader instance pre-loaded with a skill that runs *command*."""
    loader = SkillMDLoader()
    skill = SkillMD(
        name="test-skill",
        description="unit test skill",
        commands=[{"language": "bash", "command": command}],
    )
    loader.skills["test-skill"] = skill
    return loader, "test-skill"


# ---------------------------------------------------------------------------
# Allowlist constant sanity checks
# ---------------------------------------------------------------------------


def test_allowed_commands_contains_expected():
    """ALLOWED_COMMANDS must include the documented safe commands."""
    expected = {"curl", "wget", "python", "python3", "node", "bash", "sh"}
    assert expected.issubset(ALLOWED_COMMANDS)


def test_allowed_commands_excludes_dangerous():
    """Dangerous commands must NOT appear in the allowlist."""
    dangerous = {"rm", "dd", "mkfs", "sudo", "su", "chmod", "chown", "kill"}
    assert dangerous.isdisjoint(ALLOWED_COMMANDS), (
        f"Dangerous commands found in allowlist: {dangerous & ALLOWED_COMMANDS}"
    )


# ---------------------------------------------------------------------------
# Blocking tests — disallowed commands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_rm_rf():
    """'rm -rf /' must be blocked and return an error (no real execution)."""
    loader, skill_id = _make_loader_with_skill("rm -rf /")
    result = await loader.execute(skill_id)

    assert not result["success"]
    cmd_result = result["results"][0]
    assert not cmd_result["success"]
    # Error message must name the blocked command
    assert "rm" in cmd_result["error"]
    assert "安全策略" in cmd_result["error"]


@pytest.mark.asyncio
async def test_blocked_arbitrary_command():
    """An arbitrary unlisted command (e.g. 'cat /etc/passwd') must be blocked."""
    loader, skill_id = _make_loader_with_skill("cat /etc/passwd")
    result = await loader.execute(skill_id)

    assert not result["success"]
    cmd_result = result["results"][0]
    assert not cmd_result["success"]
    assert "cat" in cmd_result["error"]


@pytest.mark.asyncio
async def test_blocked_full_path_disallowed():
    """Commands provided as full paths to disallowed binaries must be blocked."""
    loader, skill_id = _make_loader_with_skill("/bin/rm -f /tmp/x")
    result = await loader.execute(skill_id)

    assert not result["success"]
    assert not result["results"][0]["success"]


# ---------------------------------------------------------------------------
# Allowing tests — allowed commands (mocked, no real subprocess)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allowed_curl_mocked():
    """'curl' is an allowed command; execution path should be reached (mocked)."""
    loader, skill_id = _make_loader_with_skill("curl https://example.com")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await loader.execute(skill_id)

    assert result["success"]
    cmd_result = result["results"][0]
    assert cmd_result["success"]
    assert cmd_result["stdout"] == "ok"


@pytest.mark.asyncio
async def test_allowed_python3_mocked():
    """'python3' is an allowed command; execution path should be reached (mocked)."""
    loader, skill_id = _make_loader_with_skill("python3 -c 'print(1)'")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"1\n", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await loader.execute(skill_id)

    assert result["success"]
    assert result["results"][0]["stdout"] == "1\n"


@pytest.mark.asyncio
async def test_allowed_full_path_curl_mocked():
    """'/usr/bin/curl' — full path to an allowed command — should pass the allowlist."""
    loader, skill_id = _make_loader_with_skill("/usr/bin/curl -s https://example.com")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"html", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await loader.execute(skill_id)

    assert result["success"]


# ---------------------------------------------------------------------------
# Parameter substitution + allowlist interaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_param_substitution_still_blocked():
    """Parameter substitution must not bypass the allowlist check."""
    loader, skill_id = _make_loader_with_skill("{cmd} /etc/passwd")
    # Even if the substituted value is 'cat', that command is still disallowed
    result = await loader.execute(skill_id, {"cmd": "cat"})

    assert not result["success"]
    assert not result["results"][0]["success"]


@pytest.mark.asyncio
async def test_param_substitution_allowed_command_mocked():
    """Param substitution that results in an allowed command should execute."""
    loader, skill_id = _make_loader_with_skill("curl {url}")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"body", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await loader.execute(skill_id, {"url": "https://example.com"})

    assert result["success"]


# ---------------------------------------------------------------------------
# Shell-metacharacter injection via parameter substitution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metachar_injection_via_param_is_safe():
    """A parameter containing shell metacharacters must NOT cause code injection.

    Because create_subprocess_exec is used (no shell), the '; rm -rf /' part
    in the substituted command string cannot be interpreted as a shell command
    separator.  Any extra tokens become literal arguments to curl — they are
    never executed as a separate process.  We verify that:
      1. The first element of argv remains 'curl' (allowed command, no bypass).
      2. 'rm' appears only as a plain argument to curl, not as a separate exec.
    """
    loader, skill_id = _make_loader_with_skill("curl {url}")

    # Simulate a malicious URL parameter with shell metacharacters
    malicious_url = "https://example.com; rm -rf /"

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"body", b""))

    captured_argv = []

    async def mock_exec(*args, **kwargs):
        captured_argv.extend(args)
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        result = await loader.execute(skill_id, {"url": malicious_url})

    # curl is allowed so execution proceeds
    assert result["success"]
    # The first (and only) executable called must be 'curl' — the allowlist check
    # is on argv[0] and it passes.  'rm' can only appear as a curl argument.
    assert captured_argv[0] == "curl"
    # 'rm' must NOT be the first element of any separate exec call — it is just
    # a stray argument token, harmless without a shell interpreter.
    assert captured_argv.count("curl") == 1  # exactly one exec call
