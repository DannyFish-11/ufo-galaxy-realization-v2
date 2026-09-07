"""Galaxy 的图标 —— **一处权威**。

浏览器/Electron 只要开了一个页面,就会自己去要 ``/favicon.ico``。仓库里此前
一个图标都没有,于是那条请求恒定 404:面板一开就在网关日志里留一条无人认领的
404,``/docs`` 也是。不是致命问题,但它是**噪声里混着真问题**的那种噪声。

图标只在这里定义一次,两个地方都从这儿取:

  * 网关 ``GET /favicon.ico``(浏览器直接访问后端时)
  * 面板 ``index.html`` 里内联的 ``<link rel="icon">``(壳里以 file:// 打开时
    根本没有同源后端可问)

两处必须一致 —— 由 tests/test_the_panel_has_an_icon_instead_of_a_404.py 盯着。
形状取自三态覆盖层那圈暖金边缘氛围光。
"""

from urllib.parse import quote

#: 暖金 —— 与覆盖层第一态(待机氛围光)同色。
BRAND_GOLD = "#e8b464"

FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<circle cx="16" cy="16" r="11" fill="none" stroke="' + BRAND_GOLD + '" stroke-width="4"/>'
    '<circle cx="16" cy="16" r="3.5" fill="' + BRAND_GOLD + '"/>'
    "</svg>"
)

FAVICON_MEDIA_TYPE = "image/svg+xml"


def favicon_data_uri() -> str:
    """给 ``<link rel="icon" href="...">`` 用的 data URI(百分号编码,可直接内联)。"""
    return "data:image/svg+xml," + quote(FAVICON_SVG, safe="")


__all__ = ["BRAND_GOLD", "FAVICON_SVG", "FAVICON_MEDIA_TYPE", "favicon_data_uri"]
