# 个人 GitHub IPA 软件源

这个公开源定期从仓库所有者的公开 GitHub Stars 和 `manual_repositories.json` 中检查 Release，生成 AltStore 格式的 IPA 列表，并使用 GitHub Pages 发布。IPA 下载地址直接指向原发布者的 GitHub Release，不通过本仓库托管、签名或安装。

软件源地址：`https://dbwxxxxxx.github.io/ipa-source/appstore.json`

源格式参考 [AltStore 文档](https://faq.altstore.io/developers/make-a-source)及 iPadn 提供的 AltStore 格式示例。该格式是否可由特定版本的全能签导入，需要在该客户端验证；不能根据 JSON 可访问推断兼容。

## 增加软件

使用此 GitHub 账号给希望收录的公开项目点 Star，或者编辑 `manual_repositories.json` 添加公开仓库地址。例如：

```json
["owner/repository", "https://github.com/another-owner/another-repository"]
```

只扫描公开仓库包含 `.ipa` 资产的稳定 Release；草稿与预发布版本会跳过。同一应用的不同安装包可能具有相同的 Bundle ID，而 AltStore 不允许源内重复 ID，因此只显示一个版本。应用图标使用 GitHub 仓库所有者头像，不一定是应用图标。

## 自动更新和限制

GitHub Actions 每两小时第 17 分尝试运行（UTC；北京时间同为偶数小时的第 17 分），也可在仓库的 Actions 页面手动运行。工作流读取 IPA 的部分 ZIP 信息，解析主应用的 Bundle ID 和版本信息，不执行安装包；无法获取必要信息的包可能被跳过。GitHub 定时任务可能延迟或在仓库长期无活动时被禁用。

本源只是整理链接，不保证 IPA 安全、适配设备或能够签名安装；安装前应核验来源和系统要求。需要你自己具备有效的签名或安装条件。

## 更新说明

优先使用经核实的中文摘要和原文中的中文更新要点；英文说明会尝试通过 Google 的非正式翻译接口翻译部分公开 Release 内容，可能存在延迟、失效或误译。翻译不可用时显示提示和 Release 原文链接，不影响软件源更新。重要兼容性及签名要求请以原发布者的完整说明为准。
