"""python -m device_client —— 把这台电脑接到主脑上。

python -m device_client --pair 7KQ2MX           第一次:主脑给的配对码(同网段自动找主脑)
python -m device_client --pair 7KQ2MX --gateway http://192.168.1.10:9000
python -m device_client                          之后:直接连
python -m device_client --install-autostart      开机自己连上(--uninstall-autostart 取消)
python -m device_client --status                 看看本机能做哪些动作、缺什么
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import List, Optional

from device_client import autostart
from device_client import pairing as _dp
from device_client.client import DeviceClient
from device_client.executors import select_executor

logger = logging.getLogger("galaxy-device-client")


def _pair(args: argparse.Namespace, state: dict, actions: List[str]) -> int:
    if args.gateway:
        gateways = [args.gateway]
    else:
        print("在局域网里找主脑…")
        gateways = _dp.discover_gateways()
        if gateways:
            print(f"找到:{', '.join(gateways)}")
    try:
        resp = _dp.pair_anywhere(args.pair, state, gateways, name=args.name or "", capabilities=actions)
    except _dp.PairingError as exc:
        print(f"✗ {exc}\n  下一步:{exc.how_to_fix}")
        return 2
    _dp.save_state(state)
    print(f"✓ 已配对:{state.get('name')}({state['device_id']}),主脑 {state.get('gateway')}")
    net = _dp.join_tailnet(resp.get("tailnet_join"), state["device_id"])
    if net.get("state") == "joined":
        print("✓ 已加入自建内网,带出门也能连回主脑")
    elif net.get("how_to_fix"):
        print(f"! 没能自动加入自建内网:{net.get('detail') or net['state']}\n  {net['how_to_fix']}")
    return 0


def main(argv: Optional[List[str]] = None, *, default_executor: Optional[str] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="python -m device_client", description="把这台电脑接到主脑上")
    ap.add_argument("--pair", metavar="CODE", help="主脑给的一次性配对码")
    ap.add_argument("--gateway", help="主脑地址,如 http://192.168.1.10:9000(不给就在局域网里自动找)")
    ap.add_argument("--name", help="这台电脑在设备列表里叫什么")
    ap.add_argument("--device-id", help="自定义设备 id(默认第一次生成后固定)")
    ap.add_argument("--host", default="127.0.0.1", help="没配对过时的兜底主脑地址")
    ap.add_argument("--port", type=int, default=8000, help="没配对过时的兜底主脑端口")
    ap.add_argument("--install-autostart", action="store_true", help="登录后自动连上主脑")
    ap.add_argument("--uninstall-autostart", action="store_true", help="取消开机自动连")
    ap.add_argument("--status", action="store_true", help="看看本机执行插件能做什么、缺什么")
    ap.add_argument("--no-run", action="store_true", help="只配对/设置,不留在前台连接")
    args = ap.parse_args(argv)

    executor = select_executor(default_executor)
    plat = executor.platform if executor.platform != "unknown" else _dp.this_platform()

    if args.status:
        print(json.dumps(executor.describe(), ensure_ascii=False, indent=2))
        return 0
    if args.uninstall_autostart:
        print(f"已取消开机自动连:{autostart.uninstall(plat)}")
        return 0

    state = _dp.load_state()
    if args.device_id:
        state["device_id"] = args.device_id
    if args.pair:
        rc = _pair(args, state, executor.supported_actions() if executor.available()[0] else [])
        if rc:
            return rc
    if args.install_autostart:
        info = autostart.install(plat)
        print(f"✓ 已设置开机自动连:{info['path']}({info['starts']}生效)")
    ok, why = executor.available()
    if not ok:
        print(f"! 本机执行插件 {executor.name} 暂不可用:{why}。会照样连上主脑,但先不接动作。")
    if args.no_run:
        return 0
    if not state.get("token"):
        print("这台电脑还没配对。让主脑给一个配对码,然后运行:python -m device_client --pair <配对码>")
        return 2

    client = DeviceClient(executor, host=args.host, port=args.port, state=state)
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        logger.info("客户端已停止")
    return 3 if client.fatal else 0


if __name__ == "__main__":
    sys.exit(main())
