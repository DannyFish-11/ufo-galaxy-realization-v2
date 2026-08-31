"""``core.safe_fs`` —— 把"校验"和"使用"绑到同一个文件描述符上。

为什么需要它
------------
先前 ``nodes/Node_120_File`` 的 ``_resolve_path`` 是这样把关的::

    root = os.path.realpath(self.workspace_root)
    candidate = os.path.realpath(os.path.join(root, path))
    if os.path.commonpath([root, candidate]) != root:
        raise ValueError(...)
    return Path(candidate)          # ← 交出去的是**路径字符串**

判定本身没有错。错在**判定的对象和使用的对象不是同一个**:判定看的是"此刻
``candidate`` 这个名字指向哪儿",使用发生在之后某个时刻,那时同一个名字可以已经
指向别处。中间这段就是 TOCTOU 窗口。

这不是理论担忧,是**实测复现过的**。一个线程反复把工作区内的 ``f.txt`` 在"普通
文件"与"指向工作区外 secret.txt 的符号链接"之间原子替换(``rename`` 一个符号链接
盖到已存在的普通文件上是允许且原子的),另一个线程走完整的"校验→打开"流程::

    校验通过 42953 次 | 读到工作区外内容 576 次 | 校验拒掉 4097 次 | realpath 抛错 257 次

**1.3% 的逃逸率**。窗口是宽的,不是发丝。

顺带记下同一次复现暴露的第二件事:``os.path.realpath`` 自己在路径抖动时会抛
``FileNotFoundError``(上面 257 次)。旧实现没有捕它,于是并发场景下调用方拿到的
是一个裸 ``FileNotFoundError``,而不是本该给出的 ``ValueError``。

试过但**不成立**的两种攻击(记下来,免得以后有人以为漏测了)
-------------------------------------------------------------
* **换入口那段符号链接** —— 无效。``_resolve_path`` 返回的是 ``realpath``(已摊平),
  返回值里根本不含那段符号链接,下游 ``open()`` 不会再走一遍。这正是先前那次
  "校验哪个就返回哪个"的修改带来的实际收益。
* **把中间某段目录换成符号链接** —— 做不到原子。``rename`` 不允许目录与符号链接
  互换,中间必然出现"该名字不存在"的瞬间,校验那侧要么抛要么拒。

真正能原子做到的只有**最后一段**:普通文件 ← 符号链接。所以下面的防线必须能挡住
它,而这恰恰是纯路径校验做不到的 —— 无论校验写得多严,它校验的都是"名字",而
``open()`` 也是拿"名字"再查一次。

做法
----
不再交出路径字符串,而是交出**文件描述符**。描述符绑定的是 inode,不是名字:一旦
拿到,别人再怎么改名字、换符号链接,这个描述符指向的东西都不会变。

解析过程是内核 ``openat2(RESOLVE_BENEATH)`` 语义的用户态实现:

1. 进程期内**钉住**一个工作区根目录的描述符;
2. 请求路径按分隔符切开,**逐段**用 ``os.open(..., dir_fd=上一段的 fd)`` 下降,
   每段都带 ``O_NOFOLLOW`` —— 于是任何一段是符号链接时,内核直接报 ``ELOOP``,
   绝不会替我们跟过去;
3. 遇到符号链接时由我们**自己**决定跟不跟:读出它的目标,拆成若干段拼回待处理
   队列,继续从当前位置下降。跳数上限 40(与 Linux ``MAXSYMLINKS`` 一致);
4. ``..`` **不下发给内核**,而是弹自己维护的 fd 栈。栈底就是根,想再往上弹就是
   越界 —— 这样即便某段在解析途中被换成符号链接,也不存在"从别处的 ``..`` 爬出去"
   这条路;
5. **绝对目标的符号链接一律拒绝**。可以把它按"相对根"重新解释(内核的
   ``RESOLVE_IN_ROOT`` 就这么干),但那等于悄悄改写语义 —— 指向 ``/etc/passwd``
   的链接会变成指向 ``<工作区>/etc/passwd``。宁可拒掉、说清楚。

平台
----
全靠 ``dir_fd``,而 ``os.supports_dir_fd`` 在 Windows 上是空的。所以本模块在
Windows 上**不可用**,构造时直接抛 :class:`UnsupportedPlatform`。调用方据此回退到
纯路径校验时,必须**明说**那条路上窗口仍在,不许静默降级 —— 这是本仓一贯的要求:
降级可以发生,但不许装作没发生。
"""

