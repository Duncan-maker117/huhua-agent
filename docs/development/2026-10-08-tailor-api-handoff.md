# Tailor PR4/5 → PR6 接口交接

当前为本地开发接口。PR4 v5（`ada326e`）本地887/887通过（含21项未集成PR5组件测试）；公开全套补评后编辑21/24（87.5%），事实疑点待Claude复核；私有仍2页、5/8目标满足，PR4未验收。PR5独立组件尚未接入graph。以下为当前字段契约，尚未完成前端交付验收。

## 当前稿与 SSE

`POST /api/chat/stream` 保留原 content 流。最终 `type: "meta"` 在 SQL 成功保存后返回；`GET /api/resume/current?session_id=…` 同样返回以下字段。不要把流式内容或加载状态当作已经保存。

| 字段 | 含义 |
|---|---|
| `version_id` | 当前文稿版本身份；可能为 null（尚未调用 writer） |
| `diff` | 按条目折叠的 `{section,item_id,before,after}`；新增/缺失侧为 null；排序变化另有 `field:"order"` |
| `change_summary` | 至多五条修改说明；具体改动以 diff 为准 |
| `match_plan` | requirements 的 `req_id/status/fact_ids/angle`，experience_plan 的分级与原因，section_order/questions |
| `questions` | 至多三条 `{q,why,improves:{item_id,req_id},options,value}`；PR5 将补已问/关闭去重 |
| `resume_meta.bullets[item_id]` | 每条的 `fact_ids/req_ids/flags/needs_metric/metric_question/text_hash`；手工改文失效后不再展示旧模型依据 |
| `session_constraints` | 当前持续生效的 `page_limit/language/template_id` |
| `page_check` | `status:rendered|render_error|stale`、实测 `pages:number|null`、`page_limit`、`within_page_limit:boolean|null`；null 不能表示合规 |
| `can_undo` | 是否有可恢复历史文稿 |

相同信息也放在 `workspace.tailor`。`workspace.experiences.items` 新增 item_id/hidden；隐藏项可放“备用”，不得渲染进投递预览。当前内部 stage 仍兼容 EVALUATING，前端使用 has_data 判断有稿，避免绑定阶段名。

页数证据的 `data_hash/template_id/page_limit` 绑定测量正文和约束。GET 不触发重新渲染；hash、模板或页数要求不符时返回 `status:stale`、`reason:document_or_page_constraints_changed`，清空 `pages/within_page_limit`。保留 `source` 与可选 `error_type` 作为诊断。

若保存时事实校验改变正文，`page_check.content_integrity:changed_by_fact_sanitizer` 和 `pre_sanitization_data_hash` 标明变化；实际页数仍显示，但 `within_page_limit:null`，不能宣称靠删掉失效正文完成了压缩。此时 `change_summary` 可能仍来自写作阶段，执行结果须以保存后的 `data/diff` 为准。`resume_meta.writer_diagnostic` 的 `status:model_completed|model_fallback` 区分实际模型写作与原文回退，不向用户显示底层异常详情。

v3 的诊断包含 `schema_retry_count:0|1`。`fallback_action:preserved_existing_draft` 表示改写失败，仍有效的上一版正文已保留；`deterministic_updates_applied` 区分本轮是否执行了已确认的资料纠正或删除。此时不能宣称润色或压缩成功，事实资料仍保留。撤销历史如因失效事实调整，其旧页数也会标 stale。PR4阶段这些诊断用于正确提示，勿展示底层schema路径。

v5 在 `resume_meta.compression_retention_checks` 保存压缩的 `item_id/op/target/status/reason`。合并和缩短均检查证据信息保留；检查失败维持原文，页数可能继续超限。每轮最多一次压缩 writer、最多两轮；保留核验每轮最多一批、30 秒。这里只用于诊断，不能把模型完成等同于压缩成功。

benchmark 的 `fact_snapshot/committed_fact_snapshot` 只用于离线审计，不是公共 API 字段；`committed_sql` 指权威、已隐私清洗的会话读取视图，不是原始数据库字节。

“读岗位”用 requirements 的 direct/transferable/gap 对照 JD 原文；“核对”从 bullets 的 transferable 和 needs_metric 定位到对应项目/条目。不要把 match_plan 覆盖率写成 ATS 分数或录用概率。

## 撤销

`POST /api/resume/session/{session_id}/versions/undo`

```json
{"expected_revision":"GET /current 返回的 64 位 revision", "version_id":"可省略；省略恢复最近一版"}
```

返回 `saved/revision/data/stage/version_id/diff/change_summary/workspace`。成功后用返回 data 更新预览和编辑器，用新 revision 继续保存；409 重新载入，503 保留用户输入并提示稍后重试。接口会再次验证会话权限、revision、失效事实与 provenance；客户端不能提交自造历史正文。

撤销只恢复文稿和证据元数据，事实母版及当前页数要求保持；后加入的经历如在历史中不存在，会保留为 hidden。历史最多十份。已经更正、删除或隐私失效的事实不能经撤销复活。

## 移除与保留

suggestions/generate、preview、apply、undo 端点已删除；删除旧建议采用 UI，改为本次修改与版本撤销。`profile-facts` 端点仍保留。Jev 前端和入口按 PR6 清理；后端兼容清理随新 match_plan 接入完成，不继续建设旧候选建议流程。

## PR6 仍需完成

按规格 §10.5：六模板去掉无照片占位与“个人简历”标题，紧凑页眉及项目单行标题；实际渲染私有 golden 内容后，按真实页数标注容量。`data/jianlimoban/capacity.json` 当前是写作启发式预算，不能直接当作模板“一页适用”的证明。

前端测试保留非建议的既有安全/登录接续/编辑保存/预览/导出覆盖，新增 diff 折叠、撤销冲突与失败、备用项、来源定位和结构化问题选项。私有 real-01 不得复制到公开 fixtures 或提交。
