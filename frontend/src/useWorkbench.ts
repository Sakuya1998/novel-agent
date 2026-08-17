import { useCallback, useEffect, useState } from "react";
import { createNovel, deleteNovel, getNovel, getNovelState, listNovels, streamNovel } from "./api";
import type { Novel, StreamEvent, WorkbenchState } from "./types";

const emptyState = (id: string): WorkbenchState => ({
  novel_id: id,
  status: "idle",
  current_chapter: 1,
  current_phase: "idle",
  chapters_done: 0,
  total_chapters: 0,
  next: [],
  current_draft: {},
  issues: [],
  persistence_error: "",
});

export function useWorkbench() {
  const [novels, setNovels] = useState<Novel[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [novel, setNovel] = useState<Novel>();
  const [state, setState] = useState<WorkbenchState>();
  const [lastNode, setLastNode] = useState<string>();
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isStreaming, setIsStreaming] = useState(false);
  const [deletingId, setDeletingId] = useState<string>();

  const refreshList = useCallback(async () => {
    const items = await listNovels();
    setNovels(items);
    setSelectedId((current) => current && items.some((item) => item.id === current) ? current : items[0]?.id);
  }, []);

  const refreshSelected = useCallback(async (id: string) => {
    const [detail, summary] = await Promise.all([getNovel(id), getNovelState(id)]);
    setNovel(detail);
    setState(summary);
  }, []);

  useEffect(() => {
    refreshList().catch((err: unknown) => setError(err instanceof Error ? err.message : "无法加载作品")).finally(() => setIsLoading(false));
  }, [refreshList]);

  useEffect(() => {
    if (!selectedId) {
      setNovel(undefined);
      setState(undefined);
      return;
    }
    setError("");
    setLastNode(undefined);
    refreshSelected(selectedId).catch((err: unknown) => setError(err instanceof Error ? err.message : "无法加载作品状态"));
  }, [refreshSelected, selectedId]);

  const handleEvent = useCallback((event: StreamEvent) => {
    if (event.type === "node_done") setLastNode(event.node);
    if (event.type === "interrupt") {
      setState((current) => current ? {
        ...current,
        status: "human_review",
        current_draft: { ...current.current_draft, chapter_number: event.chapter_number, title: event.title, content: event.content },
        issues: event.issues ?? current.issues,
        persistence_error: event.persistence_error ?? current.persistence_error,
      } : current);
    }
    if (event.type === "error") setError(event.message);
  }, []);

  const run = useCallback(async (id = selectedId) => {
    if (!id) return;
    setError("");
    setIsStreaming(true);
    try {
      setState((current) => ({ ...(current ?? emptyState(id)), status: "running" }));
      await streamNovel(id, "run", undefined, handleEvent);
      await refreshSelected(id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "创作运行失败");
      await refreshSelected(id).catch(() => undefined);
    } finally {
      setIsStreaming(false);
    }
  }, [handleEvent, refreshSelected, selectedId]);

  const resume = useCallback(async (feedback: string) => {
    if (!selectedId) return;
    setError("");
    setIsStreaming(true);
    try {
      setState((current) => current ? { ...current, status: "running" } : current);
      await streamNovel(selectedId, "resume", feedback, handleEvent);
      await refreshSelected(selectedId);
      await refreshList();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "恢复创作失败");
      await refreshSelected(selectedId).catch(() => undefined);
    } finally {
      setIsStreaming(false);
    }
  }, [handleEvent, refreshList, refreshSelected, selectedId]);

  const addNovel = useCallback(async (payload: Pick<Novel, "title" | "genre" | "inspiration" | "total_chapters" | "style">) => {
    setError("");
    const created = await createNovel(payload);
    setNovels((current) => [created, ...current]);
    setSelectedId(created.id);
    setNovel(created);
    setState(emptyState(created.id));
    await run(created.id);
  }, [run]);

  const removeNovel = useCallback(async (id: string) => {
    setError("");
    setDeletingId(id);
    try {
      await deleteNovel(id);
      if (selectedId === id) {
        setNovel(undefined);
        setState(undefined);
        setLastNode(undefined);
      }
      await refreshList();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "删除作品失败");
      throw err;
    } finally {
      setDeletingId(undefined);
    }
  }, [refreshList, selectedId]);

  return { novels, novel, state, selectedId, setSelectedId, lastNode, error, isLoading, isStreaming, deletingId, run, resume, addNovel, removeNovel };
}
