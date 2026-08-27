import { ArrowUpRight, FileUp, Plus, Settings2 } from "lucide-react";
import type { ServiceStatus } from "../useServiceStatus";

interface Props {
  serviceStatus: ServiceStatus;
  onCreate: () => void;
  onImport: () => void;
  onSettings: () => void;
}

const STATUS_COPY: Record<ServiceStatus, { label: string; detail: string }> = {
  checking: { label: "正在检查服务", detail: "连接状态确认中" },
  ready: { label: "工作区已就绪", detail: "可以创建或导入作品" },
  degraded: { label: "服务需要关注", detail: "部分能力可能暂不可用" },
  offline: { label: "服务未连接", detail: "启动后端服务后继续" },
};

export function EmptyWorkspace({ serviceStatus, onCreate, onImport, onSettings }: Props) {
  const status = STATUS_COPY[serviceStatus];

  return (
    <section className="empty-workspace">
      <header className="empty-workspace-header">
        <div>
          <span className="section-label">作品库</span>
          <h1>开始一个新故事</h1>
          <p>从新的创作蓝图开始，或继续已有的作品归档。</p>
        </div>
        <button className="primary-button" type="button" onClick={onCreate}>
          <Plus size={16} />新建作品
        </button>
      </header>

      <div className="empty-workspace-actions" aria-label="作品库操作">
        <button type="button" onClick={onCreate}>
          <span className="empty-action-icon"><Plus size={18} /></span>
          <span><strong>新建作品</strong><small>创建标题、类型与创作约束</small></span>
          <ArrowUpRight size={16} />
        </button>
        <button type="button" onClick={onImport}>
          <span className="empty-action-icon"><FileUp size={18} /></span>
          <span><strong>导入作品</strong><small>从文稿或备份恢复工作区</small></span>
          <ArrowUpRight size={16} />
        </button>
        <button type="button" onClick={onSettings}>
          <span className="empty-action-icon"><Settings2 size={18} /></span>
          <span><strong>模型设置</strong><small>配置创作、分析与向量模型</small></span>
          <ArrowUpRight size={16} />
        </button>
      </div>

      <footer className={`empty-workspace-status ${serviceStatus}`}>
        <span className={`status-dot ${serviceStatus}`} />
        <div><strong>{status.label}</strong><small>{status.detail}</small></div>
      </footer>
    </section>
  );
}
