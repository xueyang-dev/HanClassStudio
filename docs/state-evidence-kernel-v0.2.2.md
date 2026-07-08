# 智能体辅助语言教学课件生成：State-Evidence 核心架构白皮书

**版本：v0.2.2**  
**定位：HanClassStudio State-Evidence Kernel 架构文档**  
**适用范围：语言教学课件生成、HTML 互动课件、Traditional PPTX 课件、教师备注与审校工作流**

---

## 摘要

在使用 Claude Code、Codex、Hermes、DeepSeek 等代码与开发智能体构建自动化语言教学课件生成系统时，真正的工程瓶颈不只是"如何生成漂亮的幻灯片"，而是：

> 如何确保生成结果在教学法上是健全的、可审计的、可迁移的，并且能够被不同呈现端稳定渲染。

传统 AIGC 幻灯片工具大多采用 **Slide-first** 思路：先从资料中抽取内容，再直接生成页面。这种方法容易造成内容堆砌、教学目标与活动脱节、视觉呈现与学习过程脱节、语言任务不适合学习者水平等问题。

HanClassStudio 的下一阶段应采用 **State-first** 思路：先描述学习者的认知状态变化，再定义目标、证据、活动和呈现方式。课件不再被视作页面集合，而是被视作一套引导学习者发生认知状态转移的媒介。

本白皮书提出 **State-Evidence Kernel（状态-证据内核）** 架构。其核心原则是：

```text
Source
→ Learning State Plan
→ Learning Goal
→ Evidence Spec
→ Learning Activity
→ Presentation Plan
→ Render
```

其中，`State / Goal / Evidence / Activity` 构成教学内核，`HTML / PPTX / Web Game / Teacher Observation` 只是下游呈现形式。Renderer 是后端编译器，不应承担教学判断职责。

---

## 1. 核心哲学：从 Slide-first 到 State-first

### 1.1 Slide-first 的问题

Slide-first 工作流通常是：

```text
Source Material → Summary → Slide Outline → Slide Content → Render
```

这种流程在办公汇报中可以接受，但在语言教学中存在明显缺陷：

1. 页面顺序不一定符合学习者认知发展。
2. 教学目标容易直接跳到活动，缺少可验证证据。
3. 活动可能技术上能运行，但教学上不可用。
4. 课件容易暴露教师解释、组件名、debug 信息或不适合学习者水平的目标语指令。
5. 同一内容难以稳定迁移到 HTML、PPTX、教师观察、小游戏等不同端。

### 1.2 State-first 的基本思想

State-first 架构将课件本质定义为：

> 引导学习者从一个认知状态过渡到另一个认知状态的教学系统。

通用状态类型：

```text
Unseen → Noticed → Recognized → Understood → Controlled Production → Communicative Use → Transfer
```

---

## 2. Learning State Plan：设计时状态 DAG

### 2.1 状态五元组

| 元素 | 作用 |
|---|---|
| State | 学习者当前或目标认知状态 |
| Goal | 希望学习者达成的能力声明 |
| Evidence | 证明状态转移成立的证据契约 |
| Activity | 采集证据的教学活动 |
| Transition | 从一个状态进入另一个状态的条件和策略 |

### 2.2 路由策略

| 路由 | 适用阶段 |
|---|---|
| Gagné Route | Unseen → Understood（前置吸收） |
| Merrill Route | Understood → Communicative Use（中高阶转移） |
| TBLT Route | Communicative Use / Transfer（交际任务） |

---

## 3. State-Evidence Kernel 核心模型

### 3.1 LearningGoal

```json
{
  "goal_id": "goal_polite_greeting_understanding",
  "goal_type": "understanding",
  "target_items": ["您好"],
  "success_claim": "Learner can recognize when '您好' is socially appropriate.",
  "required_state_to_reach": "understood_polite_greeting"
}
```

### 3.2 LearningState

```json
{
  "state_id": "understood_polite_greeting",
  "state_type": "understood",
  "target_items": ["您好"],
  "learner_claim": "Learner understands the contrast between '你好' and '您好'.",
  "prerequisites": ["recognized_polite_greeting"],
  "design_confidence": 0.95
}
```

### 3.3 LearningTransition

```json
{
  "from_state": "recognized_polite_greeting",
  "to_state": "understood_polite_greeting",
  "transition_intent": "verify_pragmatic_understanding",
  "required_evidence_ids": ["ev_polite_greeting_scene_choice"],
  "transition_policy": "all_required"
}
```

### 3.4 EvidenceSpec

