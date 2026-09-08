# Stage 4E real-plan dataset intake

本目录只保存数据集契约和 manifest，不提交真实户型图、个人信息或授权凭证原件。
真实源图、人工标注和预测模型放在本机或受控对象存储的独立数据根目录中，再以
相对于该数据根目录的路径写入 `manifest.json`。`authorization.reference` 只写
外部审计编号，不写姓名、电话、地址或访问令牌。

当前 `manifest.json` 是 `intake_pending` 空集，不能代表准确率基线。采集首批
授权样本后，每条记录必须同时具备：

1. 原始 PNG/JPEG，记录其字节 SHA-256 和像素尺寸；
2. 按 `stage-4e-annotation-v1` 完成的像素标注，标注中的 `asset_sha256` 必须
   与源图一致；
3. 授权审计编号；
4. `annotation.review_status=reviewed`，以及标注员、复核员的外部标识；
5. `provenance.source` 和对应 ingest `draft-model.json` 预测及其 SHA-256。

可用 `ingest.load_dataset_manifest` 校验结构、`ingest.inspect_dataset` 校验文件
和标注引用，`ingest.evaluate_dataset` 生成确定性的房间 IoU 汇总。数据根目录不
应指向旧仓库，也不应把未经授权的生产或客户资产复制到 Git。
