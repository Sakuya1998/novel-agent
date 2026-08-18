import { LoaderCircle, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ModelRoute, ModelRoutes, ModelSettings, RoutePurpose } from "../types";

interface Props {
  settings: ModelSettings;
  disabled: boolean;
  busyAction: string;
  onSave: (routes: ModelRoutes) => Promise<unknown>;
}

const routeMeta: Array<{ purpose: RoutePurpose; label: string; description: string }> = [
  { purpose: "creative", label: "创作模型", description: "世界观、角色、正文写作与润色" },
  { purpose: "analysis", label: "分析模型", description: "大纲规划与一致性检查" },
  { purpose: "embedding", label: "嵌入模型", description: "长期记忆的向量检索" },
];

function firstTarget(settings: ModelSettings, purpose: RoutePurpose): ModelRoute {
  const current = settings.routes[purpose];
  if (current) return current;
  const profile = settings.profiles.find((item) => purpose !== "embedding" || item.provider !== "anthropic");
  const models = purpose === "embedding" ? profile?.embedding_models : profile?.chat_models;
  return {
    profile_id: profile?.id ?? "",
    model_name: models?.[0] ?? "",
    fallback_profile_id: "",
    fallback_model_name: "",
  };
}

export function ModelRoutesPanel({ settings, disabled, busyAction, onSave }: Props) {
  const [routes, setRoutes] = useState<Record<RoutePurpose, ModelRoute>>(() => ({
    creative: firstTarget(settings, "creative"),
    analysis: firstTarget(settings, "analysis"),
    embedding: firstTarget(settings, "embedding"),
  }));

  useEffect(() => {
    setRoutes({
      creative: firstTarget(settings, "creative"),
      analysis: firstTarget(settings, "analysis"),
      embedding: firstTarget(settings, "embedding"),
    });
  }, [settings]);

  const profileMap = useMemo(
    () => new Map(settings.profiles.map((profile) => [profile.id, profile])),
    [settings.profiles],
  );
  const valid = routeMeta.every(({ purpose }) => {
    const route = routes[purpose];
    return route.profile_id
      && route.model_name.trim()
      && (purpose === "embedding"
        || Boolean(route.fallback_profile_id) === Boolean(route.fallback_model_name?.trim()));
  });
  const formDisabled = disabled || Boolean(busyAction);

  function changeProfile(purpose: RoutePurpose, profileId: string) {
    const profile = profileMap.get(profileId);
    const models = purpose === "embedding" ? profile?.embedding_models : profile?.chat_models;
    setRoutes((current) => ({
      ...current,
      [purpose]: {
        ...current[purpose],
        profile_id: profileId,
        model_name: models?.[0] ?? "",
      },
    }));
  }

  function changeFallbackProfile(purpose: RoutePurpose, profileId: string) {
    const profile = profileMap.get(profileId);
    setRoutes((current) => ({
      ...current,
      [purpose]: {
        ...current[purpose],
        fallback_profile_id: profileId,
        fallback_model_name: profile?.chat_models[0] ?? "",
      },
    }));
  }

  return <section className="model-routes-panel">
    <div className="model-routes-intro">
      <span className="eyebrow">MODEL ASSIGNMENT</span>
      <h3>模型分工</h3>
      <p>不同任务可以使用不同服务和模型。保存后会在下一次模型调用时生效。</p>
    </div>
    <div className="model-route-list">
      {routeMeta.map(({ purpose, label, description }) => {
        const eligibleProfiles = settings.profiles.filter((profile) => purpose !== "embedding" || profile.provider !== "anthropic");
        const selectedProfile = profileMap.get(routes[purpose].profile_id);
        const modelOptions = purpose === "embedding" ? selectedProfile?.embedding_models : selectedProfile?.chat_models;
        const fallbackProfile = profileMap.get(routes[purpose].fallback_profile_id ?? "");
        const listId = `${purpose}-primary-models`;
        const fallbackListId = `${purpose}-fallback-models`;
        return <div className="model-route-row" key={purpose}>
          <div className="model-route-copy"><strong>{label}</strong><small>{description}</small></div>
          <div className="model-route-controls">
            <label>主模型服务
              <select value={routes[purpose].profile_id} disabled={formDisabled} onChange={(event) => changeProfile(purpose, event.target.value)}>
                <option value="">选择服务</option>
                {eligibleProfiles.map((profile) => <option value={profile.id} key={profile.id}>{profile.name}</option>)}
              </select>
            </label>
            <label>主模型名称
              <input
                list={listId}
                value={routes[purpose].model_name}
                disabled={formDisabled || !routes[purpose].profile_id}
                onChange={(event) => setRoutes((current) => ({ ...current, [purpose]: { ...current[purpose], model_name: event.target.value } }))}
              />
              <datalist id={listId}>{(modelOptions ?? []).map((model) => <option value={model} key={model} />)}</datalist>
            </label>
            {purpose !== "embedding" && <>
              <label>备用模型服务
                <select value={routes[purpose].fallback_profile_id ?? ""} disabled={formDisabled} onChange={(event) => changeFallbackProfile(purpose, event.target.value)}>
                  <option value="">不使用备用模型</option>
                  {settings.profiles.map((profile) => <option value={profile.id} key={profile.id}>{profile.name}</option>)}
                </select>
              </label>
              <label>备用模型名称
                <input
                  list={fallbackListId}
                  value={routes[purpose].fallback_model_name ?? ""}
                  disabled={formDisabled || !routes[purpose].fallback_profile_id}
                  onChange={(event) => setRoutes((current) => ({ ...current, [purpose]: { ...current[purpose], fallback_model_name: event.target.value } }))}
                />
                <datalist id={fallbackListId}>{(fallbackProfile?.chat_models ?? []).map((model) => <option value={model} key={model} />)}</datalist>
              </label>
            </>}
          </div>
        </div>;
      })}
    </div>
    {settings.profiles.length === 0 ? <div className="model-route-warning">请先在“模型服务”中新增服务档案。</div> : null}
    <div className="model-route-actions">
      <button className="primary-button" type="button" disabled={formDisabled || !valid} onClick={() => void onSave(routes).catch(() => undefined)}>
        {busyAction === "save-routes" ? <LoaderCircle className="spin" size={14} /> : <Save size={14} />} 保存模型分工
      </button>
    </div>
  </section>;
}
