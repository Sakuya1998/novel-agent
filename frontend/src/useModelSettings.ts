import { useCallback, useEffect, useState } from "react";
import {
  createModelProfile,
  deleteModelProfile,
  getModelSettings,
  saveModelRoutes,
  testModelProfile,
  updateModelProfile,
} from "./api";
import type {
  ConnectionTestResult,
  ModelProfileWrite,
  ModelRoutes,
  ModelSettings,
} from "./types";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "模型设置操作失败";
}

export function useModelSettings(open: boolean) {
  const [settings, setSettings] = useState<ModelSettings>();
  const [isLoading, setIsLoading] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const reload = useCallback(async (): Promise<boolean> => {
    setIsLoading(true);
    setError("");
    try {
      setSettings(await getModelSettings());
      return true;
    } catch (err: unknown) {
      setError(errorMessage(err));
      return false;
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void reload();
  }, [open, reload]);

  const mutate = useCallback(async <T,>(
    action: string,
    successMessage: string,
    operation: () => Promise<T>,
  ): Promise<T> => {
    setBusyAction(action);
    setError("");
    setNotice("");
    try {
      const result = await operation();
      const refreshed = await reload();
      setNotice(
        refreshed ? successMessage : `${successMessage}，但刷新失败，请重新打开模型设置`,
      );
      return result;
    } catch (err: unknown) {
      setError(errorMessage(err));
      throw err;
    } finally {
      setBusyAction("");
    }
  }, [reload]);

  const saveProfile = useCallback((payload: ModelProfileWrite, profileId?: string) => (
    mutate(
      "save-profile",
      "模型服务已保存",
      () => profileId ? updateModelProfile(profileId, payload) : createModelProfile(payload),
    )
  ), [mutate]);

  const removeProfile = useCallback((profileId: string) => (
    mutate("delete-profile", "模型服务已删除", () => deleteModelProfile(profileId))
  ), [mutate]);

  const saveRoutes = useCallback((routes: ModelRoutes) => (
    mutate("save-routes", "模型分工已保存", () => saveModelRoutes(routes))
  ), [mutate]);

  const testProfile = useCallback(async (
    profileId: string,
    kind: "chat" | "embedding",
    modelName: string,
  ): Promise<ConnectionTestResult> => {
    setBusyAction(`test-${kind}`);
    setError("");
    setNotice("");
    try {
      const result = await testModelProfile(profileId, kind, modelName);
      setNotice(`${result.message} · ${result.latency_ms} ms`);
      return result;
    } catch (err: unknown) {
      setError(errorMessage(err));
      throw err;
    } finally {
      setBusyAction("");
    }
  }, []);

  return {
    settings,
    isLoading,
    busyAction,
    error,
    notice,
    reload,
    saveProfile,
    removeProfile,
    saveRoutes,
    testProfile,
  };
}
