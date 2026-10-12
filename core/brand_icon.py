"""Galaxy 的图标 —— **一处权威**。

浏览器/Electron 只要开了一个页面,就会自己去要 ``/favicon.ico``。仓库里此前
一个图标都没有,于是那条请求恒定 404:面板一开就在网关日志里留一条无人认领的
404,``/docs`` 也是。不是致命问题,但它是**噪声里混着真问题**的那种噪声。

图标只在这里定义一次,两个地方都从这儿取:

  * 网关 ``GET /favicon.ico``(浏览器直接访问后端时)
  * 面板 ``index.html`` 里内联的 ``<link rel="icon">``(壳里以 file:// 打开时
    根本没有同源后端可问)

两处必须一致 —— 由 tests/test_the_panel_has_an_icon_instead_of_a_404.py 盯着。

画的是**那只桌宠**:与托盘、任务栏图标(``windows_service/pet_icon.py`` 现画)、面板与覆盖层上那两只
同一个外形、同一双眼缝、同一套颜色(``tests/test_every_pet_is_the_same_pet.py`` 逐项核对)。原先是
一圈暖金圆环,说是「取自覆盖层第一态的暖金氛围光」—— 那圈光早就换成了紫调,图标还停在旧样子。
这里不 import ``windows_service``(核心不依赖那个顶层包),数值抄一份,由测试核对相等。
"""

from urllib.parse import quote

#: 桌宠外形(viewBox 0 0 40 40),与 pet_icon.PATH_D 一字不差。
_PET_PATH = (
    "M20 4.6c8 0 13.6 4.2 15 11 .6 2.9.6 5.9 0 8.8-1.4 7.2-6.8 11.6-15 11.6"
    "S6.4 31.6 5 24.4a22 22 0 0 1 0-8.8c1.4-6.8 7-11 15-11z"
)
#: 身子 / 眼睛的颜色,与 pet_icon.SKIN / pet_icon.EYE 相同。
PET_SKIN = "#a58bb5"
PET_EYE = "#fcf9fe"

FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">'
    f'<path d="{_PET_PATH}" fill="{PET_SKIN}"/>'
    f'<rect x="13.2" y="14.4" width="4" height="9.6" rx="2" fill="{PET_EYE}"/>'
    f'<rect x="22.8" y="14.4" width="4" height="9.6" rx="2" fill="{PET_EYE}"/>'
    "</svg>"
)

FAVICON_MEDIA_TYPE = "image/svg+xml"


def favicon_data_uri() -> str:
    """给 ``<link rel="icon" href="...">`` 用的 data URI(百分号编码,可直接内联)。"""
    return "data:image/svg+xml," + quote(FAVICON_SVG, safe="")


__all__ = ["PET_SKIN", "PET_EYE", "FAVICON_SVG", "FAVICON_MEDIA_TYPE", "favicon_data_uri"]
