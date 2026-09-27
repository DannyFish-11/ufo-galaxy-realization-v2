"""core/version.py — Galaxy 的产品版本号，全仓只在这里写一次。

此前同一个系统报出过五个版本号，全都写死在各自的文件里：
* 启动横幅和 ``--version``：``v2.3.21``（``core/ascii_art.py``）
* ``core.__version__`` 和 ``galaxy_gateway.__version__``：``3.0.0``
* ``GET /api/v1/system/status``：``2.0.0``
* 镜像标签：``2.3.23``
* README 抬头：``v10.0``

用户看到的、部署看到的、接口报的对不上。现在它们都从这里取；取不了 Python 常量的地方
（Dockerfile 的 LABEL、启动脚本横幅、npm 包的 package.json、README）由
``tests/test_version_single_source.py`` 核对，和这里不一致就判红。

改版本：只改 ``__version__``，然后按那个测试的提示把非 Python 的几处一起改掉。
"""

__version__ = "2.3.23"

#: 给人看的写法（横幅、``--version``、启动记录）。
GALAXY_VERSION = f"v{__version__}"

__all__ = ["__version__", "GALAXY_VERSION"]
