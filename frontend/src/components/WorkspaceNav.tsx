import { BookOpenText, Gauge, LibraryBig, Map } from "lucide-react";
import type { NovelStatus } from "../types";

export type WorkspaceView = "write" | "plan" | "knowledge" | "quality";

interface Props {
  active: WorkspaceView;
  status: NovelStatus;
  issueCount: number;
  onChange: (view: WorkspaceView) => void;
}

const ITEMS = [
  { id: "write", label: "写作", icon: BookOpenText },
  { id: "plan", label: "规划", icon: Map },
  { id: "knowledge", label: "设定", icon: LibraryBig },
  { id: "quality", label: "质量", icon: Gauge },
] as const;

export function WorkspaceNav({ active, status, issueCount, onChange }: Props) {
  const planningReview = status === "blueprint_review" || status === "scene_review";

  return (
    <nav className="workspace-nav" aria-label="作品工作区">
      <div role="tablist" aria-label="作品视图">
        {ITEMS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={active === id}
            className={active === id ? "active" : ""}
            onClick={() => onChange(id)}
          >
            <Icon size={15} />
            <span>{label}</span>
            {id === "plan" && planningReview ? <em>待审</em> : null}
            {id === "quality" && issueCount > 0 ? <em>{issueCount}</em> : null}
          </button>
        ))}
      </div>
    </nav>
  );
}
