import { Download, FileArchive, FileUp, X } from "lucide-react";
import { useRef, useState } from "react";

interface Props {
  open: boolean;
  novelTitle: string;
  onClose: () => void;
  onExport: (format: string, password: string, metadata: { author: string; publisher: string; language: string }) => Promise<{ blob: Blob; filename: string }>;
  onImport: (file: File, title: string, password: string) => Promise<unknown>;
}

const FORMATS = [
  ["markdown", "Markdown"],
  ["txt", "纯文本"],
  ["docx", "DOCX"],
  ["epub", "EPUB"],
  ["backup", "完整备份 ZIP"],
] as const;

export function ImportExportDialog({ open, novelTitle, onClose, onExport, onImport }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [format, setFormat] = useState("markdown");
  const [exportPassword, setExportPassword] = useState("");
  const [importPassword, setImportPassword] = useState("");
  const [author, setAuthor] = useState("");
  const [publisher, setPublisher] = useState("");
  const [language, setLanguage] = useState("zh-CN");
  const [file, setFile] = useState<File>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  if (!open) return null;

  async function exportBook() {
    setBusy(true); setMessage("");
    try {
      const result = await onExport(
        format,
        format === "backup" ? exportPassword : "",
        { author, publisher, language },
      );
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = result.filename; anchor.click(); URL.revokeObjectURL(url);
      setMessage("导出已开始");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "导出失败"); } finally { setBusy(false); }
  }

  async function importBook() {
    if (!file) return;
    setBusy(true); setMessage("");
    try { await onImport(file, "", importPassword); setMessage("导入完成，作品列表已更新"); setFile(undefined); setImportPassword(""); if (inputRef.current) inputRef.current.value = ""; } catch (reason) { setMessage(reason instanceof Error ? reason.message : "导入失败"); } finally { setBusy(false); }
  }

  return <section className="model-settings-dialog import-export-dialog" role="dialog" aria-modal="true" aria-labelledby="import-export-title">
    <div className="memory-quality-header"><div className="dialog-title"><FileArchive size={18} /><div><span className="eyebrow">PORTABILITY</span><h2 id="import-export-title">导入与导出</h2></div></div><button type="button" className="icon-button" title="关闭" aria-label="关闭" onClick={onClose}><X size={16} /></button></div>
    <div className="import-export-body"><section><div className="block-label"><Download size={14} />导出《{novelTitle}》</div><div className="import-export-row"><select aria-label="导出格式" value={format} onChange={(event) => setFormat(event.target.value)} disabled={busy}>{FORMATS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select><button type="button" className="primary-button" onClick={() => void exportBook()} disabled={busy}><Download size={14} />导出文件</button></div><div className="import-export-metadata"><label>作者<input aria-label="出版作者" value={author} onChange={(event) => setAuthor(event.target.value)} placeholder="未署名" disabled={busy} /></label><label>出版者<input aria-label="出版者" value={publisher} onChange={(event) => setPublisher(event.target.value)} placeholder="可选" disabled={busy} /></label><label>语言<select aria-label="出版语言" value={language} onChange={(event) => setLanguage(event.target.value)} disabled={busy}><option value="zh-CN">中文</option><option value="en">English</option><option value="ja">日本語</option></select></label></div>{format === "backup" && <label className="import-export-password">备份密码<input aria-label="导出备份密码" type="password" value={exportPassword} onChange={(event) => setExportPassword(event.target.value)} placeholder="留空则导出明文 ZIP" disabled={busy} /></label>}</section><section><div className="block-label"><FileUp size={14} />导入作品</div><input ref={inputRef} type="file" accept=".md,.markdown,.txt,.docx,.epub,.zip,.novel-backup.zip,.enc" onChange={(event) => setFile(event.target.files?.[0])} disabled={busy} /><label className="import-export-password">备份密码<input aria-label="导入备份密码" type="password" value={importPassword} onChange={(event) => setImportPassword(event.target.value)} placeholder="加密备份需要填写" disabled={busy} /></label><button type="button" className="secondary-button import-submit" onClick={() => void importBook()} disabled={busy || !file}><FileUp size={14} />导入到当前工作区</button></section>{message && <p className="import-export-message">{message}</p>}</div>
  </section>;
}
