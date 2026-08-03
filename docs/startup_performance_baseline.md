# 启动性能基线（权威 API 层）

这份文件记的是**测量结果**，不是优化方案。写下来是因为"提速"这件事最容易的失败方式，
是在没有基线的情况下动手——改完之后没人说得清快了多少，甚至说不清原来慢在哪。

复现方式在每一节里，数字可以随时重测。

## 一、总量

冷/热差异极大，而**差的那一部分不是字节码编译，是磁盘冷读**——这一点我一开始判断错了，
记在这里免得下一个人重走：

| 场景 | 组装耗时 |
|---|---|
| 进程第一次跑（文件系统冷） | ~10.8 s |
| 文件系统热之后 | ~2.06 s |

所以任何"启动很慢"的观察，第一件事是确认它是不是只是第一次。

## 二、字节码编译到底值多少

用独立缓存目录隔离，每组跑 3 次：

```bash
M='import time; t=time.perf_counter()
import fastapi, core.api_routes as ar
app=fastapi.FastAPI(); app.include_router(ar.create_api_routes(service_manager=None, config=None)); app.openapi()
print(f"{(time.perf_counter()-t)*1000:.0f}")'

# 每次全新空缓存目录（保证不复用 .pyc）
for i in 1 2 3; do d=$(mktemp -d); PYTHONPYCACHEPREFIX=$d python3 -c "$M"; done
# 复用同一个已预热的缓存目录
d=$(mktemp -d); PYTHONPYCACHEPREFIX=$d python3 -c "$M" >/dev/null
for i in 1 2 3; do PYTHONPYCACHEPREFIX=$d python3 -c "$M"; done
```

| 场景 | 三次测量 |
|---|---|
| 无 .pyc 复用 | 4362 / 3703 / 4153 ms |
| 有 .pyc 复用 | 1814 / 1887 / 1902 ms |

差约 **2.2 s**——但那是把 site-packages 也算进去了。真实容器里 pip 装依赖时已经
编译过 site-packages，**只有应用代码没有**。隔离之后：

| 场景 | 三次测量 |
|---|---|
| 应用代码无 .pyc + `PYTHONDONTWRITEBYTECODE=1` | 2315 / 2322 / 2384 ms |
| 构建期 `compileall` 之后 | 1919 / 1930 / 2036 ms |

**约 380 ms 每次启动（~16%）**。已在 `Dockerfile` 与 `Dockerfile.gateway` 里落实。

> 为什么这在容器里是**每次**而不是首次：四个 Dockerfile 都设了
> `PYTHONDONTWRITEBYTECODE=1`（容器常见做法），于是运行期永远不写 .pyc；
> 而构建时又没有预编译，所以每一次进程启动都要重编译一遍应用代码。

`Dockerfile.node` 与 `Dockerfile.agentcpm` **没有动**：它们跑单个节点，import 图
与这里测的完全不同，没测过就不该套用一个未验证的收益。

## 三、剩下的时间花在哪（这一节推翻了任务标题的前提）

任务原本叫"FastAPI 整合与提速"，隐含前提是 FastAPI 的路由装配慢。**实测不是。**

给 `APIRouter.include_router` 打点，统计 `create_api_routes()` 内部：

```
create_api_routes() 合计 867 ms · include_router 调用 49 次
其中 include_router 累计 1 ms      ← 路由装配总共 1 毫秒
```

也就是说那 867 ms 几乎全是**函数体里那些 `from core.routes import X` 触发的模块导入**，
与 FastAPI 无关。`python -X importtime` 的前几名：

```
431.9 ms  core.api_routes
226.9 ms    fastapi
133.9 ms    core.routes._models
107.1 ms      core.schemas.multimodal
 61.3 ms    core
 53.1 ms    core.node_protocol
```

**结论：要提速就得减少/推迟 import，而不是动 FastAPI 的装配方式。**

## 四、一个不该算进启动成本的数字

`app.openapi()` 首次生成要 ~580 ms。但 `unified_launcher.py` 与 `core/api_routes.py`
里**没有任何地方主动调用它**——FastAPI 是惰性生成的，这 580 ms 只在第一次有人访问
`/openapi.json` 或 `/docs` 时才付。

早期把它算进"启动耗时"会让总数虚高约三分之一。测量时要注意自己有没有替生产
多做一件它不做的事。

## 五、还没做的

* **减少启动期 import**：这是剩下 ~1.9 s 里的主要部分，但要动 `core/api_routes.py`
  里几十处顶层导入，风险与收益都需要逐个模块评估，不是一次性改动。
* **节点镜像**：见上，未测量。
* **请求延迟**：这份文件只测了启动，没测运行期。两者的瓶颈未必是同一个。
