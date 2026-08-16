# Multi-Agent 小说创作系统 — 开发文档

> 版本：v1.0 | 适用框架：LangGraph + OpenAI/Claude API + ChromaDB | 目标：构建可协作、可迭代、可人机协作的自动化小说创作流水线

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [Agent 详细设计](#3-agent-详细设计)
4. [状态机与编排](#4-状态机与编排)
5. [记忆系统](#5-记忆系统)
6. [工具集](#6-工具集)
7. [核心代码实现](#7-核心代码实现)
8. [Prompt 工程规范](#8-prompt-工程规范)
9. [人机协作机制](#9-人机协作机制)
10. [部署与运行](#10-部署与运行)
11. [扩展指南](#11-扩展指南)

---

## 1. 项目概述

### 1.1 背景与痛点

传统大模型单次生成小说存在以下问题：

| 痛点 | 表现 | 根因 |
|------|------|------|
| 人物前后矛盾 | 第三章说角色 25 岁，第五章变成 30 岁 | 上下文窗口限制，长文本遗忘 |
| 世界观设定漂移 | 前期设定"灵气不可外泄"，后期角色随意释放 | 缺乏结构化规则存储 |
| 节奏失控 | 铺垫过长或高潮仓促 | 无全局结构规划 |
| 文笔不统一 | 不同章节风格差异明显 | 缺乏风格约束层 |
| 逻辑漏洞 | 时间线矛盾、地点描述冲突 | 无一致性审查机制 |

### 1.2 解决方案

采用 **Multi-Agent 协作架构**，将创作流程拆解为 6 个专业 Agent + 1 个主控编排器：

- 每个 Agent 专注单一职责，拥有独立记忆和工具
- 通过状态机编排协作顺序，支持循环迭代
- 引入一致性审查和风格编辑，保障质量
- 支持人机协作，用户可随时介入修改

### 1.3 核心特性

- **专业化分工**：每个 Agent 有明确的输入/输出契约
- **结构化记忆**：World Bible + 角色档案 + 向量检索
- **可迭代优化**：一致性审查发现问题 → 回滚修正
- **风格可控**：支持金庸/古龙/村上春树等风格迁移
- **人机协作**：每章完成后可暂停等待用户反馈

---

## 2. 系统架构

### 2.1 整体架构

```
+-------------------------------------------------------------+
|                        用户界面层                            |
|              (Streamlit / Gradio / CLI)                      |
+-------------------------------------------------------------+
|                        编排调度层                            |
|              LangGraph 状态机 + 主控编排器                    |
+----------+----------+----------+----------+-----------------+
| 世界观    | 角色      | 情节      | 正文      | 风格编辑 +      |
| 架构师    | 设计师    | 规划师    | 写手      | 一致性审查      |
| World    | Character | Plot     | Scene    | Style +        |
| Builder  | Designer  | Planner  | Writer   | Consistency    |
+----------+----------+----------+----------+-----------------+
|                        记忆与存储层                          |
|   ChromaDB(向量)  +  SQLite(结构化)  +  文件系统            |
+-------------------------------------------------------------+
|                        模型服务层                            |
|   GPT-4o / Claude-3.5 / DeepSeek-V3 / 本地模型              |
+-------------------------------------------------------------+
```

### 2.2 数据流

```
用户需求 -> Orchestrator 解析 -> WorldBuilder 构建世界观
                                    |
                        CharacterDesigner 设计角色
                                    |
                        PlotPlanner 生成大纲
                                    |
            +-----------------------+-----------------------+
            |                                               |
    SceneWriter 逐章写作              ConsistencyChecker 审查
            |                                               |
    StyleEditor 润色 <---------------- 发现问题则回滚修正
            |
    输出最终稿
```

### 2.3 技术栈

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| 编排框架 | LangGraph | 状态机驱动，支持循环边和条件分支 |
| LLM | GPT-4o / Claude-3.5-Sonnet | 主力模型，负责创意生成 |
| 向量数据库 | ChromaDB | 存储 World Bible、角色档案，支持语义检索 |
| 结构化存储 | SQLite | 章节元数据、角色状态、伏笔追踪 |
| 前端 | Streamlit | 快速搭建人机协作界面 |
| 监控 | LangSmith | Agent 执行链路追踪与调试 |


---

## 3. Agent 详细设计

### 3.1 主控编排器 (Orchestrator)

**职责**：理解用户意图，拆解创作任务，调度各 Agent 执行，维护全局状态机。

**输入**：
- `user_input`: 用户的创作需求描述
- `current_stage`: 当前所处阶段
- `feedback`: 用户反馈（可选）

**输出**：
- `next_stage`: 下一阶段标识
- `task_assignment`: 分配给具体 Agent 的任务参数

**状态流转**：

```
init -> world_building -> character_design -> plot_planning 
  -> writing -> editing -> consistency_check -> done
                    ^___________________________|
                    (发现问题时回滚到 writing)
```

**核心逻辑**：

```python
def orchestrator(state: NovelState):
    stage = state.get("stage", "init")

    # 检查一致性审查反馈
    if state.get("consistency_issues"):
        return {**state, "stage": "writing", "revision_mode": True}

    transitions = {
        "init": "world_building",
        "world_building": "character_design",
        "character_design": "plot_planning", 
        "plot_planning": "writing",
        "writing": "editing" if chapter_complete else "writing",
        "editing": "consistency_check",
        "consistency_check": "done" if no_issues else "writing"
    }

    return {**state, "stage": transitions.get(stage, "done")}
```

---

### 3.2 世界观架构师 (WorldBuilder)

**职责**：构建故事舞台，生成 World Bible 供其他 Agent 引用。

**输入**：
- `genre`: 题材（仙侠/科幻/武侠/都市/奇幻）
- `user_input`: 用户提供的创意线索
- `style_preference`: 风格偏好

**输出**：
- `world_bible`: 结构化世界观文档
- `world_facts`: 可检索的事实条目列表

**World Bible 结构**：

```yaml
world_bible:
  geography:
    - region: "东荒"
      description: "灵气稀薄之地，多为散修聚集"
      climate: "干燥，昼夜温差大"
      key_locations: ["古庙", "黑风岭", "落霞镇"]

  history:
    - year: "天元历 1024 年"
      event: "玄天宗建立"
      significance: "奠定了正道领袖地位"
    - year: "天元历 1456 年"
      event: "魔道入侵"
      significance: "导致东荒灵气枯竭"

  rules:
    magic_system:
      name: "灵气修炼体系"
      levels: ["炼气", "筑基", "金丹", "元婴", "化神"]
      constraints: 
        - "灵气不可外泄超过三息，否则经脉受损"
        - "渡劫时必须独处，否则雷劫威力翻倍"

  society:
    power_structure: "宗门制，以实力为尊"
    economy: "灵石为通用货币"
    customs: 
      - "拜师需行三跪九叩之礼"
      - "修士陨落后遗物归宗门所有"

  culture:
    language_style: "半文半白，多用典故"
    aesthetics: "崇尚自然，建筑多为木质结构"
```

**Prompt 模板**：

```markdown
你是一位资深的世界观架构师，擅长构建自洽、有深度的虚构世界。

## 任务
基于以下信息，生成详细的 World Bible：

题材：{genre}
用户创意：{user_input}
风格基调：{style_preference}

## 输出要求
1. **地理与势力**：绘制主要地理区域，标注关键地点和势力分布
2. **历史年表**：列出至少 5 个影响世界格局的关键历史事件
3. **规则体系**：
   - 如果是修仙/奇幻：详细描述力量体系（等级、限制、代价）
   - 如果是科幻：描述科技水平、物理规则、社会制度
   - 如果是武侠：描述武功体系、门派规则、江湖规矩
4. **社会结构**：权力分配、经济系统、文化习俗
5. **日常细节**：至少 3 个能体现世界特色的日常生活场景

## 约束
- 所有规则必须有"限制"和"代价"，避免万能设定
- 历史事件之间要有因果关系，不能孤立存在
- 社会结构要体现阶层矛盾和冲突点
- 输出为结构化 YAML 格式
```

---

### 3.3 角色设计师 (CharacterDesigner)

**职责**：为每个角色生成完整档案，确保行为逻辑自洽。

**输入**：
- `world_bible`: 世界观文档
- `user_input`: 用户对角色的特殊要求
- `genre`: 题材

**输出**：
- `characters`: 角色档案列表

**角色档案结构**：

```yaml
character:
  basic:
    name: "林渊"
    age: 22
    appearance: 
      - "眉心有一道旧伤疤"
      - "总是穿着洗得发白的青衫"
      - "右手无名指缺了一截"
    social_status: "散修，靠猎杀妖兽为生"

  psychology:
    mbti: "INTJ"
    big_five:
      openness: 85
      conscientiousness: 90
      extraversion: 30
      agreeableness: 40
      neuroticism: 60
    core_motivation: "寻找父亲失踪的真相"
    deep_fear: "发现自己与父亲的失踪有关"
    decision_pattern: "先观察再行动，习惯制定多个备用方案"

  arc:
    start: "冷漠独行的复仇者"
    midpoint: "发现真相后的信念崩塌"
    end: "接纳过去，成为守护者"
    key_moments:
      - chapter: 3
        event: "得知父亲曾是魔道中人"
        emotional_change: "愤怒 -> 困惑"
      - chapter: 12
        event: "为救同伴放弃复仇"
        emotional_change: "执念 -> 释然"

  relationships:
    - target: "苏婉儿"
      type: "潜在爱情"
      initial: -2
      evolution: "从互相猜忌到生死相托"
      tension: "她父亲是林渊的杀父仇人"
    - target: "玄天宗长老"
      type: "敌对"
      initial: -8
      evolution: "发现对方才是幕后黑手"

  voice:
    catchphrases: 
      - "事不过三。"
      - "我不信命。"
    dialogue_style: "简洁克制，极少用感叹号，疑问句多于陈述句"
    emotional_speech: "情绪激动时会停顿，用反问代替直接表达"
    internal_monologue: "习惯用第二人称自我对话，如'你在怕什么'"

  behavior_rules:
    - "绝不会在公共场合暴露真实情绪"
    - "面对强者时习惯站在对方视线死角"
    - "紧张时会无意识摩挲眉心伤疤"
    - "从不说'谢谢'，用行动代替"
```

**Prompt 模板**：

```markdown
你是一位专业的角色设计师，精通心理学和戏剧理论。

## 输入
世界观：{world_bible}
用户要求：{user_input}

## 任务
设计主要角色，每个角色必须包含：

### 1. 基础层
- 姓名、年龄、3 个标志性外貌特征
- 社会身份和日常状态

### 2. 心理层（基于心理学模型）
- MBTI 类型及具体表现
- 大五人格量表（0-100 分）
- 核心动机（表面欲望 vs 深层需求）
- 最大恐惧
- 决策模式（面对危机的第一反应）

### 3. 关系层
- 与每个其他角色的关系向量（情感值 -10~+10）
- 关系演变轨迹
- 关系中的核心矛盾点

### 4. 语言层
- 2-3 句标志性口头禅
- 对话风格描述
- 情绪高涨时的语言变化
- 内心独白特点

### 5. 行为层
- 3-5 个习惯性小动作
- 压力下的行为变化
- 绝不触碰的底线

### 6. 弧光层
- 起点状态
- 中点转折事件
- 终点状态
- 每 3 章标注一次情感状态变化

## 约束
- 避免"完美主角"，每个角色必须有明显缺陷
- 反派动机必须自洽，不能为恶而恶
- 角色间关系网要有张力，避免全员友好
- 语言风格要符合世界观设定
- 输出为结构化 YAML 格式
```

---

### 3.4 情节规划师 (PlotPlanner)

**职责**：设计三幕结构、章节大纲、伏笔网络、节奏控制。

**输入**：
- `world_bible`: 世界观
- `characters`: 角色档案
- `target_length`: 目标篇幅
- `genre_conventions`: 题材套路要求

**输出**：
- `outline`: 章节大纲列表
- `foreshadowing_list`: 伏笔清单
- `pacing_curve`: 节奏曲线数据

**章节大纲结构**：

```yaml
chapter:
  index: 1
  title: "雨夜古庙"
  word_count: 3500

  structure:
    hook: "主角在雨夜发现神秘秘籍"
    setup: "描述古庙环境，建立氛围"
    inciting_incident: "黑衣人出现，索要秘籍"
    rising_action: "双方对峙，主角发现对方身份"
    climax: "闪电照亮令牌，揭示玄天宗标记"
    falling_action: "黑衣人退去，留下警告"
    resolution: "主角决定追查真相"

  characters_present: ["林渊", "神秘黑衣人"]
  location: "东荒古庙"
  time: "天元历 1478 年，雨夜"

  emotional_arc: 
    start: "孤独疲惫"
    peak: "紧张警觉"
    end: "决心坚定"

  tension_level: 6  # 1-10

  foreshadowing:
    planted:
      - element: "黑衣人腰间的青铜令牌"
        reveal_chapter: 5
        reveal_method: "林渊在玄天宗外门弟子身上看到同款令牌"
    revealed:
      - element: "古庙供桌上的灰尘分布"
        planted_chapter: 0
        significance: "暗示近期有人来过"

  key_scenes:
    - type: "dialogue"
      content: "黑衣人与主角的对峙"
      purpose: "建立威胁，透露部分信息"
    - type: "action"
      content: "闪电照亮令牌"
      purpose: "视觉冲击，悬念升级"
    - type: "internal"
      content: "主角回忆父亲失踪前的异常"
      purpose: "情感铺垫"
```

**Prompt 模板**：

```markdown
你是一位资深的情节规划师，精通三幕结构和悬念设计。

## 输入
世界观：{world_bible}
角色档案：{characters}
目标篇幅：{target_length}
题材套路：{genre_conventions}

## 任务
生成完整的章节大纲，要求：

### 1. 整体结构
- 第一幕（Setup）：占 25%，建立世界、人物、日常
- 第二幕（Confrontation）：占 50%，冲突升级，中点转折
- 第三幕（Resolution）：占 25%，高潮对决，收尾

### 2. 每章必须包含
- 标题、预估字数
- 场景地点、出场角色、时间点
- 情节点（钩子->铺垫->触发事件->上升动作->高潮->下降动作->结局）
- 情感弧线（起始->峰值->结束）
- 紧张度评分（1-10）

### 3. 伏笔管理
- 列出所有埋设的伏笔：内容、埋设章节、揭示章节、揭示方式
- 确保伏笔回收率 100%，无遗漏
- 重要伏笔要有"误导层"和"真相层"

### 4. 节奏控制
- 紧张章节后必须安排"呼吸章节"
- 每 3 章设置一个小高潮
- 中点必须有"虚假胜利"或"虚假失败"
- 高潮前 3 章开始加速，每章紧张度递增

### 5. 角色弧光映射
- 标注每章中每个主要角色的情感状态变化
- 确保角色成长与情节推进同步

## 约束
- 避免"机械降神"，所有转折必须有前文铺垫
- 对话场景要有"潜台词"，不能直白表达
- 动作场景要服务于角色塑造，不能纯炫技
- 输出为结构化 YAML 格式
```


---

### 3.5 正文写手 (SceneWriter)

**职责**：根据大纲撰写具体场景，控制视角、对话、描写比例。

**输入**：
- `chapter_plan`: 当前章节大纲
- `world_context`: 检索到的相关世界观
- `character_states`: 角色当前状态
- `style_profile`: 风格参数
- `previous_chapters`: 已写章节（最近 2 章）

**输出**：
- `chapter_text`: 完整章节正文
- `word_count`: 实际字数

**风格参数配置**：

```python
STYLE_PROFILES = {
    "jin_yong": {
        "name": "金庸",
        "traits": "白描见长，招式详尽，历史底蕴深厚，侠义精神",
        "sentence_pattern": "长短句交错，多用四字格",
        "dialogue_ratio": 0.4,
        "description_ratio": 0.35,
        "action_ratio": 0.25,
    },
    "gu_long": {
        "name": "古龙", 
        "traits": "短句有力，意境留白，人物洒脱，悬疑迭起",
        "sentence_pattern": "极简短句，分行排列",
        "dialogue_ratio": 0.5,
        "description_ratio": 0.2,
        "action_ratio": 0.3,
    },
    "murakami": {
        "name": "村上春树",
        "traits": "日常超现实，细腻心理，隐喻丰富，孤独感",
        "sentence_pattern": "平缓叙述，突然转折",
        "dialogue_ratio": 0.35,
        "description_ratio": 0.4,
        "action_ratio": 0.25,
    },
    "yu_hua": {
        "name": "余华",
        "traits": "冷峻克制，命运荒诞，细节真实，黑色幽默",
        "sentence_pattern": "平实叙述，克制情感",
        "dialogue_ratio": 0.3,
        "description_ratio": 0.3,
        "action_ratio": 0.4,
    }
}
```

**Prompt 模板**：

```markdown
你是一位专业的小说写手，正在撰写第 {chapter_index} 章。

## 风格参数
风格：{style_name}
特点：{style_traits}
句式偏好：{sentence_pattern}
对话占比：{dialogue_ratio}
描写占比：{description_ratio}
动作占比：{action_ratio}

## 世界观上下文（检索结果）
{world_context}

## 角色当前状态
{character_states}

## 本章大纲
{chapter_plan}

## 前情提要（最近 2 章）
{previous_chapters}

## 写作要求
1. **严格遵循大纲**：每个情节点必须覆盖，顺序不可打乱
2. **角色一致性**：
   - 对话必须符合角色语言风格
   - 行为必须符合角色性格模型
   - 情感变化必须符合角色弧光
3. **视角控制**：以主角视角为主，必要时可切换但需有明确过渡
4. **节奏控制**：
   - 紧张场景：短句为主，段落简短
   - 抒情场景：长句铺陈，感官细节
   - 对话场景：潜台词优先，避免直白
5. **Show, Don't Tell**：用动作和细节表现情绪，而非直接陈述
6. **结尾要求**：必须留下悬念或情感钩子

## 输出
直接输出章节正文，不要添加额外说明。
预估字数：{target_word_count} 字
```

---

### 3.6 风格编辑 (StyleEditor)

**职责**：润色文笔、调整节奏、优化对话，统一全文风格。

**输入**：
- `full_text`: 完整小说文本
- `style_profile`: 目标风格参数
- `issues`: 已知问题列表（可选）

**输出**：
- `edited_text`: 润色后的完整文本
- `change_log`: 修改记录

**审查清单**：

```markdown
## 风格编辑审查清单

### 1. 文笔统一性
- [ ] 全文用词风格是否一致？
- [ ] 是否存在现代词汇混入古风场景？
- [ ] 句式长度分布是否合理？

### 2. 对话优化
- [ ] 对话是否符合角色身份？
- [ ] 是否存在"说明性对话"？
- [ ] 对话是否有潜台词？
- [ ] 对话标签是否过多？

### 3. 节奏调整
- [ ] 紧张场景段落是否过短？
- [ ] 抒情场景是否有足够的感官细节？
- [ ] 是否存在信息密度过高的段落？

### 4. 冗余检测
- [ ] 是否存在重复描写？
- [ ] 是否存在过度解释？
- [ ] 过渡段落是否必要？

### 5. 画面感增强
- [ ] 是否有"Tell"需要改为"Show"？
- [ ] 五感描写是否均衡？
- [ ] 环境描写是否服务于情绪？

### 6. 修辞优化
- [ ] 比喻是否新颖？
- [ ] 排比是否过度？
- [ ] 反讽是否恰当？
```

**Prompt 模板**：

```markdown
你是一位资深文学编辑，擅长文笔润色和风格统一。

## 输入
目标风格：{style_name}
风格特点：{style_traits}

待润色文本：
{full_text}

## 任务
对全文进行润色，重点：
1. **风格统一**：确保全文符合目标风格，消除风格漂移
2. **对话优化**：删减说明性对话，增强潜台词，减少对话标签
3. **节奏调整**：紧张场景缩短段落，抒情场景增加感官细节
4. **冗余删减**：删除重复描写和过度解释
5. **画面感增强**：将"Tell"改为"Show"，补充五感描写
6. **修辞优化**：替换陈词滥调，调整排比节奏

## 输出格式
先输出修改记录，再输出润色后的完整文本。
```

---

### 3.7 一致性审查员 (ConsistencyChecker)

**职责**：扫描全文检测设定冲突，生成问题报告。

**输入**：
- `full_text`: 完整小说文本
- `world_bible`: 世界观文档
- `characters`: 角色档案
- `outline`: 章节大纲

**输出**：
- `issues`: 问题列表
- `severity`: 严重程度（critical/warning/info）
- `suggestions`: 修正建议

**审查维度**：

| 维度 | 检查内容 | 示例 |
|------|----------|------|
| 人物一致性 | 年龄、外貌、能力、性格前后是否一致 | 第三章 25 岁，第五章 30 岁 |
| 时间线 | 事件顺序、时间间隔是否合理 | 昨天刚受伤，今天就痊愈 |
| 地点一致性 | 地理位置、环境描述是否冲突 | 前文在山顶，后文在谷底但无过渡 |
| 规则一致性 | 世界观规则是否被违背 | 设定"灵气不可外泄"，角色随意释放 |
| 关系一致性 | 人物关系变化是否有铺垫 | 仇人突然变成盟友，无转折过程 |
| 物品一致性 | 道具状态、位置是否一致 | 丢失的剑突然出现在手中 |

**Prompt 模板**：

```markdown
你是一位严谨的一致性审查员，负责检测小说中的设定冲突。

## 输入
世界观规则：{world_bible}
角色档案：{characters}
章节大纲：{outline}
小说全文：{full_text}

## 任务
逐章审查，检测以下类型的冲突：

### 1. 人物一致性
- 年龄、外貌特征是否有变化？
- 能力等级是否有跳跃？
- 性格行为是否偏离设定？
- 标志性小动作是否遗漏？

### 2. 时间线
- 事件顺序是否逻辑自洽？
- 时间间隔是否合理？
- 是否存在"时间旅行"漏洞？

### 3. 地点一致性
- 地理位置描述是否冲突？
- 场景转换是否有合理过渡？
- 环境细节（天气、光线）是否一致？

### 4. 规则一致性
- 世界观规则是否被违背？
- 特殊能力的使用是否符合限制？
- 社会规则是否被选择性执行？

### 5. 关系一致性
- 人物关系变化是否有足够铺垫？
- 情感转变是否符合角色弧光？
- 是否存在关系"突变"？

### 6. 物品一致性
- 道具状态（完好/损坏/丢失）是否一致？
- 物品位置是否有合理解释？
- 特殊物品的能力是否前后一致？

## 输出格式
对每个发现的问题：
1. 问题描述
2. 涉及章节
3. 严重程度（critical/warning/info）
4. 修正建议

如果没有发现问题，输出"一致性检查通过"。
```


---

## 4. 状态机与编排

### 4.1 LangGraph 状态定义

```python
from typing import TypedDict, Annotated, List, Optional
from langgraph.graph import StateGraph, END
import operator

class NovelState(TypedDict):
    user_input: str
    genre: str
    style: str
    target_length: str
    world_bible: Optional[str]
    characters: Optional[List[dict]]
    outline: Optional[List[dict]]
    chapters: Annotated[List[str], operator.add]
    current_chapter: int
    total_chapters: int
    stage: str
    consistency_issues: Optional[List[dict]]
    revision_mode: bool
    revision_note: Optional[str]
    human_feedback: Optional[dict]
    pause_for_human: bool
    created_at: str
    updated_at: str
```

### 4.2 状态流转

```
START -> Orchestrator -> WorldBuilder -> CharacterDesigner -> PlotPlanner
  -> SceneWriter -> HumanReview(可选) -> StyleEditor -> ConsistencyChecker
  -> (发现问题则回滚到 SceneWriter) -> (全部通过则 END)
```

### 4.3 条件边实现

```python
def route_from_orchestrator(state):
    stage = state["stage"]
    routing_map = {
        "init": "orchestrator",
        "world_building": "world_builder",
        "character_design": "character_designer",
        "plot_planning": "plot_planner",
        "writing": "scene_writer",
        "human_review": "human_review",
        "editing": "style_editor",
        "consistency_check": "consistency_checker",
        "done": END
    }
    return routing_map.get(stage, END)

def route_from_consistency(state):
    if state.get("consistency_issues"):
        if any(i["severity"] == "critical" for i in state["consistency_issues"]):
            return "scene_writer"
        return "style_editor"
    return "orchestrator"

def route_from_human(state):
    feedback = state.get("human_feedback", {})
    action = feedback.get("action", "continue")
    if action == "rewrite":
        state["current_chapter"] -= 1
        return "scene_writer"
    elif action == "revise":
        state["revision_mode"] = True
        state["revision_note"] = feedback.get("note", "")
        return "scene_writer"
    elif action == "edit_style":
        return "style_editor"
    return "orchestrator"

# 构建图
builder = StateGraph(NovelState)
builder.add_node("orchestrator", orchestrator_node)
builder.add_node("world_builder", world_builder_node)
builder.add_node("character_designer", character_designer_node)
builder.add_node("plot_planner", plot_planner_node)
builder.add_node("scene_writer", scene_writer_node)
builder.add_node("human_review", human_review_node)
builder.add_node("style_editor", style_editor_node)
builder.add_node("consistency_checker", consistency_checker_node)

builder.set_entry_point("orchestrator")

builder.add_conditional_edges(
    "orchestrator", route_from_orchestrator,
    {
        "world_builder": "world_builder",
        "character_designer": "character_designer",
        "plot_planner": "plot_planner",
        "scene_writer": "scene_writer",
        "human_review": "human_review",
        "style_editor": "style_editor",
        "consistency_checker": "consistency_checker",
        END: END
    }
)

for node in ["world_builder", "character_designer", "plot_planner"]:
    builder.add_edge(node, "orchestrator")

builder.add_edge("scene_writer", "human_review")

builder.add_conditional_edges(
    "human_review", route_from_human,
    {
        "scene_writer": "scene_writer",
        "style_editor": "style_editor",
        "orchestrator": "orchestrator"
    }
)

builder.add_edge("style_editor", "consistency_checker")

builder.add_conditional_edges(
    "consistency_checker", route_from_consistency,
    {
        "scene_writer": "scene_writer",
        "style_editor": "style_editor",
        "orchestrator": "orchestrator"
    }
)

graph = builder.compile(checkpointer=MemorySaver())
```

---

## 5. 记忆系统

### 5.1 三层记忆架构

| 层级 | 内容 | 存储方式 | 作用 |
|------|------|----------|------|
| 短期记忆 | 当前对话、最近 3 章 | 内存变量 | 即时上下文 |
| 中期记忆 | World Bible、角色摘要、伏笔 | 向量数据库(ChromaDB) | 语义检索 |
| 长期记忆 | 完整角色档案、大纲、全文 | SQLite | 结构化持久化 |

### 5.2 向量记忆实现

```python
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain.schema import Document

class NovelMemory:
    def __init__(self, persist_dir="./memory"):
        self.embeddings = OpenAIEmbeddings()
        self.vector_store = Chroma(
            collection_name="novel_memory",
            embedding_function=self.embeddings,
            persist_directory=persist_dir
        )

    def add_world_fact(self, fact, category, chapter_reveal=999):
        doc = Document(
            page_content=fact,
            metadata={
                "type": "world_fact",
                "category": category,
                "chapter_reveal": chapter_reveal
            }
        )
        self.vector_store.add_documents([doc])

    def add_character_summary(self, name, summary):
        doc = Document(
            page_content=f"角色：{name}\n{summary}",
            metadata={"type": "character", "character_name": name}
        )
        self.vector_store.add_documents([doc])

    def add_chapter_summary(self, chapter_idx, summary):
        doc = Document(
            page_content=f"第{chapter_idx}章摘要：{summary}",
            metadata={"type": "chapter_summary", "chapter_idx": chapter_idx}
        )
        self.vector_store.add_documents([doc])

    def query_for_writing(self, query, current_chapter, k=5):
        results = self.vector_store.similarity_search(
            query, k=k*2,
            filter={"chapter_reveal": {"$lte": current_chapter}}
        )
        return results[:k]

    def get_character_context(self, name, current_chapter):
        results = self.vector_store.similarity_search(
            f"角色{name}的状态和经历", k=3,
            filter={
                "$or": [
                    {"type": "character", "character_name": name},
                    {"type": "chapter_summary"}
                ]
            }
        )
        return results
```

### 5.3 结构化存储 (SQLite)

```python
import sqlite3
import json

class NovelStore:
    def __init__(self, db_path="./novels.db"):
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        sql = """
            CREATE TABLE IF NOT EXISTS novels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT, genre TEXT, style TEXT,
                status TEXT DEFAULT 'writing',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                novel_id INTEGER, name TEXT, profile_json TEXT,
                FOREIGN KEY (novel_id) REFERENCES novels(id)
            );
            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                novel_id INTEGER, chapter_idx INTEGER,
                title TEXT, outline_json TEXT,
                content TEXT, word_count INTEGER,
                status TEXT DEFAULT 'draft',
                FOREIGN KEY (novel_id) REFERENCES novels(id)
            );
            CREATE TABLE IF NOT EXISTS foreshadowing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                novel_id INTEGER, element TEXT,
                planted_chapter INTEGER, reveal_chapter INTEGER,
                status TEXT DEFAULT 'planted',
                FOREIGN KEY (novel_id) REFERENCES novels(id)
            );
            CREATE TABLE IF NOT EXISTS consistency_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                novel_id INTEGER, chapter_idx INTEGER,
                issue_type TEXT, description TEXT,
                severity TEXT, status TEXT DEFAULT 'open',
                FOREIGN KEY (novel_id) REFERENCES novels(id)
            );
        """
        self.conn.executescript(sql)
        self.conn.commit()

    def create_novel(self, title, genre, style):
        cursor = self.conn.execute(
            "INSERT INTO novels (title, genre, style) VALUES (?, ?, ?)",
            (title, genre, style)
        )
        self.conn.commit()
        return cursor.lastrowid

    def save_character(self, novel_id, name, profile):
        self.conn.execute(
            "INSERT INTO characters (novel_id, name, profile_json) VALUES (?, ?, ?)",
            (novel_id, name, json.dumps(profile, ensure_ascii=False))
        )
        self.conn.commit()

    def save_chapter(self, novel_id, chapter_idx, title, outline, content):
        word_count = len(content)
        self.conn.execute(
            "INSERT INTO chapters (novel_id, chapter_idx, title, outline_json, content, word_count) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT DO UPDATE SET "
            "title=excluded.title, outline_json=excluded.outline_json, "
            "content=excluded.content, word_count=excluded.word_count",
            (novel_id, chapter_idx, title, json.dumps(outline), content, word_count)
        )
        self.conn.commit()

    def get_chapter(self, novel_id, chapter_idx):
        cursor = self.conn.execute(
            "SELECT * FROM chapters WHERE novel_id=? AND chapter_idx=?",
            (novel_id, chapter_idx)
        )
        row = cursor.fetchone()
        if row:
            return {
                "id": row[0], "novel_id": row[1], "chapter_idx": row[2],
                "title": row[3], "outline": row[4], "content": row[5],
                "word_count": row[6], "status": row[7]
            }
        return None

    def get_all_chapters(self, novel_id):
        cursor = self.conn.execute(
            "SELECT * FROM chapters WHERE novel_id=? ORDER BY chapter_idx",
            (novel_id,)
        )
        return [{
            "id": r[0], "chapter_idx": r[2], "title": r[3],
            "content": r[5], "word_count": r[6]
        } for r in cursor.fetchall()]

    def save_foreshadowing(self, novel_id, element, planted, reveal):
        self.conn.execute(
            "INSERT INTO foreshadowing (novel_id, element, planted_chapter, reveal_chapter) VALUES (?, ?, ?, ?)",
            (novel_id, element, planted, reveal)
        )
        self.conn.commit()

    def get_unresolved_foreshadowing(self, novel_id, current_chapter):
        cursor = self.conn.execute(
            "SELECT * FROM foreshadowing "
            "WHERE novel_id=? AND status='planted' AND reveal_chapter <= ?",
            (novel_id, current_chapter)
        )
        return cursor.fetchall()
```

---

## 6. 工具集

### 6.1 工具定义

```python
from langchain.tools import tool
from typing import Annotated

@tool
def search_inspiration(query: Annotated[str, "搜索关键词"]) -> str:
    """搜索创作灵感，获取相关题材的经典桥段、设定参考"""
    return f"关于'{query}'的创作灵感：..."

@tool
def calculate_timeline(events: Annotated[str, "事件列表，JSON格式"]) -> str:
    """计算时间线，检测时间冲突"""
    events_list = json.loads(events)
    return "时间线验证结果：无冲突"

@tool
def check_character_behavior(
    character_profile: Annotated[str, "角色档案"],
    action: Annotated[str, "待验证的行为"]
) -> str:
    """验证角色行为是否符合其性格设定"""
    prompt = f"角色档案：{character_profile}\n待验证行为：{action}\n该行为是否符合角色设定？"
    return llm.invoke(prompt).content

@tool
def analyze_pacing(text: Annotated[str, "待分析的文本"]) -> str:
    """分析文本节奏，给出调整建议"""
    sentences = text.split("。")
    avg_length = sum(len(s) for s in sentences) / len(sentences)
    return f"平均句长：{avg_length:.1f}字"

@tool
def export_to_format(
    chapters: Annotated[str, "章节内容，JSON格式"],
    format_type: Annotated[str, "导出格式：txt/md/epub"]
) -> str:
    """将小说导出为指定格式"""
    chapters_list = json.loads(chapters)
    if format_type == "txt":
        content = "\n\n".join(chapters_list)
        with open("output.txt", "w", encoding="utf-8") as f:
            f.write(content)
        return "已导出为 output.txt"
    elif format_type == "md":
        content = "\n\n---\n\n".join(chapters_list)
        with open("output.md", "w", encoding="utf-8") as f:
            f.write(content)
        return "已导出为 output.md"
    return "不支持的格式"
```

### 6.2 工具注册

```python
from langchain.agents import initialize_agent, AgentType

tools = [
    search_inspiration,
    calculate_timeline,
    check_character_behavior,
    analyze_pacing,
    export_to_format
]

world_builder_agent = initialize_agent(
    tools=tools, llm=llm,
    agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)
```


---

## 7. 核心代码实现

### 7.1 项目结构

```
novel-agent/
├── main.py                    # 命令行入口
├── config.py                  # 配置管理
├── requirements.txt           # 依赖清单
├── .env                       # 环境变量
│
├── agents/                    # Agent 实现
│   ├── __init__.py
│   ├── orchestrator.py        # 主控编排器
│   ├── world_builder.py       # 世界观架构师
│   ├── character_designer.py  # 角色设计师
│   ├── plot_planner.py        # 情节规划师
│   ├── scene_writer.py        # 正文写手
│   ├── style_editor.py        # 风格编辑
│   └── consistency_checker.py # 一致性审查员
│
├── graph/                     # LangGraph 编排
│   ├── __init__.py
│   ├── builder.py             # 图构建
│   ├── nodes.py               # 节点实现
│   └── edges.py               # 条件边
│
├── memory/                    # 记忆系统
│   ├── __init__.py
│   ├── vector_store.py        # ChromaDB 封装
│   └── sql_store.py           # SQLite 封装
│
├── tools/                     # 工具集
│   ├── __init__.py
│   ├── search_tools.py
│   ├── analysis_tools.py
│   └── export_tools.py
│
├── prompts/                   # Prompt 模板
│   ├── world_builder.txt
│   ├── character_designer.txt
│   ├── plot_planner.txt
│   ├── scene_writer.txt
│   ├── style_editor.txt
│   └── consistency_checker.txt
│
├── ui/                        # 用户界面
│   └── streamlit_app.py       # Streamlit 界面
│
├── api/                       # API 服务
│   └── server.py              # FastAPI 服务
│
└── output/                    # 输出目录
    └── .gitkeep
```

### 7.2 主入口 (main.py)

```python
import asyncio
from dotenv import load_dotenv
from graph.builder import build_graph
from memory.vector_store import NovelMemory
from memory.sql_store import NovelStore

load_dotenv()

async def main():
    # 初始化存储
    memory = NovelMemory()
    store = NovelStore()

    # 构建图
    graph = build_graph()

    # 用户输入
    user_input = input("请输入您的创作需求：")
    genre = input("题材（仙侠/科幻/武侠/都市/奇幻）：")
    style = input("风格（金庸/古龙/村上春树/余华/自定义）：")

    # 创建小说记录
    novel_id = store.create_novel(
        title="未命名", genre=genre, style=style
    )

    # 初始状态
    initial_state = {
        "user_input": user_input,
        "genre": genre,
        "style": style,
        "target_length": "medium",
        "world_bible": None,
        "characters": None,
        "outline": None,
        "chapters": [],
        "current_chapter": 0,
        "total_chapters": 0,
        "stage": "init",
        "consistency_issues": None,
        "revision_mode": False,
        "revision_note": None,
        "human_feedback": None,
        "pause_for_human": False,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "novel_id": novel_id
    }

    # 运行图
    config = {"configurable": {"thread_id": f"novel_{novel_id}"}}

    async for event in graph.astream(initial_state, config):
        for key, value in event.items():
            print(f"\n=== {key} ===")
            if key == "world_builder":
                print("世界观生成完成")
                print(value["world_bible"][:500] + "...")
            elif key == "character_designer":
                print(f"角色设计完成，共 {len(value['characters'])} 个角色")
            elif key == "plot_planner":
                print(f"大纲生成完成，共 {len(value['outline'])} 章")
            elif key == "scene_writer":
                print(f"第 {value['current_chapter']} 章写作完成")
            elif key == "consistency_checker":
                issues = value.get("consistency_issues", [])
                if issues:
                    print(f"发现 {len(issues)} 个一致性问题，正在修正...")
                else:
                    print("一致性检查通过")

    print("\n创作完成！")

if __name__ == "__main__":
    asyncio.run(main())
```

### 7.3 配置管理 (config.py)

```python
import os
from pydantic_settings import BaseSettings

class Config(BaseSettings):
    # LLM 配置
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = "gpt-4o"
    openai_temperature: float = 0.7

    # 备选模型
    claude_api_key: str = os.getenv("CLAUDE_API_KEY", "")
    claude_model: str = "claude-3-5-sonnet-20241022"

    # 向量数据库
    chroma_persist_dir: str = "./memory/chroma"

    # SQLite
    sqlite_db_path: str = "./memory/novels.db"

    # LangSmith
    langsmith_api_key: str = os.getenv("LANGSMITH_API_KEY", "")
    langsmith_project: str = "novel-agent"

    # 创作参数
    default_chapter_word_count: int = 3500
    max_chapters: int = 50

    # 人机协作
    enable_human_review: bool = True

    class Config:
        env_file = ".env"

CONFIG = Config()
```

### 7.4 模型封装 (models/llm.py)

```python
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from config import CONFIG

def get_llm(provider: str = "openai"):
    if provider == "openai":
        return ChatOpenAI(
            model=CONFIG.openai_model,
            temperature=CONFIG.openai_temperature,
            api_key=CONFIG.openai_api_key
        )
    elif provider == "claude":
        return ChatAnthropic(
            model=CONFIG.claude_model,
            temperature=CONFIG.openai_temperature,
            api_key=CONFIG.claude_api_key
        )
    else:
        raise ValueError(f"不支持的模型提供商：{provider}")
```

---

## 8. Prompt 工程规范

### 8.1 Prompt 设计原则

1. **角色明确**：每个 Prompt 开头定义 Agent 的专业身份
2. **输入结构化**：明确标注输入数据的格式和含义
3. **输出格式固定**：要求结构化输出（YAML/JSON/列表）
4. **约束具体化**：避免模糊要求，给出具体标准
5. **示例引导**：复杂任务提供 Few-shot 示例

### 8.2 Prompt 模板加载

```python
from pathlib import Path

class PromptManager:
    def __init__(self, prompts_dir="./prompts"):
        self.prompts_dir = Path(prompts_dir)
        self._cache = {}

    def load(self, name: str) -> str:
        if name in self._cache:
            return self._cache[name]

        path = self.prompts_dir / f"{name}.txt"
        if not path.exists():
            raise FileNotFoundError(f"Prompt 模板不存在：{path}")

        content = path.read_text(encoding="utf-8")
        self._cache[name] = content
        return content

    def render(self, name: str, **kwargs) -> str:
        template = self.load(name)
        return template.format(**kwargs)

prompt_manager = PromptManager()

# 使用示例
world_prompt = prompt_manager.render(
    "world_builder",
    genre="仙侠",
    user_input="主角是一个被宗门抛弃的弟子",
    style_preference="冷峻写实"
)
```

### 8.3 Few-shot 示例（风格迁移）

```markdown
## 风格示例：古龙

### 原文
林渊走进酒馆，看到苏婉儿坐在角落里。她的眼神很冷漠。

### 古龙风格改写

林渊推开门。

风从门外灌进来，吹灭了柜台上的半支蜡烛。

角落里坐着一个人。

一个女人。

她的眼睛里没有光。只有刀锋一样的冷。

林渊没有走过去。他只是站在那里，看着她。

她也看着他。

两个人都没有说话。

有时候，沉默比刀更锋利。

---

## 风格示例：金庸

### 原文
林渊走进酒馆，看到苏婉儿坐在角落里。她的眼神很冷漠。

### 金庸风格改写

那酒馆坐落在洛阳城东，招牌上写着"醉仙楼"三个大字，字迹已然斑驳。
林渊踏入门槛，目光一扫，便见角落里坐着一个青衣女子。
她约莫二十来岁年纪，眉如远山，目若秋水，只是那双眸子中
透着一股说不出的冷漠，仿佛世间万物都与她毫不相干。
林渊心中一动，暗道："这女子好重的煞气。"
他缓步上前，抱拳道："姑娘，此处可有人坐？"
那女子抬起头来，淡淡地看了他一眼，却不答话。
"""
```

---

## 9. 人机协作机制

### 9.1 协作节点设计

```python
from langgraph.types import interrupt

def human_review_node(state: NovelState):
    """人机协作审查节点"""
    if not CONFIG.enable_human_review:
        return {**state, "human_feedback": {"action": "continue"}}

    chapter_idx = state["current_chapter"] - 1
    chapter_text = state["chapters"][chapter_idx]

    # 生成审查摘要
    summary_prompt = f"""
    请用 50 字概括以下章节的核心内容：
    {chapter_text[:1000]}
    """
    summary = llm.invoke(summary_prompt).content

    # 发送中断，等待用户输入
    user_input = interrupt({
        "type": "chapter_review",
        "chapter_idx": chapter_idx,
        "summary": summary,
        "word_count": len(chapter_text),
        "options": [
            {"id": "continue", "label": "通过，继续下一章"},
            {"id": "revise", "label": "提出修改意见"},
            {"id": "rewrite", "label": "重写本章"},
            {"id": "edit_style", "label": "调整风格后重写"}
        ]
    })

    return {**state, "human_feedback": user_input}
```

### 9.2 Streamlit 协作界面

```python
import streamlit as st
from graph.builder import build_graph

st.set_page_config(page_title="小说创作 Agent", layout="wide")

# 初始化
if "graph" not in st.session_state:
    st.session_state.graph = build_graph()
if "state" not in st.session_state:
    st.session_state.state = None
if "creating" not in st.session_state:
    st.session_state.creating = False

st.title("Multi-Agent 小说创作系统")

# 侧边栏：创作设置
with st.sidebar:
    st.header("创作设置")
    genre = st.selectbox("题材", ["仙侠", "科幻", "武侠", "都市", "奇幻", "悬疑"])
    style = st.selectbox("风格", ["金庸", "古龙", "村上春树", "余华", "自定义"])
    target_length = st.selectbox("篇幅", ["短篇(3-5章)", "中篇(10-20章)", "长篇(30+章)"])
    enable_review = st.checkbox("启用人工审查", value=True)

    user_input = st.text_area("创作需求", height=100,
        placeholder="描述您想创作的小说...")

    if st.button("开始创作", type="primary"):
        st.session_state.creating = True
        st.session_state.state = {
            "user_input": user_input,
            "genre": genre,
            "style": style,
            "target_length": target_length,
            "enable_human_review": enable_review,
            "stage": "init",
            "chapters": [],
            "current_chapter": 0
        }

# 主界面：分栏展示
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("创作进度")

    stages = ["世界观", "角色", "大纲", "正文", "润色", "审查"]
    current_stage_idx = {
        "init": 0, "world_building": 0, "character_design": 1,
        "plot_planning": 2, "writing": 3, "editing": 4,
        "consistency_check": 5, "done": 6
    }.get(st.session_state.state.get("stage", "init"), 0) if st.session_state.state else 0

    for i, stage in enumerate(stages):
        if i < current_stage_idx:
            st.success(f"✓ {stage}")
        elif i == current_stage_idx:
            st.info(f"▶ {stage} (进行中)")
        else:
            st.text(f"○ {stage}")

    # 统计信息
    if st.session_state.state and st.session_state.state.get("chapters"):
        total_words = sum(len(c) for c in st.session_state.state["chapters"])
        st.metric("已写字数", f"{total_words:,}")
        st.metric("已完成章节", len(st.session_state.state["chapters"]))

with col2:
    st.subheader("创作内容")

    tab1, tab2, tab3, tab4 = st.tabs(["世界观", "角色", "大纲", "正文"])

    with tab1:
        if st.session_state.state and st.session_state.state.get("world_bible"):
            st.markdown(st.session_state.state["world_bible"])
        else:
            st.info("等待世界观生成...")

    with tab2:
        if st.session_state.state and st.session_state.state.get("characters"):
            for char in st.session_state.state["characters"]:
                with st.expander(char.get("name", "未命名")):
                    st.json(char)
        else:
            st.info("等待角色设计...")

    with tab3:
        if st.session_state.state and st.session_state.state.get("outline"):
            for i, ch in enumerate(st.session_state.state["outline"]):
                st.write(f"**第{i+1}章：{ch.get('title', '')}**")
                st.write(ch.get("summary", ""))
        else:
            st.info("等待大纲生成...")

    with tab4:
        if st.session_state.state and st.session_state.state.get("chapters"):
            for i, chapter in enumerate(st.session_state.state["chapters"]):
                with st.expander(f"第{i+1}章"):
                    st.write(chapter)

                    if enable_review and i == len(st.session_state.state["chapters"]) - 1:
                        col_a, col_b, col_c = st.columns(3)
                        with col_a:
                            if st.button("通过", key=f"pass_{i}"):
                                st.session_state.human_feedback = {"action": "continue"}
                        with col_b:
                            if st.button("修改", key=f"revise_{i}"):
                                note = st.text_input("修改意见", key=f"note_{i}")
                                if st.button("提交", key=f"submit_{i}"):
                                    st.session_state.human_feedback = {
                                        "action": "revise", "note": note
                                    }
                        with col_c:
                            if st.button("重写", key=f"rewrite_{i}"):
                                st.session_state.human_feedback = {"action": "rewrite"}
        else:
            st.info("等待正文生成...")
```


---

## 10. 部署与运行

### 10.1 环境准备

```bash
git clone https://github.com/yourname/novel-agent.git
cd novel-agent
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 10.2 依赖清单 (requirements.txt)

```
langgraph>=0.2.0
langchain>=0.3.0
langchain-openai>=0.2.0
langchain-chroma>=0.1.0
chromadb>=0.5.0
streamlit>=1.38.0
python-dotenv>=1.0.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
```

### 10.3 环境变量 (.env)

```bash
OPENAI_API_KEY=sk-...
LANGSMITH_API_KEY=ls-...
```

### 10.4 运行方式

| 模式 | 命令 | 说明 |
|------|------|------|
| 命令行 | `python main.py` | 终端交互 |
| Web 界面 | `streamlit run ui/streamlit_app.py` | 可视化协作 |
| API 服务 | `python api/server.py` | 提供 REST API |

### 10.5 Docker 部署

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "ui/streamlit_app.py", "--server.port=8501"]
```

```bash
docker build -t novel-agent .
docker run -p 8501:8501 --env-file .env novel-agent
```

---

## 11. 扩展指南

### 11.1 添加新风格

在 `config.py` 的 `STYLE_PROFILES` 中添加新条目，定义句式偏好、描写比例等参数。

### 11.2 添加新 Agent

1. 在 `agents/` 目录下新建节点文件
2. 在 `graph/nodes.py` 中实现逻辑
3. 在 `graph/builder.py` 中注册节点和边
4. 在 `prompts/` 中添加 Prompt 模板

### 11.3 集成本地模型

```python
from langchain_community.llms import Ollama
llm = Ollama(model="qwen2.5:72b", base_url="http://localhost:11434")
```

### 11.4 添加读者模拟 Agent (BetaReader)

在一致性审查后增加一个节点，模拟目标读者反馈爽点、毒点、节奏感受，再回流到 SceneWriter 修正。

### 11.5 连载管理

实现 `SerialManager` 类，支持断点续写、前文回顾自动生成、长期连载的状态持久化。

---

## 附录

### A. 常见问题

**Q: LLM 上下文不够长怎么办？**
A: 采用 RAG 检索，只注入相关世界观片段，而非全文。

**Q: 如何保证角色不"崩"？**
A: SceneWriter Prompt 中强制嵌入角色档案约束，ConsistencyChecker 专项审查人物一致性。

**Q: 创作速度太慢怎么办？**
A: 初稿用 GPT-4o-mini 加速，润色阶段再用 GPT-4o；独立章节可并行生成。

**Q: 用户中途改需求怎么办？**
A: Orchestrator 解析修订指令，触发对应 Agent 重新执行，已完成的章节可选择性保留。

### B. 性能优化

- 使用 `@lru_cache` 缓存世界观检索结果
- 异步并行处理独立任务
- 一致性审查发现问题时，只重写相关段落而非整章

### C. 监控与调试

集成 LangSmith 追踪 Agent 调用链，访问 `smith.langchain.com` 查看详细执行链路、Token 消耗和延迟分析。

---

> 本文档持续更新中。如有问题或建议，欢迎提交 Issue。
