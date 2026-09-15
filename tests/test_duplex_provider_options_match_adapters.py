"""面板上选得到的 provider，必须和真的实现了的 provider 一一对应。

这两份清单原本互不知道对方存在：

* `core/voice_duplex_session.py` 的 `_ADAPTERS` —— **真的实现了**哪几家；
* `core/routes/config_schema_registry.py` 里 `GALAXY_REALTIME_PROVIDER` 的
  `options` —— 面板下拉框**选得到**哪几家。

两边漂移的两种形态都不会有任何症状：

1. 实现了但没进 options → 这家**选不到**，等于没接。接了一整套却没人用得上，
   而代码、测试、文档全都显示"支持"。
2. 进了 options 但没实现 → 用户选中它，`get_adapter()` 抛
   `未实现的双工 provider 适配器` —— 一个只有选了才知道的坑。

所以把它钉成一条：两个集合必须**相等**。
"""

from core.routes.config_schema_registry import CONFIG_SCHEMA
from core.voice_duplex_session import _ADAPTERS, get_adapter


def _options() -> set:
    return set(CONFIG_SCHEMA["GALAXY_REALTIME_PROVIDER"]["options"])


class TestTheTwoListsAgree:
    def test_every_implemented_adapter_is_selectable_in_the_panel(self):
        missing = set(_ADAPTERS) - _options()
        assert not missing, f"这些 provider 实现了却在面板里选不到，等于没接: {sorted(missing)}"

    def test_every_selectable_option_actually_has_an_adapter(self):
        extra = _options() - set(_ADAPTERS)
        assert not extra, f"面板里选得到但没实现，用户选中会抛异常: {sorted(extra)}"

    def test_the_default_is_one_of_the_options(self):
        assert CONFIG_SCHEMA["GALAXY_REALTIME_PROVIDER"]["default"] in _options()

    def test_each_option_really_constructs(self):
        """判据不停在"名字对得上"——真的把每个都造出来一次。

        名字对得上而 `get_adapter` 仍抛错是可能的（登记表键与类名不一致），
        只比集合发现不了。
        """
        for name in sorted(_options()):
            assert get_adapter(name).name == name
