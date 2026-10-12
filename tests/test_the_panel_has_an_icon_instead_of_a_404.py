"""图标:一处定义,两处取用,没有一条恒定的 404。

浏览器和 Electron 只要开了页面就会自己去要 ``/favicon.ico``。仓库里此前一个
图标都没有,于是那条请求恒定 404 —— 面板一开、``/docs`` 一开,网关日志里就多
一条无人认领的 404。真跑实测里它就混在真问题中间。

守两件事:
  1. 图标只在 core/brand_icon.py 定义一次;
  2. 面板 index.html(源码与 dist 两份)内联的就是**那一份**,不是各写各的
     —— 否则壳里显示的图标和后端给的图标会悄悄分叉。
"""

import os

import pytest

from core.brand_icon import FAVICON_MEDIA_TYPE, FAVICON_SVG, favicon_data_uri

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL_SRC = os.path.join(ROOT, "electron", "renderer", "panel", "index.html")
PANEL_DIST = os.path.join(ROOT, "electron", "renderer", "panel", "dist", "index.html")


def test_the_icon_is_a_real_svg():
    assert FAVICON_SVG.startswith("<svg")
    assert FAVICON_SVG.rstrip().endswith("</svg>")
    assert FAVICON_MEDIA_TYPE == "image/svg+xml"


def test_the_data_uri_is_percent_encoded_so_it_survives_an_html_attribute():
    uri = favicon_data_uri()
    assert uri.startswith("data:image/svg+xml,")
    # 裸 # 会被当成片段起点,裸引号会提前关掉属性 —— 两个都不许出现。
    body = uri.split(",", 1)[1]
    assert "#" not in body
    assert '"' not in body


@pytest.mark.parametrize("path", [PANEL_SRC, PANEL_DIST], ids=["src", "dist"])
def test_the_panel_inlines_the_one_icon_we_defined(path):
    html = open(path, encoding="utf-8").read()
    assert 'rel="icon"' in html, f"{path} 没有 <link rel=icon>,浏览器会去要 /favicon.ico 然后吃 404"
    assert favicon_data_uri() in html, f"{path} 里的图标和 core/brand_icon.py 对不上 —— 两处分叉了"


def test_the_gateway_serves_the_same_icon_without_a_token():
    """网关那条路由的形状:无鉴权、返回 SVG、内容就是那一份。

    直接读源码断言,而不是起一个真网关 —— 起网关会把整套子系统拉起来,
    这条判据不需要那么重。真正的端到端在启动器真跑里已经走过。
    """
    src = open(os.path.join(ROOT, "launcher", "services.py"), encoding="utf-8").read()
    assert '@self.app.get("/favicon.ico"' in src
    assert "include_in_schema=False" in src
    assert "FAVICON_SVG" in src and "FAVICON_MEDIA_TYPE" in src


def test_the_icon_is_the_same_pet_as_the_tray_and_the_taskbar():
    """网页图标也是那只桌宠:外形、眼缝、颜色与 windows_service/pet_icon.py 逐项相等。

    原先是一圈暖金圆环,说是「取自覆盖层第一态的暖金氛围光」—— 那圈光早换成紫调了,图标没跟上。
    """
    from windows_service import pet_icon as p

    assert f'd="{p.PATH_D}"' in FAVICON_SVG
    assert f'fill="{p.SKIN}"' in FAVICON_SVG
    y, h, _ = p.EYE_STATES["open"]
    for x in p.EYE_X:
        eye = f'<rect x="{x}" y="{y}" width="{p.EYE_W:g}" height="{h}" rx="{p.EYE_RX:g}" fill="{p.EYE}"/>'
        assert eye in FAVICON_SVG, eye


def test_nothing_on_screen_still_calls_the_first_state_warm_gold():
    """覆盖层第一态是三条边的紫调氛围光;启动横幅、外壳日志不能再写「暖金」。"""
    for rel in ("launcher/services.py", "electron/main.js", "electron/renderer/app.js"):
        src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        assert "暖金" not in src, f"{rel} 还在说暖金氛围光"
