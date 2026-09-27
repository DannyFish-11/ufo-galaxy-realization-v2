"""device_client — 把一台电脑作为「相对主体」接到主脑上(Windows / Linux / macOS 共用)。

两层,各管一件事:

* **连接层**(``pairing.py`` + ``client.py``):配对、凭据、令牌续期、进自建内网、找主脑、
  连上并保持连接、把主脑下发的动作交给执行层、把结果回给主脑。三个系统完全一样。
* **执行层**(``executors/``):在本机真正动手(点击、打字、截图……)。按系统插件化,
  启动时自动选;第三方可以用 entry point ``galaxy.desktop_executors`` 加自己的插件。

它不是第二个大脑:没有三态、没有模型。要不要做某件事,由主脑那边的权限门和确认决定。

用法::

    python -m device_client --pair 7KQ2MX          # 第一次:主脑给的配对码(同网段自动找主脑)
    python -m device_client                        # 之后:直接连
    python -m device_client --install-autostart    # 开机自己连上
"""
