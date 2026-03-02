# ChatGPT 批量自动注册工具

> 使用 [freemail](https://github.com/idinging/freemail) 创建临时邮箱，并发自动注册 ChatGPT 账号

## 功能

- 📨 自动创建临时邮箱 (freemail 工作器)
- 📥 自动获取 OTP 验证码
- ⚡ 支持并发注册多个账号
- 🔄 自动处理 OAuth 登录
- ☁️ 支持代理配置
- 📤 支持上传账号到 Codex / CPA 面板

## 环境

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
```
然后确保你有 [freemail](https://github.com/idinging/freemail) 服务（如果没有，请先部署一个） 
## 配置 (config.json)

```json
{
  "total_accounts": 5,
  "freemail_worker_domain": "",
  "freemail_token": "",
  "proxy": "http://127.0.0.1:7890",
  "output_file": "registered_accounts.txt",
  "enable_oauth": true,
  "oauth_redirect_uri": "http://localhost:1455/auth/callback",
  "ak_file": "ak.txt",
  "rk_file": "rk.txt"
}
```

| 配置项 | 说明 |
|--------|------|
| total_accounts | 注册账号数量 |
| freemail_worker_domain / freemail_token | freemail 工作器域名与 Token |
| proxy | 代理地址 (可选) |
| output_file | 输出账号文件 |
| enable_oauth | 启用 OAuth 登录 |
| ak_file | Access Key 文件 |
| rk_file | Refresh Key 文件 |

## CPA 面板集成 (TODO)

注册完成后，可以自动上传账号到 CPA 面板：

| 配置项 | 说明 | 参考 |
|--------|------|------|
| upload_api_url | CPA 面板上传 API 地址 | https://help.router-for.me/cn/ |
| upload_api_token | CPA 面板登录密码 | 你的 CPA 面板密码 |

> CPA 面板仓库:  [CPA-Dashboard](https://github.com/dongshuyan/CPA-Dashboard)

## 使用

```bash
uv run main.py
```

## 输出

注册成功的账号会保存到 `output/[时间戳]-[数量]/accounts.txt`

## 目录结构

```
chatgpt_register/
├── main.py                 # 主程序入口
├── app/                    # 应用逻辑
│   ├── cli.py              # 命令行交互
│   ├── registrar.py        # 单次注册流程
│   └── runner.py           # 并发任务调度
├── core/                   # 核心工具
│   ├── config.py           # 配置加载
│   ├── emailing.py         # 邮箱服务适配
│   ├── logger.py           # 日志模块
│   └── utils.py            # 通用工具
├── codex/                  # Codex 协议工具
│   ├── codex.py
│   ├── oauth.py
│   ├── registrar.py
│   ├── sentinel.py
│   ├── utils.py
│   └── README.md
├── output/                 # 输出目录
│   └── [时间戳]-[数量]/
│       ├── registered_accounts.txt
│       ├── ak.txt
│       ├── rk.txt
│       └── codex_tokens/
├── config.json             # 配置文件
├── config.json.example     # 配置示例
├── requirements.txt        # 依赖列表
├── upload.py               # 可选：上传/集成脚本
└── README.md               # 本文档
```

## 注意事项

- 别忘了 [freemail](https://github.com/idinging/freemail) 
- 建议使用代理避免 IP 被封
- 使用 CPA 面板需要先部署面板服务
