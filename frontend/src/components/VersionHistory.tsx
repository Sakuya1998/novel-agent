import { GitCompareArrows, History, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import type { ChapterVersion } from "../types";

interface Props {
  versions: ChapterVersion[];
  disabled: boolean;
  onCompare: (fromVersion: number, toVersion: number) => Promise<string>;
  onRestore: (versionNumber: number) => Promise<void>;
}

const SOURCE_LABELS: Record<string, string> = {
  initial: "初稿",
  revision: "整章修订",
  scene_revision: "场景修订",
  restored: "历史恢复",
  final: "定稿",
};

export function VersionHistory({ versions, disabled, onCompare, onRestore }: Props) {
  const [fromVersion, setFromVersion] = useState(0);
  const [toVersion, setToVersion] = useState(0);
  const [diff, setDiff] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const latest = versions.at(-1)?.version_number ?? 0;
    const previous = versions.at(-2)?.version_number ?? latest;
    setFromVersion(previous);
    setToVersion(latest);
    setDiff("");
  }, [versions]);

  async function compare() {
    if (!fromVersion || !toVersion) return;
    setLoading(true);
    try {
      setDiff(await onCompare(fromVersion, toVersion));
    } finally {
      setLoading(false);
    }
  }

  if (!versions.length) return null;
  return <div className="version-history">
    <div className="block-label"><History size={14} />版本历史</div>
    <div className="version-list">{versions.map((version) => <div className="version-row" key={version.version_number}>
      <span>v{version.version_number}</span>
      <div><strong>{SOURCE_LABELS[version.source] ?? version.source}</strong><small>{version.word_count} 字</small></div>
      <button type="button" className="version-restore" title={`恢复 v${version.version_number}`} aria-label={`恢复 v${version.version_number}`} disabled={disabled} onClick={() => onRestore(version.version_number)}><RotateCcw size={13} /></button>
    </div>)}</div>
    {versions.length > 1 && <div className="version-compare">
      <select aria-label="基线版本" value={fromVersion} onChange={(event) => setFromVersion(Number(event.target.value))} disabled={disabled || loading}>{versions.map((version) => <option value={version.version_number} key={version.version_number}>v{version.version_number}</option>)}</select>
      <span>→</span>
      <select aria-label="目标版本" value={toVersion} onChange={(event) => setToVersion(Number(event.target.value))} disabled={disabled || loading}>{versions.map((version) => <option value={version.version_number} key={version.version_number}>v{version.version_number}</option>)}</select>
      <button type="button" className="version-compare-button" title="比较版本" aria-label="比较版本" onClick={compare} disabled={disabled || loading || fromVersion === toVersion}><GitCompareArrows size={14} /></button>
    </div>}
    {diff && <pre className="version-diff">{diff}</pre>}
  </div>;
}
