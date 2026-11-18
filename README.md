# GitHub IPA 软件源生成器

自动扫描 GitHub 仓库所有者的**公开 Star 仓库**，并可额外扫描手动配置的公开仓库；对每个仓库选取最新的包含 `.ipa` 的非草稿、非预发行 Release，逐个列出其中的 `.ipa` 资产，写入符合全能签软件源结构的 `appstore.json`。生成器只调用 GitHub 官方 API 读取元数据，下载链接直指 Release 的原始 `browser_download_url`；本项目不会下载、托管、解包、运行或签名 IPA。

## 安装和启用

1. 在 GitHub 创建一个**公开**仓库，并将本项目文件推送到 `main` 分支根目录。无需 PAT、个人 token 或自行配置 Secrets；Actions 使用仓库自动提供的短期 `GITHUB_TOKEN`，仅读取公开 API 数据，写回本仓库的 `appstore.json`。
2. 确认仓库 Settings → Actions → General 中允许 Actions，并允许工作流写入仓库（Workflow permissions: Read and write permissions）。工作流声明 `contents: write`。如仓库组织策略禁用该权限，请由仓库管理员调整。
3. Actions 会在推送到 `main` 时运行、可在 Actions → Update IPA source → Run workflow 手动运行，并按每天 UTC 02:17（北京时间 10:17）尝试运行。第一次可手动触发。
4. 若要使用 GitHub Pages：Settings → Pages → Build and deployment 的 Source 选择 `GitHub Actions`。工作流生成源后会直接部署 Pages；完成后即可访问。
5. 在全能签添加软件源，填写 `https://<GitHub用户名>.github.io/<仓库名>/appstore.json`。生成 JSON 的 `sourceURL` 会基于 Actions 的 `GITHUB_REPOSITORY` 自动构造为该地址。

## 手动指定其他仓库

编辑根目录 `manual_repositories.json`，填写 GitHub `owner/repo` 或完整公开仓库 URL。例如：

```json
[
  "example-owner/example-app",
  "https://github.com/another-owner/another-app"
]
```

提交更改后工作流自动运行，也可以手动运行。手动仓库必须是公开仓库；无效 JSON 会令任务失败并保留现有源。Star 仓库与手动仓库会去重。

## 生成规则与错误处理

- 输出 UTF-8 JSON；顶层字段为 `name,message,identifier,sourceURL,sourceicon,apps`。每个应用包含 `name,type,version,versionDate,versionDescription,lock,downloadURL,isLanZouCloud,iconURL,tintColor,size`。
- 版本取 Release tag（缺失时回退 Release 名称）；日期取发布时间；更新日志取 Release 正文。应用图标使用仓库所有者头像，缺少时使用 GitHub 默认 favicon。
- 同一个 Release 中的每个 `.ipa` 资产分别生成一条记录，名称包含文件名，用户可辨认不同设备架构/变体。项目不判断 IPA 是否适配 iPhone；列表出现不表示每个包均兼容目标设备。无 IPA 的仓库跳过；草稿和预发行版本不采用。
- 支持 Star 和 Release API 分页，对限流及暂时性网络/服务错误有限重试。若扫描遇到未恢复的 API 错误，则整个生成失败且**不改写**已有 `appstore.json`；404 的仓库按不可用跳过。这样避免部分 API 故障导致破坏性清空源。GitHub 自动提交只在文件有变化时执行，Pages 由同一工作流部署，确保自动更新生效。
- GitHub 官方 API 对公开 Star 的访问无需 PAT。仓库在 Actions 运行时必须为公开，且用户 Star 的列表来自该仓库 owner。API 请求不会打印 token；请勿自行加入 token 输出或上传敏感日志。

## 重要风险与限制

此项目只是整理公开 Release 链接，**不等于自动签名、安装或验证**。GitHub Pages 仅提供 JSON；IPA 从上游 GitHub Release 下载，不经本站中转。第三方 IPA 可能恶意、篡改、失效或不兼容，安装前务必核验发布者、来源、权限和文件。iOS 安装仍受签名、证书、设备与系统版本限制；勿安装来历不明的包。

GitHub Actions 的计划任务不是准时服务，可能延迟、排队或错过。长期无活动的公开仓库计划工作流可能被 GitHub 自动禁用；需留意 Actions 状态并手动运行或恢复工作流。GitHub API 有速率限制；扫描规模过大时任务可能失败，失败时旧 JSON 保持不变。

## 本地测试

Python 3.10+，无需第三方依赖：

```bash
python3 -m unittest discover -s tests -v
```

测试使用模拟 API 响应，不请求 GitHub、不需要账号，也不访问真实 Star 数据。