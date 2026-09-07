"""compose 起不来的时候,得说清楚是**什么**起不来。

基础设施那一行原来只有一句 ``Docker 启动异常 (rc=1)，详情见 logs/docker.log``。
真跑下来同一句话底下至少三种事,下一步动作完全不同:

* ``.env`` 缺必填变量 —— compose 在插值阶段就拒了,跟 Docker 一点关系没有,
  而那句话把人指向了 Docker(这是"说的和现实相反");
* 拉不到镜像 —— 守护进程好好的,是网络的事;
* 端口被占 —— 本机已经有东西占着。

这一片盯住:三类各自认得出、认不出时**明说没判定**(不猜一个最像的)、
以及给出的下一步跟类别对得上。
"""

from __future__ import annotations

import pytest

from launcher.compose_failures import (
    FAIL_ADVICE,
    FAIL_IMAGE_PULL,
    FAIL_MISSING_ENV,
    FAIL_PORT_IN_USE,
    FAIL_UNKNOWN,
    classify_compose_failure,
    describe_compose_failure,
    read_compose_log_tail,
)

# 真跑里 compose 吐的原话(截断)。
REAL_MISSING_ENV = (
    "error while interpolating services.minio.environment.[]: required variable "
    "MINIO_SECRET_KEY is missing a value: MINIO_SECRET_KEY 必须设置（见 .env.example）"
)
REAL_IMAGE_PULL = (
    " Image nats:2.10-alpine Pulling \n"
    " Image redis:7-alpine Pulling \n"
    "failed to copy: httpReadSeeker: failed open: failed to do request: Get "
    '"https://production.cloudfront.docker.com/registry-v2/...": Forbidden'
)


class TestMissingEnv:
    def test_the_real_line_is_recognised(self):
        kind, keys = classify_compose_failure(REAL_MISSING_ENV)
        assert kind == FAIL_MISSING_ENV
        assert keys == ["MINIO_SECRET_KEY"]

    def test_it_names_every_missing_key(self):
        text = (
            "required variable NEO4J_PASSWORD is missing a value: x\n"
            "required variable MONGODB_URI is missing a value: y\n"
        )
        _, keys = classify_compose_failure(text)
        assert keys == ["NEO4J_PASSWORD", "MONGODB_URI"]

    def test_duplicate_keys_are_listed_once(self):
        text = "required variable NEO4J_PASSWORD is missing a value: x\n" * 3
        _, keys = classify_compose_failure(text)
        assert keys == ["NEO4J_PASSWORD"]

    def test_the_message_says_it_is_not_docker(self):
        """这一句是重点:人会去查 Docker,而真正该改的是 .env。"""
        msg = describe_compose_failure(REAL_MISSING_ENV)
        assert "MINIO_SECRET_KEY" in msg
        assert ".env" in msg
        assert "不是 Docker 的问题" in msg

    def test_missing_env_wins_over_pull_noise(self):
        """插值失败时根本没开始拉镜像;先匹配到镜像那一类就会把人指错方向。"""
        kind, _ = classify_compose_failure(REAL_IMAGE_PULL + "\n" + REAL_MISSING_ENV)
        assert kind == FAIL_MISSING_ENV

    def test_many_keys_are_truncated_not_dumped(self):
        text = "".join(f"required variable K{i} is missing a value: x\n" for i in range(9))
        msg = describe_compose_failure(text)
        assert "…" in msg


class TestImagePull:
    def test_the_real_forbidden_line_is_recognised(self):
        kind, _ = classify_compose_failure(REAL_IMAGE_PULL)
        assert kind == FAIL_IMAGE_PULL

    @pytest.mark.parametrize(
        "line",
        [
            "error pulling image configuration",
            "manifest unknown",
            "pull access denied for foo/bar",
            "toomanyrequests: rate limit",
            "dial tcp: lookup registry-1.docker.io: no such host",
            "net/http: TLS handshake timeout",
        ],
    )
    def test_the_usual_pull_failures(self, line):
        assert classify_compose_failure(line)[0] == FAIL_IMAGE_PULL

    def test_the_message_clears_docker_of_blame(self):
        msg = describe_compose_failure(REAL_IMAGE_PULL)
        assert "镜像" in msg
        assert "Docker 本身是好的" in msg

    def test_runtime_name_is_honoured(self):
        """跑 Podman 的机器上不该看到 "Docker"。"""
        assert "Podman" in describe_compose_failure(REAL_IMAGE_PULL, runtime_name="Podman")


