"""记忆卡片:「怎么切」只有一处说了算,而且 0 与「不知道」不许混。

左栏那叠卡片折的是**一条记忆线上连续三天**的切片。这个文件守三件事:

1. **判断在后端。** ``core/memory_cards.py`` 是唯一定义处;面板照着切好的片画。
   同一条线在面板上切五张、在别的界面上切六张,那就是同一个事实两处各存,而且
   两边都以为自己是对的。
2. **``weight`` 的 0 与 None 是两件事。** 0 = 这三天确实什么都没发生;None =
   这三天没有留下可读的记录。把 None 画成 0 就是把「不知道」画成「确实没有」,
   而这两种情况下人该做的事完全不同。
3. **边界锚在这条线的第一条轮次,不是今天。** 按今天倒推的话,同一条线昨天看和
   今天看会切在不同地方 —— 昨天那张卡今天变成另一张。
"""

from __future__ import annotations

import time

import pytest

from core.memory_cards import PROFILE_BINS, SLICE_DAYS, slice_turns_into_cards

DAY = 86400.0


def turn(day_offset: float, *, now: float, content: str = "x", **md):
    """一条落在「now 之前 day_offset 天」的轮次。"""
    return {"role": "user", "content": content, "timestamp": now - day_offset * DAY, "metadata": md}


@pytest.fixture
def now() -> float:
    # 钉在正午,免得测试在午夜前后跑时因为「今天」翻页而飘。
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))


class TestAQuietStretchIsZeroNotMissing:
    def test_an_empty_slice_is_kept_with_weight_zero(self, now):
        """中间没说过话的那三天**照样成卡**,weight 是 0。

        跳过它的话,卡片之间会出现一段看不见的时间断层 —— 相邻两张卡看着连续,
        实际中间隔了三天。而「那几天很安静」本身就是一条信息。
        """
        cards = slice_turns_into_cards([turn(7, now=now), turn(0, now=now)], now=now)
        assert len(cards) >= 3, f"七天跨度应当至少切出三张(每张 {SLICE_DAYS} 天): {len(cards)}"
        quiet = [c for c in cards if c["turns"] == 0]
        assert quiet, "中间那段安静期被丢掉了"
        for c in quiet:
            assert c["weight"] == 0.0, "空的一段应当是 0(确实什么都没发生),不是 None"

    def test_zero_and_none_are_different_values(self, now):
        """判别用例:同一份数据里同时出现 0 与 None,两者不许被抹成同一个。"""
        cards = slice_turns_into_cards(
            [turn(7, now=now), turn(0, now=now), {"role": "user", "content": "没有时间戳的一条"}],
            now=now,
        )
        weights = [c["weight"] for c in cards]
        assert 0.0 in weights, "没有一段是 0 —— 空的那段去哪了?"
        assert None in weights, "没有一段是 None —— 那条没时间戳的轮次被当成有时间戳处理了"


class TestUndatedTurnsAreNotSilentlyDropped:
    def test_a_turn_with_no_timestamp_makes_that_card_unknown(self, now):
        """没有时间戳的轮次落在哪张卡上,那张卡的浓淡就是**不知道**。

        它确实有内容,但「这三天有多浓」这个问题没有答案 —— 报一个数出来是在
        编。卡面上 None 画成虚线空心,与「空」分得开。
        """
        cards = slice_turns_into_cards([turn(0, now=now), {"role": "user", "content": "无戳"}], now=now)
        assert cards[-1]["weight"] is None
        assert cards[-1]["profile"] == [], "算不出浓淡就不该给一条图出来"

    def test_they_are_still_counted(self, now):
        """**不许丢。** 丢了的话总轮次数对不上,而没人会发现少了哪几条。"""
        cards = slice_turns_into_cards([turn(0, now=now), {"role": "user", "content": "无戳"}], now=now)
        assert sum(c["turns"] for c in cards) == 2

    def test_all_undated_still_produces_a_card(self):
        """一条有时间戳的都没有:不能凭空造一段时间,也不能装作什么都没有。"""
        cards = slice_turns_into_cards([{"role": "user", "content": "无戳"}] * 3)
        assert len(cards) == 1
        assert cards[0]["weight"] is None
        assert cards[0]["turns"] == 3
        assert cards[0]["from"] == "" and cards[0]["to"] == "", "编不出日期就该留空"

    def test_a_zero_timestamp_counts_as_undated(self, now):
        """``timestamp: 0`` 是「没记住自己什么时候的」,不是 1970 年。

        兜底成 ``time.time()`` 的话,一条旧记录会被算成刚刚发生、跳进最新那张卡
        —— 一个凭空出现、谁也想不通的数字。
        """
        cards = slice_turns_into_cards([turn(0, now=now), {"role": "user", "content": "零戳", "timestamp": 0}], now=now)
        assert cards[-1]["weight"] is None
        assert all(c["from"] != "1970-01-01" for c in cards)