```json
{
  "evidence_id": "ev_polite_greeting_scene_choice",
  "state_from": "recognized_polite_greeting",
  "state_to": "understood_polite_greeting",
  "learning_claim": "Learner can identify '您好' in a teacher-student scenario.",
  "target_items": ["您好"],
  "evidence_type": "deterministic_choice",
  "assessment_mode": "deterministic",
  "collector_refs": ["act_teacher_scene_choice"],
  "pass_criteria": { "min_correct": 1, "attempts_allowed": 2 },
  "confidence_policy": { "deterministic": true, "ai_required": false, "teacher_override": true },
  "failure_action": {
    "remediation_type": "rescaffold",
    "recommended_activity": "act_show_scene_contrast",
    "return_to_state": "recognized_polite_greeting"
  }
}
```

### 3.5 LearningActivity

```json
{
  "activity_id": "act_teacher_scene_choice",
  "activity_type": "scene_choice",
  "collects_evidence": ["ev_polite_greeting_scene_choice"],
  "allowed_presentation_modes": ["html_interactive", "pptx_classroom", "teacher_observation"],
  "learner_level_fit": ["zero_beginner", "beginner"],
  "scaffolding_level": "high"
}
```

---

## 4. 四层证据系统

| 层级 | 类型 | 场景 | 要求 |
|---|---|---|---|
| L1 | Deterministic | 选择、配对、听音 | 稳定可测试，适合 zero_beginner |
| L2 | Constrained Production | 句式替换、受限填空 | HSK1/CEFR A1+ |
| L3 | Semantic | 角色扮演、自由表达 | 需 fallback 或 teacher_override |
| L4 | Teacher Observation | 朗读、小组协作 | 写入 speaker notes / teacher dashboard |

---

## 5. Core Artifacts

| 文件 | 路径 | 职责 |
|---|---|---|
| Learning State Plan | `learning/learning_state_plan.json` | 状态 DAG、目标、转移 |
| Evidence Plan | `learning/evidence_plan.json` | 证据契约、判定规则 |
| Activity Plan | `learning/activity_plan.json` | 活动定义、呈现模式 |
| Evidence Alignment Report | `quality/evidence_alignment_report.json` | 对齐检查结果 |

---

## 6. Quality Gate Rules

| 规则 | 触发条件 | 结果 |
|---|---|---|
| Goal Orphan | LearningGoal 无 EvidenceSpec | **blocked** |
| Evidence Orphan | EvidenceSpec 无 Activity 采集 | **blocked** |
| Activity Suitability | 活动与水平不匹配 | warning / blocked |
| Semantic Safety | Level 3 无 fallback | warning / blocked |
| Presentation Independence | EvidenceSpec 引用 slide id | **blocked** |
| Teacher Notes | 教师观察无 notes | warning / blocked |

---

## 7. 与 HanClassStudio 集成

### Pipeline 演进

```text
source_material.json
→ source_lesson_profile.json
→ learner_model.json
→ language_items.json
→ learning_state_plan.json (new)
→ evidence_plan.json (new)
→ activity_plan.json (new)
→ presentation_plan.json
→ pptx_deck_plan.json / html_realization.json
→ render
→ quality reports
```

`lesson_blueprint.json` 保留为下游 presentation artifact，不再承担教学目标定义职责。

### Review Agent 扩展

新增审校维度：
- State validity
- Evidence sufficiency
- Activity suitability
- Presentation independence
- Teacher observation readiness

---

## 8. 工程规约

```yaml
SYSTEM_PARADIGM:
  "State-first: Source → StatePlan → Goal → Evidence → Activity → Presentation → Render"

MODELS:
  LearningState:
    state_id, state_type, target_items, learner_claim, prerequisites, design_confidence
  LearningTransition:
    from_state, to_state, transition_intent, required_evidence_ids, optional_evidence_ids, transition_policy
  EvidenceSpec:
    evidence_id, state_from, state_to, learning_claim, target_items, evidence_type,
    assessment_mode, collector_refs, pass_criteria, confidence_policy, failure_action
  LearningActivity:
    activity_id, activity_type, collects_evidence, allowed_presentation_modes,
    learner_level_fit, scaffolding_level

TEST_CRITERIA:
  - Every LearningGoal has at least one EvidenceSpec
  - Every EvidenceSpec is collected by at least one LearningActivity
  - Zero_beginner lessons don't start with production before recognition
  - Communicative_use goals cannot be satisfied only by deterministic choice
  - Semantic evidence requires fallback or teacher_override
  - EvidenceSpec must not reference slide or presentation ids
  - Teacher observation evidence appears in speaker notes / teacher mode
  - quality/evidence_alignment_report.json generated for every compilation
```

---

*完整版及相关讨论可查阅 HanClassStudio 项目文档及 GitHub 仓库。*