from __future__ import annotations

import errno
import os
import stat as stat_module
from collections import deque
from pathlib import Path
from typing import IO, Any, Iterator, List, Sequence

__all__ = [
    "MAX_SYMLINK_HOPS",
    "PathEscapesWorkspace",
    "SymlinkNotFollowed",
    "PathOnlyGuard",
    "UnsupportedPlatform",
    "WorkspaceGuard",
    "dir_fd_supported",
    "open_workspace",
]

# 与 Linux MAXSYMLINKS 对齐:超过就认定成环。
MAX_SYMLINK_HOPS = 40

_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


class PathEscapesWorkspace(ValueError):
    """请求的路径解析后落在工作区之外。

    继承 ``ValueError`` 是为了兼容:调用方原先捕的就是 ``ValueError``,换成本类
    之后那些 ``except ValueError`` 依然接得住,不会因为换了实现而漏网。
    """


class SymlinkNotFollowed(PathEscapesWorkspace):
    """遇到了不肯跟的符号链接(目标是绝对路径,或调用方要求不跟最后一段)。"""


class UnsupportedPlatform(RuntimeError):
    """本平台不支持 ``dir_fd``,守卫无法提供它承诺的保证。"""


def dir_fd_supported() -> bool:
    """本平台能不能做描述符锚定的解析。

    只要有一个必需的系统调用不支持 ``dir_fd``,就整体判为不支持 —— 部分支持等于
    留了一条没人注意的旁路。
    """
    required = (os.open, os.stat, os.readlink, os.unlink, os.rmdir, os.mkdir, os.rename)
    return all(fn in os.supports_dir_fd for fn in required)


def _split(relpath: str | os.PathLike[str]) -> List[str]:
    """把一个**相对**路径切成待下降的段。

    只处理相对路径:符号链接的相对目标,以及已经被
    :meth:`WorkspaceGuard._segments` 转成相对形式的请求路径。
    """
    text = os.fspath(relpath)
    if os.sep == "\\":
        text = text.replace("\\", "/")
    return [seg for seg in text.split("/") if seg not in ("", ".")]


def _is_symlink(name: str, dir_fd: int) -> bool:
    """*name* 在 *dir_fd* 里是不是符号链接。查不到就当不是,让调用方按原错误处理。"""
    try:
        return stat_module.S_ISLNK(os.lstat(name, dir_fd=dir_fd).st_mode)
    except OSError:
        return False