class TestTheBoundaryIsAnchoredToTheThreadNotToToday:
    def test_the_first_card_starts_at_the_first_turn(self, now):
        cards = slice_turns_into_cards([turn(5, now=now)], now=now)
        assert cards[0]["from"] == time.strftime("%Y-%m-%d", time.localtime(now - 5 * DAY))

    def test_looking_at_it_later_does_not_move_the_boundaries(self, now):
        """同一批轮次,今天看和三天后看,已有卡片的边界必须一模一样。

        按「今天」倒推切的话,边界每天都在挪 —— 昨天那张卡今天变成另一张,而
        用户是照着卡片记事的。
        """
        turns = [turn(9, now=now), turn(5, now=now), turn(1, now=now)]
        today = slice_turns_into_cards(turns, now=now)
        later = slice_turns_into_cards(turns, now=now + 3 * DAY)
        assert [c["id"] for c in today] == [c["id"] for c in later][: len(today)]


class TestWeightIsRelativeToThisThread:
    def test_the_busiest_slice_is_one(self, now):
        cards = slice_turns_into_cards(
            [turn(4, now=now) for _ in range(3)] + [turn(0, now=now) for _ in range(9)], now=now
        )
        assert max(c["weight"] for c in cards if c["weight"] is not None) == 1.0

    def test_a_lone_slice_is_one_not_zero(self, now):
        """线上只有一段有内容时,那一段就是最忙的那一段 —— 1.0,不是 0。"""
        cards = slice_turns_into_cards([turn(0, now=now)], now=now)
        assert cards[0]["weight"] == 1.0

    def test_weight_stays_in_range(self, now):
        cards = slice_turns_into_cards([turn(d, now=now) for d in (0, 0, 0, 3, 7, 7, 11)], now=now)
        for c in cards:
            if c["weight"] is not None:
                assert 0.0 <= c["weight"] <= 1.0


class TestTheProfileIsWithinTheSlice:
    def test_profile_has_a_fixed_number_of_bins(self, now):
        """段数固定,于是不同卡片的图形可以直接比高低。"""
        cards = slice_turns_into_cards([turn(0, now=now), turn(1, now=now)], now=now)
        for c in cards:
            if c["profile"]:
                assert len(c["profile"]) == PROFILE_BINS

    def test_profile_normalises_inside_the_slice(self, now):
        """段内归一 —— 它回答「这三天忙在哪一头」,与别的卡比高低是 weight 的活。"""
        cards = slice_turns_into_cards([turn(0.1, now=now) for _ in range(4)], now=now)
        assert max(cards[-1]["profile"]) == 1.0


class TestModalitiesComeFromTheRecordNotFromAGuess:
    def test_modalities_are_collected(self, now):
        cards = slice_turns_into_cards([turn(0, now=now, modalities=["screen", "audio"])], now=now)
        assert cards[-1]["modalities"] == ["audio", "screen"]

    def test_no_modality_recorded_means_empty_not_text(self, now):
        """没记录就是空。猜成「文字」的话,卡面上会出现一个谁也没说过的事实。"""
        assert slice_turns_into_cards([turn(0, now=now)], now=now)[-1]["modalities"] == []


class TestTheSlicingLivesInExactlyOnePlace:
    def test_the_files_that_handle_cards_do_no_day_arithmetic(self):
        """**碰卡片的那几个文件**里不许出现天数换算。

        它们照着后端切好的片画。自己算的话,同一条线在这里切五张、在别的界面切
        六张,而两边都以为自己是对的 —— 这个仓库为「同一个事实两处各存」栽过
        不止一次。

        范围只圈**提到卡片的文件**,不是整个面板:头一版扫了全部 .ts,被
        ``island.ts`` 里那个把设备心跳写成「N 天前」的 ``formatAgo`` 绊倒 ——
        那跟切片毫无关系。一条会在无关代码上报红的判据,迟早被加白名单绕过,
        那比没有这条判据更糟。
        """
        import re
        from pathlib import Path

        panel_src = Path(__file__).resolve().parent.parent / "electron/renderer/panel/src"
        block = re.compile(r"/\*.*?\*/", re.S)
        line = re.compile(r"^\s*//.*$", re.M)
        forbidden = ("86400", str(int(SLICE_DAYS * 86400)))

        offenders = {}
        checked = []
        for path in panel_src.rglob("*.ts"):
            if path.name.endswith(".gen.ts"):
                continue
            code = line.sub("", block.sub("", path.read_text(encoding="utf-8")))
            if "MemoryCard" not in code and "cards" not in code:
                continue
            checked.append(path.name)
            hit = [n for n in forbidden if n in code]
            if hit:
                offenders[path.name] = hit
        assert checked, "一个碰卡片的文件都没扫到 —— 这条判据在空转"
        assert not offenders, f"这些文件在自己算天数: {offenders} —— 切片的判断只能在后端一处"

    def test_the_built_panel_really_asks_for_them(self):
        """产物里必须真的有那个端点。

        源码接上了、``dist/`` 没重建,是这条路上最难看出来的一种断线:dist 是提交
        进仓库的、Electron 直接加载它,界面照常打开,只是左栏永远空着。
        """
        from pathlib import Path

        dist = Path(__file__).resolve().parent.parent / "electron/renderer/panel/dist/assets"
        js = "\n".join(p.read_text(encoding="utf-8") for p in sorted(dist.glob("*.js")))
        assert js, "dist/assets 下一个 js 都没有 —— dist/ 必须提交进仓库"
        assert "/api/v1/memory/cards" in js, "构建产物里没有记忆卡片那个端点 —— 左栏不会有东西"
