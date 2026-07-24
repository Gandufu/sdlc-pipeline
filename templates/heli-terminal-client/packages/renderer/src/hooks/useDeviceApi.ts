import { useEffect, useState, useRef } from 'react';

interface QueryState<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  refresh: () => Promise<void>;
}

/**
 * 轮询 device API 的 hook。
 *
 * fetcher 可以是组件 render 时新建的箭头函数 — 我们用 ref 持有最新引用，
 * 让 run / setInterval 依赖的回调保持稳定，避免因 fetcher 引用变化
 * 导致 setInterval 被反复清理与重建（视觉表现为「连续刷新」）。
 */
export const useDeviceQuery = <T,>(
  fetcher: () => Promise<T>,
  options: { intervalMs?: number; enabled?: boolean } = {}
): QueryState<T> => {
  const { intervalMs = 0, enabled = true } = options;
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<Error | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const mounted = useRef(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const run = useRef<() => Promise<void>>(async () => {
    if (!enabledRef.current) return;
    setLoading(true);
    try {
      const v = await fetcherRef.current();
      if (mounted.current) {
        setData(v);
        setError(undefined);
      }
    } catch (err: any) {
      if (mounted.current) {
        setError(err instanceof Error ? err : new Error(String(err)));
      }
    } finally {
      if (mounted.current) setLoading(false);
    }
  }).current;

  useEffect(() => {
    mounted.current = true;
    run();
    if (intervalMs > 0) {
      const t = setInterval(run, intervalMs);
      return () => clearInterval(t);
    }
    return () => {
      mounted.current = false;
    };
    // 故意只依赖 intervalMs：run 通过 ref 读取最新 fetcher，无需重跑
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs]);

  return { data, error, loading, refresh: run };
};
