import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";

export interface UpdateSafetyReasons {
  busy: readonly string[];
  dirty: readonly string[];
}

export interface UpdateSafetySnapshot extends UpdateSafetyReasons {
  isBusy: boolean;
  isDirty: boolean;
}

interface UpdateSafetyContextValue {
  removeSource: (source: string) => void;
  snapshot: UpdateSafetySnapshot;
  updateSource: (source: string, reasons: UpdateSafetyReasons) => void;
}

const EMPTY_SNAPSHOT: UpdateSafetySnapshot = {
  busy: [],
  dirty: [],
  isBusy: false,
  isDirty: false,
};

const UpdateSafetyContext = createContext<UpdateSafetyContextValue>({
  removeSource: () => undefined,
  snapshot: EMPTY_SNAPSHOT,
  updateSource: () => undefined,
});

function normalizedReasons(reasons: readonly string[]): string[] {
  return [...new Set(reasons)].sort((left, right) => left.localeCompare(right));
}

export function UpdateSafetyProvider({ children }: { children: ReactNode }) {
  const [sources, setSources] = useState(
    () => new Map<string, UpdateSafetyReasons>(),
  );
  const updateSource = useCallback(
    (source: string, reasons: UpdateSafetyReasons) => {
      setSources((current) => {
        const next = new Map(current);
        next.set(source, {
          busy: normalizedReasons(reasons.busy),
          dirty: normalizedReasons(reasons.dirty),
        });
        return next;
      });
    },
    [],
  );
  const removeSource = useCallback((source: string) => {
    setSources((current) => {
      if (!current.has(source)) return current;
      const next = new Map(current);
      next.delete(source);
      return next;
    });
  }, []);
  const snapshot = useMemo<UpdateSafetySnapshot>(() => {
    const busy = normalizedReasons(
      [...sources.values()].flatMap((source) => source.busy),
    );
    const dirty = normalizedReasons(
      [...sources.values()].flatMap((source) => source.dirty),
    );
    return {
      busy,
      dirty,
      isBusy: busy.length > 0,
      isDirty: dirty.length > 0,
    };
  }, [sources]);
  const value = useMemo(
    () => ({ removeSource, snapshot, updateSource }),
    [removeSource, snapshot, updateSource],
  );

  return (
    <UpdateSafetyContext.Provider value={value}>
      {children}
    </UpdateSafetyContext.Provider>
  );
}

export function useUpdateSafetyRegistration(
  source: string,
  reasons: UpdateSafetyReasons,
) {
  const { removeSource, updateSource } = useContext(UpdateSafetyContext);
  const busyKey = JSON.stringify(normalizedReasons(reasons.busy));
  const dirtyKey = JSON.stringify(normalizedReasons(reasons.dirty));

  useLayoutEffect(() => {
    updateSource(source, {
      busy: JSON.parse(busyKey) as string[],
      dirty: JSON.parse(dirtyKey) as string[],
    });
  }, [busyKey, dirtyKey, source, updateSource]);

  useLayoutEffect(
    () => () => {
      removeSource(source);
    },
    [removeSource, source],
  );
}

export function useUpdateSafetySnapshot(): UpdateSafetySnapshot {
  return useContext(UpdateSafetyContext).snapshot;
}
