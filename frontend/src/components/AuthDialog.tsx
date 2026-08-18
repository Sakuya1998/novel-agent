import { LogIn, LogOut, UserPlus, X } from "lucide-react";
import { useState } from "react";
import type { AuthSession, AuthUser } from "../types";

interface Props {
  open: boolean;
  currentUser: AuthUser | null;
  onLogin: (identifier: string, password: string) => Promise<AuthSession>;
  onRegister: (payload: { username: string; email: string; password: string; display_name: string; tenant_name: string }) => Promise<AuthSession>;
  onLogout: () => Promise<void>;
  onClose: () => void;
}

export function AuthDialog({ open, currentUser, onLogin, onRegister, onLogout, onClose }: Props) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [identifier, setIdentifier] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [tenantName, setTenantName] = useState("我的工作区");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setBusy(true);
    setError("");
    try {
      if (mode === "login") {
        await onLogin(identifier.trim(), password);
      } else {
        await onRegister({
          username: username.trim(),
          email: email.trim(),
          password,
          display_name: displayName.trim(),
          tenant_name: tenantName.trim(),
        });
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "认证失败");
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;
  return <div className="model-settings-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className="model-settings-dialog auth-dialog" role="dialog" aria-modal="true" aria-labelledby="auth-title">
      <header className="model-settings-header"><div><span className="eyebrow">WORKSPACE ACCESS</span><h2 id="auth-title">工作区身份</h2></div><button type="button" className="dialog-close-button" aria-label="关闭身份窗口" title="关闭" onClick={onClose}><X size={18} /></button></header>
      {currentUser ? <div className="auth-current"><div><span>{currentUser.display_name || currentUser.username}</span><strong>{currentUser.tenant_name}</strong><small>{currentUser.role} · {currentUser.username}</small></div><button type="button" className="secondary-button" onClick={() => void onLogout()}><LogOut size={14} />退出登录</button></div> : <>
        <div className="auth-tabs"><button type="button" className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}><LogIn size={14} />登录</button><button type="button" className={mode === "register" ? "active" : ""} onClick={() => setMode("register")}><UserPlus size={14} />注册工作区</button></div>
        <form className="auth-form" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          {mode === "login" ? <label>用户名或邮箱<input aria-label="用户名或邮箱" autoComplete="username" value={identifier} onChange={(event) => setIdentifier(event.target.value)} required /></label> : <>
            <label>用户名<input aria-label="用户名" autoComplete="username" minLength={3} value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
            <label>邮箱<input aria-label="邮箱" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
            <label>显示名称<input aria-label="显示名称" value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
            <label>工作区名称<input aria-label="工作区名称" value={tenantName} onChange={(event) => setTenantName(event.target.value)} required /></label>
          </>}
          <label>密码<input aria-label="密码" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={mode === "register" ? 8 : 1} value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
          {error && <p className="auth-error">{error}</p>}
          <button type="submit" className="primary-button" aria-label={mode === "login" ? "提交登录" : "提交注册"} disabled={busy}>{mode === "login" ? <LogIn size={14} /> : <UserPlus size={14} />}{busy ? "提交中" : mode === "login" ? "登录" : "创建工作区"}</button>
        </form>
      </>}
    </section>
  </div>;
}
