# plan.json 与脚本

`init`生成完整骨架；智能体填完场景、动作后再生成图像。不要把空的trigger/scene/beats留给图像模型猜。数量、题材、文案均可编辑。

每项：

- id：唯一ASCII字母数字；用于稳定文件名，文案改变不影响精修定位。
- source：项目内图集路径；默认sources/01.png。相对路径不得逃出项目。
- grid：[列,行]；图片必须恰好等分为正方形格。背景和alpha保留，不自动去白底。
- order：从0开始的格子顺序，可复位或跳过已拒绝帧；若改变原动作，向用户说明。
- durations_ms：与order等长，20～10000毫秒。GIF以10毫秒为单位量化，报告读取实际解码时间。
- caption_box：可选归一化[x0,y0,x1,y1]。仅当这一区域全部是文字和稳定装饰、没有动作时才设置。
- caption_frame：核对正确的文字来源格，默认0。不能用错字作为共享供体；锁定只保证一致，不判断语义正确。
- visual_status：pending/reviewed/accepted；只有用户确认才写accepted。
- known_limits：尚未解决的跳切、解剖或内容问题列表。

附件：`attachments: [{"role":"cover","source":"assets/cover.png"}, ...]`；role可为cover/icon/banner，按官方快照配置检查。生成附件后再填写，缺附件时报告会提醒不能称完整投稿包。

工具的技术检查不自动判断文字拼写、透明边缘好坏、故事性或所有审核条文。打包只带独立GIF、实际解码帧总览、HTML、报告及登记附件，不带原始照片、计划里的源路径和生成原图。
