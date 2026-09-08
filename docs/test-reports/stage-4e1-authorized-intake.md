# 阶段 4E-1 授权图 intake 记录

日期：2026-09-08

## 源证据

- 授权状态：用户在本次会话明确授权使用该图片作为测试样本。
- 原始文件：`微信图片_2026-09-08_143222_540.png`（当前仅保留在本机受控数据目录）。
- 格式：PNG RGBA，`1080 x 1214`。
- 源字节 SHA-256：`a3ae5a6c1ea5f965d39aabcd8c5eceda81bd1750866f04df1e25c9a4f44aa6aa`。
- 已通过 `load_bitmap` 完整解码。

## 当前算法结果

使用当前 `orthogonal-cv-0.2`、显式 `mm_per_pixel=1.0` 运行 ingest，结果为：

```text
BitmapError: no_closed_rectangle: no supported closed orthogonal room was found
```

因此当前没有合法的 draft prediction artifact，不能把失败结果包装成模型，也不能
把算法候选直接写成 ground truth。该失败本身作为真实复杂宣传页的拒识证据保留。

## 人工标注待办

主体平面约位于 `x=170..905, y=553..1040`。初步可见四房两厅双卫，以及阳台、
玄关、厨房和衣帽/收纳区域。以下问题必须由标注员在原图上确认后，才能生成
`stage-4e-annotation-v1`：

- 开放式 Dining/Living/Kitchen 是否拆成独立 room；
- CLOAKROOM、VESTIBULE 和 BALCONY 是否计入房间评测；
- 所有墙体需按棕色粗线中心线逐段标注，并在门洞处拆段；
- 每个门、窗、阳台推拉门需确认 `host_wall_id`、offset、width 和 kind；
- 不得把家具轮廓、标题栏、尺寸线当成墙体事实。

该记录当前仍为 intake 候选，不能解除 4E-1 阶段门。
