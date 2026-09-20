"""托盘里那份「本机模型实测账」，每一个数都得说得出它是哪来的。

## 这道门为什么存在

关于一个型号，仓库里同时存着**四种来路完全不同**的数：目录声明的权重、磁盘上
那个 GGUF 的真实大小、量过一次写进源码的驻留量、这台机器自己量的 KV 单价。

把它们并排摆出来是有用的 —— 排查「模型带不动」时第一个要问的就是它们。但并排
摆也带来一种特有的坏法：**四个数字挨在一起，看上去就都像是量出来的。**

这道门守的就是这一点：没量过的必须写着「未量过」，不能写成 0，也不能拿另一个
来路的数顶上。

## 写这份报告时我自己就犯了一次

第一版直接拿 ``effective_weight_mb(tag)`` 的返回值当「磁盘上那一份」。而那个函数
**查不到文件时会退回目录声明** —— 这是它该有的行为。照着写的结果是：一台一个
模型都没下载的机器，报告把目录里的数原样抄成了「磁盘上那一份」。

而这份报告存在的**全部意义**就是把这两者分开。所以下面第一条钉的就是它。
"""

from __future__ import annotations

import re
from pathlib import Path

import core.model_measurements_report as mr
from core.model_measurements_report import UNKNOWN, ModelRow, measurement_rows, render_report

_ROOT = Path(__file__).resolve().parents[1]


class TestAnUnmeasuredNumberSaysSo:
    def test_a_model_that_is_not_downloaded_has_no_size_on_disk(self, monkeypatch) -> None:
        """**这一条是这道门的判别点。**

        没下载就是没下载。拿目录声明顶上去，这份报告就失去了它唯一的用处。
        """
        import core.local_model_backends as lmb

        monkeypatch.setattr(lmb, "resolve_gguf_path", lambda _t: None)
        for row in measurement_rows():
            assert row.weight_on_disk_mb is None, (
                f"{row.tag} 没下载，报告却说磁盘上有 {row.weight_on_disk_mb} MB —— "
                "那是目录声明被抄了过来。这份报告的全部意义就是把这两者分开。"
            )

    def test_a_downloaded_model_reports_the_real_file(self, monkeypatch) -> None:
        """下载过就该报真文件 —— 否则「换过量化」这条信息永远浮不上来。"""
        import core.local_model_backends as lmb
        import core.model_catalog as mc

        monkeypatch.setattr(lmb, "resolve_gguf_path", lambda _t: "/tmp/fake.gguf")
        monkeypatch.setattr(mc, "effective_weight_mb", lambda _t: 4321)
        rows = {r.tag: r for r in measurement_rows()}
        assert rows["gemma4:12b"].weight_on_disk_mb == 4321

    def test_swapping_the_quantization_is_called_out(self) -> None:
        """差值本身就是「你换过量化」这条信息 —— 默默用掉等于把它咽了。"""
        row = ModelRow(tag="x", requires_gpu=True, declared_weight_mb=8000, weight_on_disk_mb=6720)
        assert row.weight_diverged(), "差了 16% 都不吭声"
        near = ModelRow(tag="x", requires_gpu=True, declared_weight_mb=8000, weight_on_disk_mb=8200)
        assert not near.weight_diverged(), "差百分之几就喊，那是噪音（GGUF 头部与对齐填充）"

    def test_a_fallback_residency_is_not_passed_off_as_measured(self) -> None:
        """``runtime_mb()`` 没量过时会退回权重值。那是**保守**，不是**量过**。

        两者写成同一句话的话，「该去量一下」这件事就永远不会被想起来。
        """
        rows = {r.tag: r for r in measurement_rows()}
        measured = rows["openbmb/minicpm-o4.5"]  # 目录里量过 11000
        fell_back = rows["gemma4:12b"]  # 目录里是 0 → 退回权重
        assert "量过" in measured.runtime_source and "未量过" not in measured.runtime_source
        assert (
            "未量过" in fell_back.runtime_source
        ), f"退回权重却写成「{fell_back.runtime_source}」—— 那就再没人会去量它了"

    def test_not_downloaded_reads_differently_from_not_measured(self, monkeypatch) -> None:
        """「还没下载」和「没量过」在屏幕上必须长得不一样。

        两者都是"这一格没有数"，但只有前一种**能动手**：看到「还没下载」的人知道
        下一步是去下载，看到「未量过」的人只会以为哪个探测没跑起来。用同一个词盖住
        两种情况，等于把那条可操作的信息咽掉 —— 跟把 0 写成"量出来是零"是同一种病。
        """
        import core.local_model_backends as lmb
        import core.model_catalog as mc

        monkeypatch.setattr(lmb, "resolve_gguf_path", lambda _t: None)
        none_here = render_report(measurement_rows(), budget_mb=8192)
        disk_lines = [ln for ln in none_here.split("\n") if "磁盘上那一份" in ln]
        assert disk_lines, "报告里没有磁盘那一栏了"
        for line in disk_lines:
            assert mr.NOT_DOWNLOADED in line, (
                f"一个都没下载，磁盘那一栏却写着「{line.strip()}」—— "
                "「没量过」读的人会去查探测，「还没下载」读的人会去下载。"
            )

        # 判别点：下载过的那一行**不许**还写着「还没下载」，否则上面那条只要
        # 把这一栏写死成那个词就永远绿。
        monkeypatch.setattr(lmb, "resolve_gguf_path", lambda _t: "/tmp/fake.gguf")
        monkeypatch.setattr(mc, "effective_weight_mb", lambda _t: 4321)
        have_it = render_report(measurement_rows(), budget_mb=8192)
        for line in [ln for ln in have_it.split("\n") if "磁盘上那一份" in ln]:
            assert mr.NOT_DOWNLOADED not in line, f"文件就在磁盘上，却还写着还没下载：{line.strip()}"
            assert "4.2 GB" in line, f"下载过却没报真文件大小：{line.strip()}"

    def test_zero_is_never_printed_as_a_number(self) -> None:
        """没有的数写成 0，会被读成「量出来是零」。"""
        assert mr._fmt_mb(None) == UNKNOWN
        assert mr._fmt_mb(0) == UNKNOWN
        assert mr._fmt_mb(-5) == UNKNOWN
        assert mr._fmt_mb(512) == "512 MB"
        assert mr._fmt_mb(8192) == "8.0 GB"


