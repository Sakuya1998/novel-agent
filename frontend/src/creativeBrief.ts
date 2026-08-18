import type { CreativeBrief } from "./types";

export const AGE_RATING_LABELS: Record<CreativeBrief["age_rating"], string> = {
  all_ages: "全年龄",
  teen: "青少年及以上",
  mature: "成人向",
};

export const POINT_OF_VIEW_LABELS: Record<CreativeBrief["point_of_view"], string> = {
  first_person: "第一人称",
  third_limited: "第三人称限知",
  third_omniscient: "第三人称全知",
  multiple: "多视角",
};

export const NARRATIVE_TENSE_LABELS: Record<CreativeBrief["narrative_tense"], string> = {
  past: "过去时",
  present: "现在时",
  mixed: "混合时态",
};

export const NARRATIVE_DISTANCE_LABELS: Record<CreativeBrief["narrative_distance"], string> = {
  close: "贴近人物内心",
  medium: "中等距离",
  distant: "疏离客观",
};

export const ENDING_TONE_LABELS: Record<CreativeBrief["ending_tone"], string> = {
  unspecified: "不限定",
  hopeful: "希望感",
  bittersweet: "苦乐参半",
  tragic: "悲剧",
  open: "开放式",
};

export function createDefaultCreativeBrief(): CreativeBrief {
  return {
    target_audience: "大众类型小说读者",
    age_rating: "teen",
    point_of_view: "third_limited",
    narrative_tense: "past",
    narrative_distance: "medium",
    ending_tone: "unspecified",
    themes: [],
    must_include: [],
    avoid_content: [],
    intensity: {
      romance: 2,
      mystery: 2,
      action: 2,
      darkness: 2,
    },
    notes: "",
  };
}