class TestPortInUse:
    def test_bind_failure_is_recognised(self):
        kind, ports = classify_compose_failure(
            "Error starting userland proxy: bind 0.0.0.0:4222 address already in use"
        )
        assert kind == FAIL_PORT_IN_USE
        assert ports == ["4222"]

    def test_port_shows_up_in_the_message(self):
        msg = describe_compose_failure("bind 0.0.0.0:6379 address already in use")
        assert "6379" in msg
        assert "端口" in msg

    def test_bare_address_in_use_still_classifies(self):
        """认得出类别但拿不到端口号 —— 类别照给,端口留空,不编一个。"""
        kind, ports = classify_compose_failure("address already in use")
        assert kind == FAIL_PORT_IN_USE
        assert ports == []


class TestUnknownStaysUnknown:
    @pytest.mark.parametrize("text", ["", "   \n\n", "something nobody has seen before"])
    def test_unrecognised_is_not_guessed(self, text):
        assert classify_compose_failure(text) == (FAIL_UNKNOWN, [])

    def test_the_message_admits_it_did_not_decide(self):
        """认不出就说认不出。硬安一个"最像"的,比不说更费时间。"""
        msg = describe_compose_failure("something nobody has seen before")
        assert "未能判定" in msg
        assert "logs/docker.log" in msg

    def test_empty_log_is_not_reported_as_a_cause(self):
        """日志读不到不是一种失败原因。"""
        assert classify_compose_failure("")[0] == FAIL_UNKNOWN


class TestTheMessageItself:
    def test_no_return_code_in_the_message(self):
        """``rc=1`` 对着屏幕的人没有任何意义,它只是"失败了"的另一种写法。"""
        for text in (REAL_MISSING_ENV, REAL_IMAGE_PULL, "address already in use", "???"):
            assert "rc=" not in describe_compose_failure(text)

    def test_every_category_has_a_next_step(self):
        for kind in (FAIL_MISSING_ENV, FAIL_IMAGE_PULL, FAIL_PORT_IN_USE, FAIL_UNKNOWN):
            assert FAIL_ADVICE[kind].strip(), f"{kind} 没有下一步"

    def test_the_three_known_categories_read_differently(self):
        msgs = {
            describe_compose_failure(REAL_MISSING_ENV),
            describe_compose_failure(REAL_IMAGE_PULL),
            describe_compose_failure("bind 0.0.0.0:4222 address already in use"),
        }
        assert len(msgs) == 3, "不同的原因给了同一句话,等于没分类"


class TestReadingTheLog:
    def test_reads_the_tail(self, tmp_path):
        p = tmp_path / "docker.log"
        p.write_text("x" * 50000 + REAL_MISSING_ENV, encoding="utf-8")
        assert "MINIO_SECRET_KEY" in read_compose_log_tail(str(p))

    def test_short_file_is_read_whole(self, tmp_path):
        p = tmp_path / "docker.log"
        p.write_text(REAL_IMAGE_PULL, encoding="utf-8")
        assert classify_compose_failure(read_compose_log_tail(str(p)))[0] == FAIL_IMAGE_PULL

    def test_missing_file_is_empty_not_an_error(self, tmp_path):
        assert read_compose_log_tail(str(tmp_path / "nope.log")) == ""

    def test_no_path_is_empty(self):
        assert read_compose_log_tail(None) == ""

    def test_undecodable_bytes_do_not_crash(self, tmp_path):
        p = tmp_path / "docker.log"
        p.write_bytes(b"\xff\xfe garbage " + REAL_IMAGE_PULL.encode())
        assert classify_compose_failure(read_compose_log_tail(str(p)))[0] == FAIL_IMAGE_PULL


class TestItIsActuallyWiredIn:
    def test_the_status_line_uses_the_classifier(self):
        """构造得出来 ≠ 用上了。这条盯的是它真的接在那一行上。"""
        import inspect

        import launcher.services as svc

        src = inspect.getsource(svc)
        assert "describe_compose_failure" in src

    def test_the_old_opaque_message_is_gone(self):
        import inspect

        import launcher.services as svc

        code = [ln for ln in inspect.getsource(svc).splitlines() if not ln.lstrip().startswith("#")]
        assert not any("启动异常 (rc=" in ln for ln in code)