class TestTheReportRefusesToGuess:
    def test_no_hardware_means_no_verdict(self, monkeypatch) -> None:
        """探不到硬件 ≠ 装不下。**不给结论**，而不是给一个「ok」或者「装不下」。

        这一条盯的是**准入压根没被问过**，不只是"结果恰好是 None"。

        第一版写成「fit 是 None 就算过」——而那时把守卫拆掉之后，``int(None)`` 抛的
        TypeError 被 except 兜住，fit 照样是 None，判据照样绿。**保护实际来自异常处理，
        不是那个显式判断**；哪天 fit_detail 变得能容忍 None，守卫就悄悄没了而没人知道。
        """
        called: list = []

        import core.routes.models as rm

        def _spy(spec, has_gpu, budget_mb):  # noqa: ANN001
            called.append(getattr(spec, "tag", "?"))
            return {"fit": "ok"}

        monkeypatch.setattr(rm, "fit_detail", _spy)

        # **两者都缺**：这一种其实分不出守卫有没有生效 —— 守卫拆掉之后
        # ``int(None)`` 会先抛 TypeError，被 except 兜住，fit 照样是 None、
        # 监视器照样没被调到。所以它只是个起点，判别点在下面那一种。
        rows = measurement_rows(budget_mb=None, has_gpu=None)
        assert not called, f"没探硬件却还是去问了准入：{called}"

        # **判别点：只缺一半。** 预算有、显卡那一位不知道 —— 算术全通得过，
        # 于是守卫要是没了，监视器一定会被调到。
        called.clear()
        half = measurement_rows(budget_mb=8192, has_gpu=None)
        assert not called, (
            f"「有没有显卡」还不知道，却已经去问准入了：{called}。"
            "不知道有没有卡，就给不出「装不装得下」—— 那个结论会被照着去选档。"
        )
        for row in list(rows) + list(half):
            assert row.fit is None, f"没探硬件却给了 {row.tag} 一个结论「{row.fit}」—— 没探到和探到「装得下」是两件事"
        # 反过来：给了硬件就必须真的去问，否则上面那条只要不调用就永远绿。
        called.clear()
        measurement_rows(budget_mb=8192, has_gpu=True)
        assert called, "给了硬件画像却没去问准入 —— 那这一栏是哪来的？"

    def test_with_hardware_every_local_model_gets_a_verdict(self) -> None:
        rows = measurement_rows(budget_mb=8192, has_gpu=True)
        assert rows, "目录里一个本地型号都没有"
        assert all(r.fit in {"ok", "insufficient_vram", "no_gpu"} for r in rows)

    def test_the_report_text_marks_every_unknown(self) -> None:
        """渲染出来的那份文本里，没量过的地方必须**看得见**是没量过。"""
        text = render_report(measurement_rows(budget_mb=8192, has_gpu=True), budget_mb=8192)
        assert UNKNOWN in text, "一份全是数字、一个「未量过」都没有的报告，读的人会以为全量过了"
        assert "这个数是哪来的" in text, "报告没有交代口径"

    def test_the_verdict_comes_from_the_one_admission_authority(self) -> None:
        """结论必须来自 :func:`core.routes.models.fit_detail`，不能在这儿另算一遍。

        另算一遍就是同一个事实两处各存 —— 这个仓库为它栽过不止一次。
        """
        src = (_ROOT / "core/model_measurements_report.py").read_text(encoding="utf-8")
        src = re.sub(r'"""(?:.|\n)*?"""', " ", src)
        assert "fit_detail" in src, "实测账自己算了一遍准入 —— 迟早跟面板给出不同答案"
        assert not re.search(r"runtime_mb\(\)\s*>", src), "这儿又写了一遍显存比较"


class TestTheTrayOnlyDisplays:
    """托盘不许自己算账 —— 它只负责把这些行显示出来。"""

    def test_the_tray_gets_its_numbers_from_the_report_module(self) -> None:
        src = (_ROOT / "windows_service/tray_icon.py").read_text(encoding="utf-8")
        code = re.sub(r'"""(?:.|\n)*?"""', " ", src)
        assert "model_measurements_report" in code, "托盘不再从实测账那一处取数了"
        assert not re.search(
            r"runtime_mb\(\)|kv_mb_per_1k\(", code
        ), "托盘自己去算那几个数了 —— 两边各算一遍，迟早给出不同答案"

    def test_the_tray_says_unknown_hardware_instead_of_zero(self) -> None:
        """探不到硬件时托盘必须传 ``None``，**不是 0**。

        传 0 的话每一行都会写着「装不下」，而真相是没人问过。
        """
        src = (_ROOT / "windows_service/tray_icon.py").read_text(encoding="utf-8")
        body = src[src.index("def _hardware_budget(") :]
        body = body[: body.index("\n    def ")]
        body = re.sub(r'"""(?:.|\n)*?"""', " ", body)
        assert re.search(r"return None, None", body), "探不到硬件时没有返回 (None, None) —— 给 0 会让每一行都写着装不下"
