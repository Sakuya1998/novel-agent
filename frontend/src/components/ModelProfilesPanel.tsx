import { CheckCircle2, FlaskConical, LoaderCircle, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ModelProfile, ModelProfileWrite, ModelSettings, ProviderName, ProviderTemplate } from "../types";

interface Props {
  settings: ModelSettings;
  selectedId?: string;
  disabled: boolean;
  busyAction: string;
  onSelect: (id?: string) => void;
  onSave: (payload: ModelProfileWrite, id?: string) => Promise<ModelProfile>;
  onDelete: (id: string) => Promise<unknown>;
  onTest: (id: string, kind: "chat" | "embedding", modelName: string) => Promise<unknown>;
}

const splitModels = (value: string) => value
  .split(/[\n,]/)
  .map((item) => item.trim())
  .filter((item, index, values) => item && values.indexOf(item) === index);

const joinModels = (models: string[]) => models.join("\n");

const emptyTemplate = {
  label: "未知供应商",
  group: "其他",
  protocol: "openai" as const,
  base_url: "",
  base_url_mode: "required" as const,
  api_key_required: true,
  supports_embeddings: true,
  chat_models: [],
  embedding_models: [],
};

export function ModelProfilesPanel({
  settings,
  selectedId,
  disabled,
  busyAction,
  onSelect,
  onSave,
  onDelete,
  onTest,
}: Props) {
  const selected = useMemo(
    () => settings.profiles.find((profile) => profile.id === selectedId),
    [selectedId, settings.profiles],
  );
  const [name, setName] = useState("");
  const [provider, setProvider] = useState<ProviderName>("openai");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [chatModels, setChatModels] = useState("");
  const [embeddingModels, setEmbeddingModels] = useState("");

  useEffect(() => {
    if (selected) {
      setName(selected.name);
      setProvider(selected.provider);
      setBaseUrl(selected.base_url);
      setApiKey("");
      setClearApiKey(false);
      setChatModels(joinModels(selected.chat_models));
      setEmbeddingModels(joinModels(selected.embedding_models));
      return;
    }
    const template = settings.templates.openai ?? emptyTemplate;
    setName("");
    setProvider("openai");
    setBaseUrl(template.base_url);
    setApiKey("");
    setClearApiKey(false);
    setChatModels(joinModels(template.chat_models));
    setEmbeddingModels(joinModels(template.embedding_models));
  }, [selected, settings.templates]);

  const isBusy = Boolean(busyAction);
  const formDisabled = disabled || isBusy;
  const parsedChatModels = splitModels(chatModels);
  const parsedEmbeddingModels = splitModels(embeddingModels);
  const activeTemplate = settings.templates[provider] ?? emptyTemplate;
  const baseUrlMode = activeTemplate.base_url_mode
    ?? (provider === "anthropic" ? "hidden" : provider === "openai" ? "fixed" : "required");
  const apiKeyRequired = activeTemplate.api_key_required ?? !["ollama", "openai_compatible"].includes(provider);
  const supportsEmbeddings = activeTemplate.supports_embeddings ?? provider !== "anthropic";
  const providerGroups = useMemo(() => {
    const groups = new Map<string, Array<[string, ProviderTemplate]>>();
    Object.entries(settings.templates).forEach(([id, template]) => {
      const group = template.group || "其他服务";
      const items = groups.get(group) ?? [];
      items.push([id, template]);
      groups.set(group, items);
    });
    return [...groups.entries()];
  }, [settings.templates]);

  function changeProvider(next: ProviderName) {
    const template = settings.templates[next] ?? emptyTemplate;
    setProvider(next);
    setBaseUrl(template.base_url);
    setChatModels(joinModels(template.chat_models));
    setEmbeddingModels(joinModels(template.embedding_models));
  }

  async function save() {
    const saved = await onSave({
      name: name.trim(),
      provider,
      base_url: baseUrl.trim(),
      api_key: apiKey.trim(),
      clear_api_key: clearApiKey,
      chat_models: parsedChatModels,
      embedding_models: parsedEmbeddingModels,
    }, selected?.id);
    setApiKey("");
    setClearApiKey(false);
    if (!selected) onSelect(saved.id);
  }

  async function remove() {
    if (!selected) return;
    if (!window.confirm(`确认删除模型服务“${selected.name}”吗？`)) return;
    const nextProfileId = settings.profiles.find((profile) => profile.id !== selected.id)?.id;
    await onDelete(selected.id);
    onSelect(nextProfileId);
  }

  return <div className="model-profile-layout">
    <aside className="model-profile-list" aria-label="模型服务列表">
      <button className="model-profile-add" type="button" onClick={() => onSelect(undefined)} disabled={formDisabled}>
        <Plus size={15} /> 新增模型服务
      </button>
      {settings.profiles.length === 0 ? <p className="model-settings-empty">尚未保存模型服务</p> : settings.profiles.map((profile) => (
        <button
          className={`model-profile-option ${profile.id === selectedId ? "active" : ""}`}
          type="button"
          key={profile.id}
          onClick={() => onSelect(profile.id)}
        >
          <span><strong>{profile.name}</strong><small>{settings.templates[profile.provider]?.label ?? profile.provider}</small></span>
          {profile.has_api_key ? <CheckCircle2 size={14} /> : null}
        </button>
      ))}
    </aside>

    <section className="model-profile-editor">
      <div className="model-editor-heading">
        <div><span className="eyebrow">PROVIDER PROFILE</span><h3>{selected ? "编辑模型服务" : "新增模型服务"}</h3></div>
        {selected ? <button className="danger-icon-button" type="button" title="删除模型服务" aria-label="删除模型服务" disabled={formDisabled} onClick={() => void remove().catch(() => undefined)}><Trash2 size={16} /></button> : null}
      </div>

      <div className="model-form-grid">
        <label>供应商
          <select value={provider} disabled={formDisabled} onChange={(event) => changeProvider(event.target.value as ProviderName)}>
            {providerGroups.map(([group, providers]) => <optgroup label={group} key={group}>
              {providers.map(([id, template]) => <option value={id} key={id}>{template.label}</option>)}
            </optgroup>)}
          </select>
        </label>
        <label>服务名称
          <input value={name} disabled={formDisabled} maxLength={80} onChange={(event) => setName(event.target.value)} placeholder="例如：DeepSeek 主服务" />
        </label>
        <label className="model-form-wide">API 地址
          <input value={baseUrl} disabled={formDisabled || baseUrlMode !== "required"} onChange={(event) => setBaseUrl(event.target.value)} placeholder={baseUrlMode === "hidden" ? "由供应商 SDK 管理" : "https://api.example.com/v1"} />
        </label>
        <label className="model-form-wide">API Key
          <input aria-label="API Key" type="password" autoComplete="new-password" value={apiKey} disabled={formDisabled || clearApiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={selected?.has_api_key ? "留空保留现有密钥" : apiKeyRequired ? "输入 API Key" : "可选"} />
          {selected?.has_api_key ? <small className="configured-secret">已配置 · {selected.api_key_masked}</small> : <small>{apiKeyRequired ? "密钥只会加密保存，不会从接口返回明文" : "此服务允许无密钥连接"}</small>}
        </label>
        {selected?.has_api_key ? <label className="model-clear-key"><input type="checkbox" checked={clearApiKey} disabled={formDisabled} onChange={(event) => setClearApiKey(event.target.checked)} /> 清除已保存密钥</label> : null}
        <label>聊天模型（每行一个）
          <textarea rows={5} value={chatModels} disabled={formDisabled} onChange={(event) => setChatModels(event.target.value)} />
        </label>
        <label>嵌入模型（每行一个）
          <textarea rows={5} value={embeddingModels} disabled={formDisabled || !supportsEmbeddings} onChange={(event) => setEmbeddingModels(event.target.value)} />
        </label>
      </div>

      <div className="model-editor-actions">
        <button className="secondary-button" type="button" disabled={formDisabled || !selected || parsedChatModels.length === 0} onClick={() => selected && void onTest(selected.id, "chat", parsedChatModels[0]).catch(() => undefined)}>
          {busyAction === "test-chat" ? <LoaderCircle className="spin" size={14} /> : <FlaskConical size={14} />} 测试聊天模型
        </button>
        {supportsEmbeddings ? <button className="secondary-button" type="button" disabled={formDisabled || !selected || parsedEmbeddingModels.length === 0} onClick={() => selected && void onTest(selected.id, "embedding", parsedEmbeddingModels[0]).catch(() => undefined)}>
          {busyAction === "test-embedding" ? <LoaderCircle className="spin" size={14} /> : <FlaskConical size={14} />} 测试嵌入模型
        </button> : null}
        <button className="primary-button model-save-button" type="button" disabled={formDisabled || !name.trim()} onClick={() => void save().catch(() => undefined)}>
          {busyAction === "save-profile" ? <LoaderCircle className="spin" size={14} /> : null} 保存服务
        </button>
      </div>
    </section>
  </div>;
}
