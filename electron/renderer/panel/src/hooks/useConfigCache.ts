import { useState, useEffect, useCallback, useRef } from 'react';

interface CacheEntry<T> {
  data: T;
  ts: number;
}

const CACHE_TTL_MS = 30_000; // 30秒缓存

/**
 * useConfigCache — 共享配置缓存 Hook
 *
 * 解决 ModelsTab / SettingsTab 每次挂载都重新拉取的问题。
 * 同一 tick 内多次请求共享同一 Promise，缓存 30 秒。
 */
export function useConfigCache<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
) {
  // 模块级共享缓存和 Promise（同一进程内所有组件实例共享）
  const cacheRef = useRef<Map<string, CacheEntry<T>> | null>(null);
  const inflightRef = useRef<Map<string, Promise<T>> | null>(null);

  if (!cacheRef.current) cacheRef.current = new Map();
  if (!inflightRef.current) inflightRef.current = new Map();

  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const key = JSON.stringify(deps);
  const cache = cacheRef.current;
  const inflight = inflightRef.current;

  const load = useCallback(async () => {
    const now = Date.now();
    const cached = cache.get(key);

    // 缓存命中且未过期
    if (cached && now - cached.ts < CACHE_TTL_MS) {
      setData(cached.data);
      setLoading(false);
      setError(null);
      return;
    }

    // 同一 tick 共享 in-flight 请求
    let promise = inflight.get(key);
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

  // 组件挂载时加载（有缓存则直接命中）
  useEffect(() => {
    load();
  }, [load]);

  // 定时刷新（30秒间隔）
  useEffect(() => {
    const timer = setInterval(load, CACHE_TTL_MS);
    return () => clearInterval(timer);
  }, [load]);

  // 手动使缓存失效（保存配置后调用）
  const invalidate = useCallback(() => {
    cache.delete(key);
    setLoading(true);
    load();
  }, [key, load]);

  return { data, loading, error, reload: load, invalidate };
}
