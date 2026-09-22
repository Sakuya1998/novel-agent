import { AlertTriangle, Check, ListTree, Send } from "lucide-react";
import type { ScenePlanItem } from "../types";
import type { ReviewBusyAction } from "../useReviewWorkflow";

export interface ReviewDecisionPanelProps {
  scenePlan: ScenePlanItem[];
  sceneNumber: number | undefined;
  feedback: string;
  busyAction: ReviewBusyAction;
  disabled: boolean;
  error: string;
  onSceneChange: (sceneNumber: number | undefined) => void;
  onFeedbackChange: (feedback: string) => void;
  onRevise: () => void | Promise<void>;
  onApprove: () => void | Promise<void>;
}

export function ReviewDecisionPanel({
  scenePlan,
  sceneNumber,
  feedback,
  busyAction,
  disabled,
  error,
  onSceneChange,
  onFeedbackChange,
  onRevise,
  onApprove,
}: ReviewDecisionPanelProps) {
  const isBusy = Boolean(busyAction);
  const controlsDisabled = disabled || isBusy;
  const feedbackLabel = sceneNumber === undefined ? "整章修改意见" : `第 ${sceneNumber} 场修改意见`;

  return <>
    {scenePlan.length > 0 ? <div className="scene-plan-block">
      <div className="block-label"><ListTree size={14} />修改范围</div>
      <button
        type="button"
        className={`scope-option ${sceneNumber === undefined ? "active" : ""}`}
        aria-pressed={sceneNumber === undefined}
        onClick={() => onSceneChange(undefined)}
        disabled={controlsDisabled}
      >整章修改</button>
      {scenePlan.map((scene) => <button
        type="button"
        className={`scene-plan-row ${sceneNumber === scene.scene_number ? "active" : ""}`}
        aria-label={`第 ${scene.scene_number} 场：${scene.goal}`}
        aria-pressed={sceneNumber === scene.scene_number}
        onClick={() => onSceneChange(scene.scene_number)}
        disabled={controlsDisabled}
        key={scene.scene_number}
      >
        <span>{String(scene.scene_number).padStart(2, "0")}</span>
        <div><strong>{scene.goal}</strong><p>{scene.location} · {scene.emotion} · {scene.estimated_words} 字</p></div>
      </button>)}
    </div> : null}
    {error ? <div className="error-callout" role="alert"><AlertTriangle size={16} /><span>{error}</span></div> : null}
    <div className="review-form review-decision">
      <div className="block-label"><Send size={14} />审查决定</div>
      <label htmlFor="review-feedback">{feedbackLabel}</label>
      <textarea
        id="review-feedback"
        value={feedback}
        onChange={(event) => onFeedbackChange(event.target.value)}
        placeholder={sceneNumber === undefined ? "写下整章需要重写的方向……" : "说明这个场景需要怎样调整……"}
        disabled={controlsDisabled}
        rows={5}
      />
      <div className="review-actions">
        <button
          type="button"
          className="secondary-button"
          onClick={() => void onRevise()}
          disabled={controlsDisabled || !feedback.trim()}
        >
          <Send size={14} />{busyAction === "revision" ? "重写中…" : sceneNumber === undefined ? "重写整章" : "重写此场景"}
        </button>
        <button
          type="button"
          className="primary-button"
          onClick={() => void onApprove()}
          disabled={controlsDisabled}
        >
          <Check size={15} />{busyAction === "approve" ? "定稿中…" : "通过定稿"}
        </button>
      </div>
    </div>
  </>;
}
