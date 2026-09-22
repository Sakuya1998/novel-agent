import { AlertCircle, CheckCircle2, LoaderCircle, RefreshCw, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useModelSettings } from "../useModelSettings";
import { useDialogLifecycle } from "../useDialogLifecycle";
import { ModelProfilesPanel } from "./ModelProfilesPanel";
import { ModelRoutesPanel } from "./ModelRoutesPanel";

interface Props {
  open: boolean;
  isStreaming: boolean;
  onClose: () => void;
}

export function ModelSettingsDialog({ open, isStreaming, onClose }: Props) {
  const modelSettings = useModelSettings(open);
  const [tab, setTab] = useState<"profiles" | "routes">("profiles");
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>();
  const { dialogRef, onBackdropMouseDown } = useDialogLifecycle<HTMLElement>(open, onClose, Boolean(modelSettings.busyAction));

  useEffect(() => {
    if (!open) {
      setSelectedProfileId(undefined);
      return;
    }
    if (!modelSettings.settings) return;
    const profiles = modelSettings.settings.profiles;
    if (profiles.length === 0) {
      setSelectedProfileId(null);
    } else if (
      selectedProfileId === undefined
      || (selectedProfileId !== null && !profiles.some((profile) => profile.id === selectedProfileId))
    ) {
      setSelectedProfileId(profiles[0].id);
    }
  }, [modelSettings.settings, open, selectedProfileId]);

  if (!open) return null;
  const settings = modelSettings.settings;
  const sourceLabel = settings?.source === "database" ? "工作台配置" : settings?.source === "environment" ? "环境配置回退" : "尚未配置";

  return <div className="model-settings-backdrop" onMouseDown={onBackdropMouseDown}>
    <section ref={dialogRef} tabIndex={-1} className="model-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="model-settings-title">
      <header className="model-settings-header">
        <div><span className="eyebrow">MODEL CONTROL</span><h2 id="model-settings-title">模型设置</h2></div>
        <div className="model-settings-header-actions"><span className={`model-source-badge ${settings?.source ?? "unconfigured"}`}>{sourceLabel}</span><button className="dialog-close-button" type="button" title="关闭" aria-label="关闭模型设置" disabled={Boolean(modelSettings.busyAction)} onClick={onClose}><X size={18} /></button></div>
      </header>
      <div className="model-settings-tabs" role="tablist" aria-label="模型设置视图">
        <button role="tab" aria-selected={tab === "profiles"} className={tab === "profiles" ? "active" : ""} onClick={() => setTab("profiles")}>模型服务</button>
        <button role="tab" aria-selected={tab === "routes"} className={tab === "routes" ? "active" : ""} onClick={() => setTab("routes")}>模型分工</button>
      </div>
      {isStreaming ? <div className="model-settings-running"><AlertCircle size={15} />小说创作正在运行，设置暂时只读。</div> : null}
      {modelSettings.error ? <div className="model-settings-message error" role="alert" aria-live="assertive"><AlertCircle size={15} />{modelSettings.error}</div> : null}
      {modelSettings.notice ? <div className="model-settings-message success" role="status" aria-live="polite"><CheckCircle2 size={15} />{modelSettings.notice}</div> : null}
      <div className="model-settings-content">
        {modelSettings.isLoading && !settings ? <div className="model-settings-loading"><LoaderCircle className="spin" size={18} />加载模型设置</div> : null}
        {!modelSettings.isLoading && modelSettings.error && !settings ? <div className="model-settings-load-error">
          <AlertCircle size={20} />
          <strong>模型设置加载失败</strong>
          <button className="secondary-button" type="button" onClick={() => void modelSettings.reload()}><RefreshCw size={14} />重新加载</button>
        </div> : null}
        {settings && tab === "profiles" ? <ModelProfilesPanel
          settings={settings}
          selectedId={selectedProfileId ?? undefined}
          disabled={isStreaming}
          busyAction={modelSettings.busyAction}
          onSelect={(id) => setSelectedProfileId(id ?? null)}
          onSave={modelSettings.saveProfile}
          onDelete={modelSettings.removeProfile}
          onTest={modelSettings.testProfile}
        /> : null}
        {settings && tab === "routes" ? <ModelRoutesPanel
          settings={settings}
          disabled={isStreaming}
          busyAction={modelSettings.busyAction}
          onSave={modelSettings.saveRoutes}
        /> : null}
      </div>
    </section>
  </div>;
}
