import { useState, useEffect, useCallback, useRef } from 'react';

interface CacheEntry<T> {
  data: T;
  ts: number;
}

const CACHE_TTL_MS = 30_000; // 30秒缓存
const RETRY_BASE_MS = 3_000;
const RETRY_MAX_MS = 30_000;

// 真正的模块级共享缓存/in-flight Promise —— 这两个 Map 建在模块作用域,同一渲染
// 进程里所有调用方(ModelsTab/SettingsTab...)才真的共用同一份缓存。
//
// 键前缀必须包含调用方显式传入的 cacheKey,不能只用 JSON.stringify(deps) ——
// ModelsTab 和 SettingsTab 都以 deps=[] 调用本 hook,若只按 deps 算键,两者会
// 撞成同一个 "[]",谁先加载完就把另一者的缓存污染成自己的数据形状(一个是
// {configured,values},一个是 Record<string,ConfigItem>),后加载的一方读到
// 完全对不上的字段(如 .configured 恒为 undefined),表现为"看起来什么都没配置"。
const cache = new Map<string, CacheEntry<unknown>>();
const inflight = new Map<string, Promise<unknown>>();

/**
 * useConfigCache — 共享配置缓存 Hook
 *
 * 解决 ModelsTab / SettingsTab 每次挂载都重新拉取的问题。
 * 同一 tick 内多次请求共享同一 Promise，缓存 30 秒。
 *
 * 只在挂载时(缓存命中则立即返回)和显式 invalidate() 后重新拉取 —— 配置/设置
 * 只会因为用户在本面板内保存而改变,没有外部进程会在背后悄悄改动它，所以不设
 * 定时轮询：之前版本的 30 秒 setInterval 会让 Tab 常驻挂载后每 30 秒都发一次
 * 真实网络请求，不管用户是否正在看这个 Tab —— 这正是"自己一直在那儿刷"的根因。
 *
 * 首次加载失败(典型场景:后端/Ollama 还在启动期,几十秒到几分钟内连不上)时，
 * 在后台按退避间隔自动重试，直到成功为止 —— 调用方(ModelsTab/SettingsTab)
 * 不应该因此把整个界面挡住等待，而是始终渲染表单本体，只用一个不打断操作的
 * 小提示表示"后台仍在重试"。一旦成功加载过一次,就不再自动重试,回到"不老是
 * 自己刷"的既有约束。
 */
export function useConfigCache<T>(
  cacheKey: string,
  fetcher: () => Promise<T>,
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryAttempt = useRef(0);
  const everLoaded = useRef(false);

  const load = useCallback(async () => {
    const now = Date.now();
    const cached = cache.get(cacheKey);

    // 缓存命中且未过期
    if (cached && now - cached.ts < CACHE_TTL_MS) {
      setData(cached.data as T);
      setLoading(false);
      setError(null);
      everLoaded.current = true;
      return;
    }

    setLoading(true);

    // 同一 tick 共享 in-flight 请求
    let promise = inflight.get(cacheKey) as Promise<T> | undefined;
    if (!promise) {
      promise = fetcher().finally(() => {
        inflight.delete(cacheKey);
      });
      inflight.set(cacheKey, promise);
    }

    try {
      const result = await promise;
      cache.set(cacheKey, { data: result, ts: Date.now() });
      setData(result);
      setError(null);
      everLoaded.current = true;
      retryAttempt.current = 0;
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
      if (!everLoaded.current) {
        const delay = Math.min(RETRY_BASE_MS * 2 ** retryAttempt.current, RETRY_MAX_MS);
        retryAttempt.current += 1;
        if (retryTimer.current) clearTimeout(retryTimer.current);
        retryTimer.current = setTimeout(() => { load(); }, delay);
      }
    } finally {
      setLoading(false);
    }
  }, [fetcher, cacheKey]);

  // 组件挂载时加载（有缓存则直接命中，不发请求）
  useEffect(() => {
    load();
    return () => {
      if (retryTimer.current) clearTimeout(retryTimer.current);
    };
  }, [load]);

  // 手动使缓存失效（保存配置后 / 收到后端就绪通知后调用）
  const invalidate = useCallback(() => {
    cache.delete(cacheKey);
    retryAttempt.current = 0;
    load();
  }, [cacheKey, load]);

  return { data, loading, error, reload: load, invalidate };
}