class WorkspaceGuard:
    """钉住工作区根目录,并只在它下面提供文件操作。

    典型用法::

        with WorkspaceGuard(workspace_root) as guard:
            data = guard.read_bytes("sub/a.txt")

    实例本身持有一个长期打开的目录描述符,用完请 :meth:`close`(或用 ``with``)。
    """

    __slots__ = ("_root_fd", "_root_path", "_closed")

    #: 这一档**真的**把窗口关上了(解析与使用绑在同一个描述符上)。
    #: :class:`PathOnlyGuard` 把它翻成 ``False`` —— 调用方据此判断自己拿到的是哪种。
    closes_toctou_window = True

    def __init__(self, root: str | os.PathLike[str]) -> None:
        if not dir_fd_supported():
            raise UnsupportedPlatform(
                "safe_fs 需要 os.supports_dir_fd;本平台(如 Windows)不提供," "调用方必须显式回退并说明 TOCTOU 窗口仍在"
            )
        self._root_path = Path(os.path.realpath(os.fspath(root)))
        # 根自己也不许是符号链接:否则"根"这个概念本身就能被换掉。
        self._root_fd = os.open(self._root_path, _DIR_FLAGS)
        self._closed = False

    # ── 生命周期 ──────────────────────────────────────────────────────────

    def close(self) -> None:
        if not self._closed:
            os.close(self._root_fd)
            self._closed = True

    def __enter__(self) -> "WorkspaceGuard":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - 兜底,正常路径靠 close/with
        try:
            self.close()
        except Exception:  # noqa: BLE001 — 解释器关闭期不许再抛
            pass

    @property
    def root(self) -> Path:
        """工作区根的规范化路径。**仅供展示/日志**,不要拿它去拼路径再打开。"""
        return self._root_path

    def _check_open(self) -> None:
        if self._closed:
            raise ValueError("WorkspaceGuard 已关闭")

    def _segments(self, relpath: str | os.PathLike[str]) -> List[str]:
        """把**请求**路径切成待下降的段,绝对路径先折算成相对根的形式。

        绝对路径按字面理解,再要求它落在根之内 —— 与旧实现一致:旧代码
        ``os.path.join(root, path)`` 在 path 为绝对路径时直接取 path,随后由包含性
        判定裁决。折算用纯词法的 ``os.path.relpath``(不碰文件系统,不引入窗口);
        真在根外的绝对路径会折算出 ``..``,由 :meth:`_descend` 的栈判据拒掉。
        """
        text = os.fspath(relpath)
        if os.path.isabs(text):
            text = os.path.relpath(text, self._root_path)
        return _split(text)

    def _normalized_segments(self, relpath: str | os.PathLike[str]) -> List[str]:
        """把请求路径归约成不含 ``..`` 的段序列;想爬到根之上就抛。

        纯词法,不碰文件系统。``..`` 的处理与 :meth:`_descend` 一致 —— 那边弹的是
        fd 栈,这边弹的是名字栈,两处判"越界"的依据必须是同一条:栈空了还要弹。
        """
        out: List[str] = []
        for name in self._segments(relpath):
            if name == "..":
                if not out:
                    raise PathEscapesWorkspace(f"Path '{relpath}' 试图爬到工作区根之上")
                out.pop()
            else:
                out.append(name)
        return out

    # ── 解析核心 ──────────────────────────────────────────────────────────

    def _descend(self, segments: Sequence[str], *, keep_last: bool) -> tuple[list[int], str | None]:
        """逐段下降,返回 (fd 栈, 最后一段的名字)。

        ``keep_last=True`` 时最后一段**不打开**,只把名字交回去 —— 用于创建、删除、
        改名这类"要在父目录里操作一个名字"的场合。此时返回的栈顶就是父目录。

        调用方负责关闭返回的所有 fd(用 :meth:`_close_stack`)。
        """
        self._check_open()
        stack: list[int] = [os.dup(self._root_fd)]
        queue: deque[str] = deque(segments)
        hops = 0
        try:
            while queue:
                name = queue.popleft()
                if name in ("", "."):
                    continue
                if name == "..":
                    if len(stack) == 1:
                        raise PathEscapesWorkspace("路径试图爬到工作区根之上")
                    os.close(stack.pop())
                    continue

                last = not queue
                if last and keep_last:
                    return stack, name

                try:
                    fd = os.open(name, _DIR_FLAGS, dir_fd=stack[-1])
                except OSError as exc:
                    if exc.errno not in (errno.ELOOP, errno.ENOTDIR):
                        raise
                    # errno 不足以分辨"符号链接"和"普通文件":Linux 上
                    # ``O_DIRECTORY|O_NOFOLLOW`` 撞到指向目录的符号链接给的是
                    # ENOTDIR 而不是 POSIX 说的 ELOOP。所以补一次 lstat 来问清楚。
                    #
                    # 这里**没有**新开窗口:真正的下降仍然只走带 O_NOFOLLOW 的
                    # open。若这一段在 lstat 之后被换成符号链接,下面那次 open
                    # 照样会失败;若被换成普通文件,readlink 会报错。两种情况都
                    # 不会让我们跟着链接走出去。
                    if not _is_symlink(name, stack[-1]):
                        if last:
                            # 最后一段是普通文件而调用方要求打开它 —— 交给上层。
                            return stack, name
                        raise
                    hops += 1
                    if hops > MAX_SYMLINK_HOPS:
                        raise PathEscapesWorkspace(f"符号链接跳数超过 {MAX_SYMLINK_HOPS},疑似成环") from exc
                    target = os.readlink(name, dir_fd=stack[-1])
                    if os.path.isabs(target):
                        raise SymlinkNotFollowed(f"拒绝跟随目标为绝对路径的符号链接: {name} -> {target}") from exc
                    queue.extendleft(reversed(_split(target)))
                    continue
                stack.append(fd)
            # 路径解析完且最后一段是目录(或路径为空 → 就是根本身)
            return stack, None
        except BaseException:
            self._close_stack(stack)
            raise

    @staticmethod
    def _close_stack(stack: Sequence[int]) -> None:
        for fd in stack:
            try:
                os.close(fd)
            except OSError:  # pragma: no cover - 已关闭的 fd
                pass

    # ── 打开 ──────────────────────────────────────────────────────────────

    def open_fd(
        self,
        relpath: str | os.PathLike[str],
        flags: int,
        mode: int = 0o666,
        *,
        follow_final: bool = False,
    ) -> int:
        """安全地打开 *relpath*,返回裸文件描述符;调用方负责 ``os.close``。

        *follow_final* 为 ``False``(默认)时最后一段带 ``O_NOFOLLOW``:若它是符号
        链接则拒绝。这是最严的一档,也是**唯一能挡住"最后一段被原子换成外链"那条
        攻击**的一档 —— 因为拒绝的依据不是"它现在指向哪儿",而是"它是不是链接",
        后者在 ``open`` 这一次系统调用里就判完了,没有窗口。

        *follow_final* 为 ``True`` 时允许最后一段是符号链接,但仍然由本模块自己
        跟随:目标按相对路径拼回队列继续下降,绝对目标一律拒。
        """
        segments = self._segments(relpath)
        if not segments:
            raise PathEscapesWorkspace("不能把工作区根本身当成文件打开")

        hops = 0
        while True:
            stack, name = self._descend(segments, keep_last=True)
            try:
                assert name is not None  # keep_last=True 时必然有名字
                try:
                    return os.open(name, flags | getattr(os, "O_NOFOLLOW", 0), mode, dir_fd=stack[-1])
                except OSError as exc:
                    if exc.errno != errno.ELOOP:
                        raise
                    if not follow_final:
                        raise SymlinkNotFollowed(f"最后一段是符号链接,已拒绝: {os.fspath(relpath)}") from exc
                    hops += 1
                    if hops > MAX_SYMLINK_HOPS:
                        raise PathEscapesWorkspace(f"符号链接跳数超过 {MAX_SYMLINK_HOPS},疑似成环") from exc
                    target = os.readlink(name, dir_fd=stack[-1])
                    if os.path.isabs(target):
                        raise SymlinkNotFollowed(f"拒绝跟随目标为绝对路径的符号链接: {target}") from exc
                    # 相对目标:相对**它所在的目录**,即去掉最后一段之后再拼。
                    segments = segments[:-1] + _split(target)
                    if not segments:
                        raise PathEscapesWorkspace("符号链接解析后落到工作区根本身") from exc
            finally:
                self._close_stack(stack)

    def opener(self, relpath: str | os.PathLike[str], *, follow_final: bool = False):
        """给内建 ``open(..., opener=...)`` 用的 opener。

        这样就能拿到真正的文件对象(带编码、缓冲、上下文管理),而底下那次
        ``open`` 走的是描述符锚定的解析。
        """

        def _opener(_path: str, flags: int) -> int:
            return self.open_fd(relpath, flags, follow_final=follow_final)

        return _opener

    def open(  # noqa: A003 - 与内建同名是刻意的,调用点读起来就是 open
        self,
        relpath: str | os.PathLike[str],
        mode: str = "r",
        *,
        follow_final: bool = False,
        **kwargs: Any,
    ) -> IO[Any]:
        """``builtins.open`` 的安全版本。参数与内建一致(``opener`` 除外)。"""
        # 传给内建的路径只用于错误消息与 ``.name``;真正定位靠 opener。
        # 即便如此也走已校验的 display_path —— 交出去的字符串(会出现在 f.name、
        # 异常消息、日志里)不该是一个指向工作区外的路径。
        display = str(self.display_path(relpath))
        return open(display, mode, opener=self.opener(relpath, follow_final=follow_final), **kwargs)  # noqa: SIM115

    # ── 读写 ──────────────────────────────────────────────────────────────

    def read_bytes(self, relpath: str | os.PathLike[str], *, follow_final: bool = False) -> bytes:
        with self.open(relpath, "rb", follow_final=follow_final) as handle:
            return handle.read()

    def read_text(
        self,
        relpath: str | os.PathLike[str],
        encoding: str = "utf-8",
        *,
        errors: str | None = None,
        follow_final: bool = False,
    ) -> str:
        with self.open(relpath, "r", encoding=encoding, errors=errors, follow_final=follow_final) as handle:
            return handle.read()

    def write_text(
        self,
        relpath: str | os.PathLike[str],
        content: str,
        encoding: str = "utf-8",
        *,
        overwrite: bool = True,
    ) -> int:
        """写入文本。

        ``overwrite=False`` 时用 ``O_EXCL``,由内核保证"存在就失败" —— 比先
        ``exists()`` 再写少一个窗口。
        """
        flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite else os.O_EXCL)
        fd = self.open_fd(relpath, flags)
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            return handle.write(content)

    def append_text(
        self,
        relpath: str | os.PathLike[str],
        content: str,
        encoding: str = "utf-8",
        *,
        create: bool = True,
    ) -> int:
        flags = os.O_WRONLY | os.O_APPEND | (os.O_CREAT if create else 0)
        fd = self.open_fd(relpath, flags)
        with os.fdopen(fd, "a", encoding=encoding) as handle:
            return handle.write(content)

    # ── 元信息 ────────────────────────────────────────────────────────────

    def stat(self, relpath: str | os.PathLike[str], *, follow_final: bool = False) -> os.stat_result:
        """取 stat。默认 ``follow_final=False`` —— 报的是那个名字**自己**的信息。"""
        segments = self._segments(relpath)
        if not segments:
            return os.stat(self._root_fd)
        stack, name = self._descend(segments, keep_last=True)
        try:
            assert name is not None
            if follow_final:
                fd = self.open_fd(relpath, os.O_RDONLY, follow_final=True)
                try:
                    return os.stat(fd)
                finally:
                    os.close(fd)
            return os.stat(name, dir_fd=stack[-1], follow_symlinks=False)
        finally:
            self._close_stack(stack)

    def exists(self, relpath: str | os.PathLike[str], *, follow_final: bool = False) -> bool:
        try:
            self.stat(relpath, follow_final=follow_final)
        except (OSError, PathEscapesWorkspace):
            return False
        return True

    def is_dir(self, relpath: str | os.PathLike[str], *, follow_final: bool = False) -> bool:
        try:
            return stat_module.S_ISDIR(self.stat(relpath, follow_final=follow_final).st_mode)
        except (OSError, PathEscapesWorkspace):
            return False

    def is_file(self, relpath: str | os.PathLike[str], *, follow_final: bool = False) -> bool:
        try:
            return stat_module.S_ISREG(self.stat(relpath, follow_final=follow_final).st_mode)
        except (OSError, PathEscapesWorkspace):
            return False

    # ── 目录 ──────────────────────────────────────────────────────────────

    def scandir(self, relpath: str | os.PathLike[str] = "") -> Iterator[os.DirEntry[str]]:
        """列目录。返回的条目名是**名字**,拼路径请继续走本守卫,别自己 join 后打开。"""
        segments = self._segments(relpath)
        stack, name = self._descend(segments, keep_last=False)
        try:
            if name is not None:  # 最后一段不是目录
                raise NotADirectoryError(errno.ENOTDIR, os.strerror(errno.ENOTDIR), os.fspath(relpath))
            # scandir 复制一份 fd,原 fd 由 _close_stack 关掉,互不影响。
            yield from os.scandir(stack[-1])
        finally:
            self._close_stack(stack)

    def listdir(self, relpath: str | os.PathLike[str] = "") -> List[str]:
        return [entry.name for entry in self.scandir(relpath)]

    def mkdir(
        self,
        relpath: str | os.PathLike[str],
        mode: int = 0o777,
        *,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        segments = self._segments(relpath)
        if not segments:
            if not exist_ok:
                raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(self._root_path))
            return
        if parents:
            for depth in range(1, len(segments)):
                self._mkdir_one(segments[:depth], mode, exist_ok=True)
        self._mkdir_one(segments, mode, exist_ok=exist_ok)

    def _mkdir_one(self, segments: Sequence[str], mode: int, *, exist_ok: bool) -> None:
        stack, name = self._descend(segments, keep_last=True)
        try:
            assert name is not None
            try:
                os.mkdir(name, mode, dir_fd=stack[-1])
            except FileExistsError:
                if not exist_ok:
                    raise
        finally:
            self._close_stack(stack)

    # ── 变更 ──────────────────────────────────────────────────────────────

    def unlink(self, relpath: str | os.PathLike[str], *, missing_ok: bool = False) -> None:
        """删掉一个名字。

        注意这里**故意不跟随符号链接** —— 删的就是那个名字本身,和 ``rm`` 一致。
        """
        stack, name = self._descend(self._segments(relpath), keep_last=True)
        try:
            if name is None:
                raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), os.fspath(relpath))
            try:
                os.unlink(name, dir_fd=stack[-1])
            except FileNotFoundError:
                if not missing_ok:
                    raise
        finally:
            self._close_stack(stack)

    def rmdir(self, relpath: str | os.PathLike[str]) -> None:
        stack, name = self._descend(self._segments(relpath), keep_last=True)
        try:
            if name is None:
                raise PathEscapesWorkspace("不能删除工作区根本身")
            os.rmdir(name, dir_fd=stack[-1])
        finally:
            self._close_stack(stack)

    def rmtree(self, relpath: str | os.PathLike[str]) -> None:
        """递归删除。

        走 ``shutil.rmtree(..., dir_fd=父目录)`` —— CPython 那条实现本身就是
        描述符锚定的(``shutil.rmtree.avoids_symlink_attacks`` 为真时),所以整棵树
        的下降也不会被换名字骗走。
        """
        import shutil

        stack, name = self._descend(self._segments(relpath), keep_last=True)
        try:
            if name is None:
                raise PathEscapesWorkspace("不能递归删除工作区根本身")
            shutil.rmtree(name, dir_fd=stack[-1])
        finally:
            self._close_stack(stack)

    def rename(self, src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        """改名/移动。两端都锚定在各自的父目录描述符上,整个操作是内核原子的。"""
        src_stack, src_name = self._descend(self._segments(src), keep_last=True)
        try:
            if src_name is None:
                raise PathEscapesWorkspace("不能移动工作区根本身")
            dst_stack, dst_name = self._descend(self._segments(dst), keep_last=True)
            try:
                if dst_name is None:
                    raise PathEscapesWorkspace("目标不能是工作区根本身")
                os.rename(src_name, dst_name, src_dir_fd=src_stack[-1], dst_dir_fd=dst_stack[-1])
            finally:
                self._close_stack(dst_stack)
        finally:
            self._close_stack(src_stack)

    # ── 展示 ──────────────────────────────────────────────────────────────

    def display_path(self, relpath: str | os.PathLike[str]) -> Path:
        """给人看的绝对路径;落到工作区外就抛。

        **不要**拿它回去做真正的打开 —— 一旦回到路径字符串,描述符锚定的那套保证
        就失效了。它只用于响应体、日志和错误消息。

        .. note::
           这里**必须**校验,尽管它"只是拿来显示"。此前它是纯拼接:
           ``display_path("../../etc/passwd")`` 老老实实返回
           ``<工作区>/../../etc/passwd`` —— 一个交出去就能指到工作区外的路径。
           当时不可利用(唯一的调用方 ``Node_120._copy_tree`` 上游已经拦过一道),
           但那是靠调用方兜着,不是靠这个函数自己站得住。CodeQL 的
           ``py/path-injection`` 正是顺着这条流报到 ``shutil.copytree`` 的,报得对。

           校验用的是**纯词法**的 ``..`` 归约(见 :meth:`_normalized_segments`),
           不是 ``realpath``。两个理由:一是这个函数不该碰文件系统 —— 它只是拼个
           字符串,加一次 ``realpath`` 就等于给每次 open 加一次系统调用,而且在
           路径抖动时会**误抛**;二是 ``realpath`` 会跟随符号链接,于是"最后一段是
           指向工作区外的符号链接"这种情况会在这里就被判成越界 —— 那本该由描述符
           那条路来判(它给的是 :class:`SymlinkNotFollowed`,语义更准)。
           **不许**让一个只负责显示的函数抢在真正的防线前面下结论。
        """
        return self._root_path.joinpath(*self._normalized_segments(relpath))


class PathOnlyGuard(WorkspaceGuard):
    """没有 ``dir_fd`` 的平台上的退路 —— **窗口仍在**,这一点必须挂在名字上。

    接口与 :class:`WorkspaceGuard` 相同,底下是先前那套 ``realpath`` +
    ``commonpath`` 的纯路径校验。它挡得住 ``..``、绝对路径、以及**校验那一刻**
    就已存在的越界符号链接;挡不住的是校验之后、使用之前被换掉的名字。

    存在的意义是让 Windows 上的调用点不必写第二套代码,而不是假装保护同样牢靠。
    :attr:`closes_toctou_window` 为 ``False``,调用方可以据此判断自己拿到的是哪一种。
    """

    closes_toctou_window = False

    __slots__ = ()

    def __init__(self, root: str | os.PathLike[str]) -> None:  # noqa: D107 - 见类 docstring
        # 刻意不调用 super().__init__:那里会因为不支持 dir_fd 直接抛。
        object.__setattr__(self, "_root_path", Path(os.path.realpath(os.fspath(root))))
        object.__setattr__(self, "_root_fd", -1)
        object.__setattr__(self, "_closed", False)

    def close(self) -> None:
        object.__setattr__(self, "_closed", True)

    def _resolve(self, relpath: str | os.PathLike[str]) -> Path:
        """唯一的落点判定 —— 本类所有操作都先过这里。

        判定**内联**在这个函数里,不再委托给一个公用 helper。这不是风格偏好:
        CodeQL 的 ``py/path-injection`` 能顺着"净化函数 → 调用点"跟**一层**
        (先前 ``Node_120._resolve_path`` 就是这个形状,跟得住),但再多一层
        (调用点 → ``_resolve`` → helper)就跟丢了,于是下面九个方法全被报成
        未净化。把判定放回这一层,既不改语义也不多写几行。

        写成 ``os.path.realpath`` + ``os.path.commonpath`` 而不是 ``Path.resolve``
        + ``Path.relative_to``:两者安全语义等价(都把 ``..`` 与符号链接摊平后比较
        祖先),但前者是静态分析认得的净化形态。
        """
        root = os.path.realpath(os.fspath(self._root_path))
        try:
            candidate = os.path.realpath(os.path.join(root, os.fspath(relpath)))
        except OSError as exc:
            # realpath 在路径抖动时会抛。旧实现漏了这条,于是并发下调用方拿到的是
            # 裸 FileNotFoundError,而不是本该给出的 ValueError。
            raise PathEscapesWorkspace(f"路径解析失败: {relpath}") from exc
        try:
            inside = os.path.commonpath([root, candidate]) == root
        except ValueError:
            inside = False  # Windows 跨盘符:本来就在工作区外
        if not inside:
            raise PathEscapesWorkspace(f"Path '{relpath}' is outside the workspace. Access denied.")
        return Path(candidate)

    # 下面全部退回路径实现。签名与父类一致,只是保证弱一档。

    def open_fd(self, relpath, flags, mode=0o666, *, follow_final=False):  # type: ignore[override]
        return os.open(self._resolve(relpath), flags, mode)

    def open(self, relpath, mode="r", *, follow_final=False, **kwargs):  # type: ignore[override] # noqa: A003
        return open(self._resolve(relpath), mode, **kwargs)  # noqa: SIM115

    def stat(self, relpath, *, follow_final=False):  # type: ignore[override]
        return os.stat(self._resolve(relpath), follow_symlinks=follow_final)

    def scandir(self, relpath=""):  # type: ignore[override]
        yield from os.scandir(self._resolve(relpath))

    def mkdir(self, relpath, mode=0o777, *, parents=False, exist_ok=False):  # type: ignore[override]
        target = self._resolve(relpath)
        if parents:
            target.mkdir(mode, parents=True, exist_ok=exist_ok)
        else:
            try:
                os.mkdir(target, mode)
            except FileExistsError:
                if not exist_ok:
                    raise

    def unlink(self, relpath, *, missing_ok=False):  # type: ignore[override]
        try:
            os.unlink(self._resolve(relpath))
        except FileNotFoundError:
            if not missing_ok:
                raise

    def rmdir(self, relpath):  # type: ignore[override]
        os.rmdir(self._resolve(relpath))

    def rmtree(self, relpath):  # type: ignore[override]
        import shutil

        shutil.rmtree(self._resolve(relpath))

    def rename(self, src, dst):  # type: ignore[override]
        os.rename(self._resolve(src), self._resolve(dst))

    def display_path(self, relpath):  # type: ignore[override]
        return self._resolve(relpath)


def open_workspace(root: str | os.PathLike[str]) -> WorkspaceGuard:
    """拿一个工作区守卫:能钉描述符就钉,不能就退回纯路径实现。

    退回时会打一条 **warning** —— 降级可以发生,但不许静默。调用方若要拒绝在
    无保护状态下运行,检查 ``guard.closes_toctou_window`` 即可。
    """
    import logging

    try:
        return WorkspaceGuard(root)
    except UnsupportedPlatform as exc:
        logging.getLogger(__name__).warning(
            "safe_fs: 本平台不支持 dir_fd,退回纯路径校验 —— " "校验与使用之间的 TOCTOU 窗口仍然存在。root=%s reason=%s",
            root,
            exc,
        )
        return PathOnlyGuard(root)
