import { Check, Circle, LoaderCircle, MessageSquareText } from "lucide-react";
import { STAGES } from "../types";

interface Props { lastNode?: string; status: string; currentPhase: string; }

export function StageRail({ lastNode, status, currentPhase }: Props) {
  const activeIndex = Math.max(STAGES.findIndex((stage) => stage.id === lastNode), STAGES.findIndex((stage) => stage.id === currentPhase));
  return (
    <div className="stage-rail" aria-label="创作阶段">
      {STAGES.map((stage, index) => {
        const complete = status === "completed" || index < activeIndex;
        const active = status.endsWith("_review") ? stage.id === status : index === activeIndex;
        return <div className={`stage ${complete ? "complete" : ""} ${active ? "active" : ""}`} key={stage.id}>
          <div className="stage-icon">{complete ? <Check size={14} /> : active ? <LoaderCircle className="spin" size={14} /> : stage.id.endsWith("_review") ? <MessageSquareText size={14} /> : <Circle size={9} />}</div>
          <span>{stage.label}</span>
          {index < STAGES.length - 1 && <i className={complete ? "filled" : ""} />}
        </div>;
      })}
    </div>
  );
}
