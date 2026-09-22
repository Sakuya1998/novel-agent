import {
  Activity,
  Download,
  FlaskConical,
  RefreshCw,
  Settings,
  ShieldCheck,
  Monitor,
  UserRound,
  Wrench,
} from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import type { AuthUser } from "../types";
import type { ServiceStatus } from "../useServiceStatus";

interface Props {
  projectTitle?: string;
  serviceStatus?: ServiceStatus;
  authEnabled?: boolean;
  authUser: AuthUser | null;
  onOpenAuth: () => void;
  onOpenMonitoring: () => void;
  onOpenBenchmarks: () => void;
  onOpenImportExport: () => void;
  onOpenTraces: () => void;
  onOpenSettings: () => void;
  onRefresh?: () => void;
}

export function WorkspaceHeader({
  projectTitle,
  serviceStatus = "checking",
  authEnabled,
  authUser,
  onOpenAuth,
  onOpenMonitoring,
  onOpenBenchmarks,
  onOpenImportExport,
  onOpenTraces,
  onOpenSettings,
  onRefresh,
}: Props) {
  const [toolsOpen, setToolsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const toolsButtonRef = useRef<HTMLButtonElement>(null);
  const focusMenuOnOpenRef = useRef(false);

  useEffect(() => {
    if (!toolsOpen) return;
    const close = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setToolsOpen(false);
    };
    const navigate = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setToolsOpen(false);
        toolsButtonRef.current?.focus();
        return;
      }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? []);
      if (!items.length) return;
      event.preventDefault();
      const current = items.indexOf(document.activeElement as HTMLButtonElement);
      const delta = event.key === "ArrowDown" ? 1 : -1;
      items[(current + delta + items.length) % items.length].focus();
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", navigate);
    if (focusMenuOnOpenRef.current) {
      focusMenuOnOpenRef.current = false;
      menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    }
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", navigate);
    };
  }, [toolsOpen]);

  function openToolsWithKeyboard(event: ReactKeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "ArrowDown") return;
    event.preventDefault();
    focusMenuOnOpenRef.current = true;
    setToolsOpen(true);
  }

  function run(action: () => void) {
    setToolsOpen(false);
    action();
  }

  const userLabel = authUser?.display_name || authUser?.username || "登录";
  const serviceLabels: Record<ServiceStatus, string> = {
    checking: "正在检查服务",
    ready: "服务正常",
    degraded: "服务需要关注",
    offline: "服务未连接",
  };

  return (
    <header className="topbar">
      <div className="workspace-context">
        <span>创作工作台</span>
        <i />
        <strong>{projectTitle || "作品库"}</strong>
      </div>
      <div className="topbar-actions">
        <span className={`connection-pill ${serviceStatus}`} role="status"><span className={`status-dot ${serviceStatus}`} />{serviceLabels[serviceStatus]}</span>
        {onRefresh && (
          <button className="icon-button" title="刷新当前作品" aria-label="刷新当前作品" onClick={onRefresh}>
            <RefreshCw size={16} />
          </button>
        )}
        <div className="tool-menu" ref={menuRef}>
          <button
            ref={toolsButtonRef}
            className={`toolbar-button ${toolsOpen ? "active" : ""}`}
            aria-expanded={toolsOpen}
            aria-haspopup="menu"
            aria-controls="workspace-tool-menu"
            onKeyDown={openToolsWithKeyboard}
            onClick={() => setToolsOpen((value) => !value)}
          >
            <Wrench size={15} />工具
          </button>
          {toolsOpen && (
            <div className="tool-menu-popover" id="workspace-tool-menu" role="menu" aria-label="工作区工具">
              <span className="menu-label">工作区</span>
              <button role="menuitem" onClick={() => run(onOpenMonitoring)}><ShieldCheck size={16} /><span><strong>运行与审计</strong><small>服务状态、任务和审计日志</small></span></button>
              <button role="menuitem" onClick={() => run(onOpenBenchmarks)}><FlaskConical size={16} /><span><strong>质量评测</strong><small>运行并比较评测基准</small></span></button>
              <button role="menuitem" onClick={() => run(onOpenImportExport)}><Download size={16} /><span><strong>导入与导出</strong><small>迁移作品或生成归档</small></span></button>
              {projectTitle && <button role="menuitem" onClick={() => run(onOpenTraces)}><Activity size={16} /><span><strong>模型调用轨迹</strong><small>查看当前作品的调用明细</small></span></button>}
              <div className="menu-separator" />
              <button role="menuitem" onClick={() => run(onOpenSettings)}><Settings size={16} /><span><strong>模型设置</strong><small>配置模型档案与路由</small></span></button>
            </div>
          )}
        </div>
        {authEnabled === false ? <div className="account-button account-status" title="本地工作区">
          <span className="account-avatar"><Monitor size={15} /></span>
          <span>本地工作区</span>
        </div> : null}
        {authEnabled === true ? <button className="account-button" onClick={onOpenAuth} title={authUser ? `${userLabel} · ${authUser.role}` : "登录工作区"}>
          <span className="account-avatar"><UserRound size={15} /></span>
          <span>{userLabel}</span>
        </button> : null}
      </div>
    </header>
  );
}
