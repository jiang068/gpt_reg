# Codex 协议密钥生成工具

> 为 ChatGPT 注册生成 Codex 协议所需的 Access Key 和 Refresh Key

## 功能

- 🔑 自动生成 Access Key (ak)
- 🔄 自动生成 Refresh Key (rk)
- 📤 支持上传到 Codex / CPA 面板
- ⚡ 支持并发生成

## 配置 (config.json)

```json
{
  "total_accounts": 800,
  "concurrent_workers": 8,
  "headless": false,
  "proxy": "http://127.0.0.1:7890",
  "upload_api_url": "https://你的CPA地址/v0/management/auth-files",
  "upload_api_token": "你的CPA密码",
  "cli_proxy_api_base": "你的CPA基础URL",
  "cli_proxy_management_url": "http://你的CPA地址/management.html#/oauth",
  "cli_proxy_password": "你的CPA密码"
}
```

| 配置项 | 说明 |
|--------|------|
| total_accounts | 生成账号数量 |
| concurrent_workers | 并发数 |
| proxy | 代理地址 |
| upload_api_url | CPA 上传 API |
| cli_proxy_api_base | CPA CLI 代理 API |

## 使用

```bash
uv run protocol_keygen.py
```

## 输出

- `ak.txt` - Access Keys
- `rk.txt` - Refresh Keys
- `registered_accounts.csv` - CSV 格式账号

## 接入 CPA 面板

生成后可以自动上传到 CPA 面板：

1. 部署 CPA 面板: https://github.com/dongshuyan/CPA-Dashboard
2. 配置 `upload_api_url` 和 `upload_api_token`
3. 运行后自动上传

> 文档: https://help.router-for.me/cn/
