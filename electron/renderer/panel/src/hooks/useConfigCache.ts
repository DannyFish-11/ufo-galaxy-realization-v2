import { useState, useEffect, useCallback } from 'react';

interface CacheEntry<T> {
  data: T;
  ts: number;
}

const CACHE_TTL_MS = 30_000; // 30秒缓存

// 真正的模块级共享缓存/in-flight Promise —— 之前这两个 Map 是用 useRef() 建在
// hook 函数体内的,每个组件实例各有一份,根本没有跨实例共享,注释和实现对不上。
// 声明在模块作用域,同一渲染进程里所有调用方(ModelsTab/SettingsTab...)才真的
// 共用同一份缓存。
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
 */
export function useConfigCache<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const key = JSON.stringify(deps);

  const load = useCallback(async () => {
    const now = Date.now();
    const cached = cache.get(key);

    // 缓存命中且未过期
    if (cached && now - cached.ts < CACHE_TTL_MS) {
      setData(cached.data as T);
      setLoading(false);
      setError(null);
      return;
    }

    // 同一 tick 共享 in-flight 请求
    let promise = inflight.get(key) as Promise<T> | undefined;
    if (!promise) {
      promise = fetcher().finally(() => {
        inflight.delete(key);
      });
      inflight.set(key, promise);
    }

    try {
      const result = await promise;
      cache.set(key, { data: result, ts: Date.now() });
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [fetcher, key]);

  // 组件挂载时加载（有缓存则直接命中，不发请求）
  useEffect(() => {
    load();
  }, [load]);

  // 手动使缓存失效（保存配置后调用）
  const invalidate = useCallback(() => {
    cache.delete(key);
    setLoading(true);
    load();
  }, [key, load]);

  return { data, loading, error, reload: load, invalidate };
}
