"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { queueService, type QueueStatusResponse } from "@/services/QueueService";
import { workspaceStore } from "@/lib/storage";

interface SyncQueueContextType {
  status: QueueStatusResponse | null;
  isSyncing: boolean;
  activeJobName: string;
  showCompleted: boolean;
  completedMessage: string;
  notifySyncStarted: (name?: string) => void;
  dismissCompleted: () => void;
  refresh: () => Promise<void>;
}

const SyncQueueContext = createContext<SyncQueueContextType | null>(null);

export function SyncQueueProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<QueueStatusResponse | null>(null);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [activeJobName, setActiveJobName] = useState<string>("Workspace Data");
  const [showCompleted, setShowCompleted] = useState<boolean>(false);
  const [completedMessage, setCompletedMessage] = useState<string>("");
  const prevSyncingRef = useRef<boolean>(false);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);

  const fetchStatus = useCallback(async () => {
    const wsId = workspaceStore.getWorkspaceId();
    if (!wsId) return;

    try {
      const data = await queueService.getStatus(wsId);
      setStatus(data);

      const hasActiveSync = data.syncing_count > 0;

      // Detect completion transition
      if (prevSyncingRef.current && !hasActiveSync) {
        setIsSyncing(false);
        const completedSource = data.items.find((i) => i.status === "completed");
        const msg = completedSource
          ? `"${completedSource.name}" sync finished (${completedSource.items_count} cards indexed)`
          : "Workspace sync completed successfully";
        setCompletedMessage(msg);
        setShowCompleted(true);
      } else if (hasActiveSync) {
        setIsSyncing(true);
        const activeItem = data.items.find((i) => i.status === "running");
        if (activeItem) {
          setActiveJobName(activeItem.name);
        }
      }

      prevSyncingRef.current = hasActiveSync;
    } catch {
      // silently ignore background polling errors
    }
  }, []);

  const notifySyncStarted = useCallback((name?: string) => {
    if (name) setActiveJobName(name);
    setIsSyncing(true);
    prevSyncingRef.current = true;
    setShowCompleted(false);
    // Immediate refresh
    void fetchStatus();
  }, [fetchStatus]);

  const dismissCompleted = useCallback(() => {
    setShowCompleted(false);
  }, []);

  // Polling loop: 2.5s if syncing, 20s if idle
  useEffect(() => {
    const intervalMs = isSyncing ? 2500 : 20000;

    void fetchStatus();

    pollTimerRef.current = setInterval(() => {
      void fetchStatus();
    }, intervalMs);

    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [fetchStatus, isSyncing]);

  // Auto-dismiss completed notification after 6 seconds
  useEffect(() => {
    if (!showCompleted) return;
    const timer = setTimeout(() => {
      setShowCompleted(false);
    }, 6000);
    return () => clearTimeout(timer);
  }, [showCompleted]);

  return (
    <SyncQueueContext.Provider
      value={{
        status,
        isSyncing,
        activeJobName,
        showCompleted,
        completedMessage,
        notifySyncStarted,
        dismissCompleted,
        refresh: fetchStatus,
      }}
    >
      {children}
    </SyncQueueContext.Provider>
  );
}

export function useSyncQueue() {
  const context = useContext(SyncQueueContext);
  if (!context) {
    return {
      status: null,
      isSyncing: false,
      activeJobName: "",
      showCompleted: false,
      completedMessage: "",
      notifySyncStarted: () => {},
      dismissCompleted: () => {},
      refresh: async () => {},
    };
  }
  return context;
}

