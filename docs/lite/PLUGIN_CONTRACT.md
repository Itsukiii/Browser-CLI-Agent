# LITE-02.2 业务插件与观察接口

实现位于 `src/bca/lite/plugin.py`、`observation.py`；示例 `examples/plugins/lite_fixture.py`。单可信插件、单 Facade、单 Coordinator，不扫描目录、不注册全局插件、不提供通用 Runtime。

## 所有权

Application 先绑定明确 Target 并启动 Capture/Input，以 `require_authorization=True` 创建 Bridge；随后将该 Bridge **独占委托**给 MaaVisionFacade，并将 Facade/插件独占委托给 Coordinator。宿主不再绕过 Coordinator 调用 Facade、Bridge 或底层输入。Plugin.resources 必须与 Facade.resources 一致。

插件只处理数据：`plan(image_size)`、`observe(batch)`、`format_state(state)`、`parse_command(text)`、`resolve(action_intent,state)`、幂等 `close()`。全部同步且必须轻量，无后台任务、网络或 native 句柄。plan 在本次实际 Maa 截图后调用，尺寸正确且无需再拍一张“规划截图”。不要求插件重复加载模型。

## 数据

- BusinessState：status、payload、signature、可选 interaction_revision、targets、diagnostic。payload/signature 只允许不可变 scalar/递归 tuple，拒绝 dict/list/非有限数；targets 是冻结 VisualTarget 的 tuple。
- VisualTarget 仅指向 `(target_key, request_key, candidate_index)`，不接受插件任意填写坐标。宿主根据原 batch 的真实唯一候选取中心；VisualObservation.regions 单独提供识别框。
- VisualObservation：序号、BusinessState、原始 ObservationRef、binding、Maa image_size、completed_at、expired、regions 和 `coordinate_space=maa_image_pixels`。不长期存放 BGR 数组；Frame 引用仍含 PNG。旧快照不可被后续结果覆盖。
- signature 比较内容，不含 Frame ID/时间；交互 revision 是视觉可见回合标志，不能拿内容相同推断同一回合。宿主不会把原 revision 换成新 revision 继续旧动作。fixture 的 OCR 数字仅在受控测试页被定义为可见回合标志，不代表一般网页数字都能充当回合证据。
- ReadIntent 触发新截图；ActionIntent 目前只支持 `click`，包含 target_key、expected_revision、单调时钟 deadline。缺 revision、过期、业务非 MATCHED 都拒绝。

## 调用与通知

`await start()` 启动资源和周期观察；重复 start 幂等。首次周期观察在 interval 后开始，`refresh()` 可立即查询。`await stop()` 禁止新命令/周期入口并等待当前工作，保留资源，可再次 start；与未完成 start 竞争时 stop 胜出。`await aclose()` 终态不可重启。

`refresh()` 始终等到串行门后重新截图。`execute_text()` 仅先做纯解析，然后 `execute_intent()` 在同一门内执行：新观察→匹配原 revision/deadline→解析目标→核对唯一候选→Facade 检查精确 batch→Bridge.authorize(精确ref)→native click→新观察。门从开始到后置观察均不释放，背景观察和其他读写不能替换 ref。confirmed 只说明输入确认；CommandResult 分别返回 outcome、后置 observation、格式化文本，不宣称业务结算成功。

Facade.click 只接受自己最后签发的同一 Batch 对象，要求明确授权模式、MATCHED 且唯一候选；复制的 Batch 或前一帧都拒绝。候选中心使用 Maa 返回图像像素，Maa 转 raw，Bridge 转 CSS；映射后 raw 越界拒绝，不提前转 CSS。

2026-11-26 P1补充：成功authorize建立本次输入边界，将input_outcome重置为not_attempted；截图本身不改历史输入结果。Facade保存并核验本次native Job.succeeded，排空后由Bridge.finish_native_click进行一致性检查：只有本次Job成功、当前边界CDP确认且Bridge仍有效才返回confirmed。native未进callback就失败、成功但没有callback、callback失败、ACK丢失、callback后native失败/异常一律unknown并阻断组合，无自动重试；此处unknown是保守结果，不声称一定发出了输入。取消仍等native排空再传播，不以历史confirmed报本次成功。该同步归并接口只供独占Facade在本次job排空后调用，不是可绕过Job的授权接口。

Coordinator.latest 永远更新，通知只比较 `(status,signature,diagnostic)`。`take_change()` 非阻塞取轻量 `(sequence,status)`；容量满丢最旧提示并增加 dropped_notifications，消费者通过序号发现遗漏并读 latest，不阻塞观察。非广播事件总线，无无限图片队列。

`stats` 返回 completed/valid/dropped_notifications/skipped_ticks/last_duration 快照；valid 仅计本次来源有效且未过期的 MATCHED。周期操作不会并行，超期不积压补跑；interval 是目标起始间隔，实际频率由完成时间记录测量，不以配置值冒充性能。

## 错误、取消与释放

NOT_FOUND/AMBIGUOUS/插件解析错误会更新快照并通知状态变化，后续新观察可恢复；识别 ERROR 不伪装旧成功状态。Bridge 断连、超时或 unknown 退役本组合，禁止自动重连和重放；应用需新建 Bridge/Facade/Coordinator。取消在途观察/命令会 invalidate，等待 native 工作排空并调用/核对 aclose；不把 asyncio cancellation 当成资源已释放。

close 的共享清理任务抵御重复取消；plugin.close 失败保留到 CloseReport.errors，可重试纯插件关闭。`CloseReport.released` 专指原生释放，不能据此忽略插件 errors。Application 只有在原生 released=true 且检查完错误后才继续关闭 Input/Capture/自建 Target/Session。

Tasker stop 失败、异常或仍 running：released=false，不 Destroy，不关闭借用 Bridge/Providers；保留句柄和 worker，可在同一 worker 重试 stop。Destroy 本身异常：结果不确定，句柄转入进程期隔离、清空对象可调用指针防析构/重复释放，released=false；不会重新调用原指针。清空不是释放证明，此情况必须保留诊断并结束该应用进程，不能继续使用依赖。这是保守终止边界，不是 native 泄漏恢复机制。
