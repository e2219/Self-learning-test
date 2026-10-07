"""Shared, proxy-aware DeepSeek transport with credential-safe diagnostics."""
import httpx

from . import security


class ClientSetupError(Exception):
    pass


def api_key():
    key = security.api_key().strip()
    if not key:
        raise ClientSetupError("请先在设置中配置 DeepSeek API Key。")
    if not key.isascii() or any(c.isspace() for c in key):
        raise ClientSetupError("API Key 含非英文字符或内部空白，请重新粘贴密钥（DEEPSEEK_KEY_FORMAT）。")
    return key


def create_client(**kwargs):
    # Keep httpx's environment proxy / NO_PROXY / certificate behavior. Never
    # silently bypass a user's proxy or disable certificate verification.
    try:
        return httpx.AsyncClient(**kwargs)
    except ImportError as exc:
        raise ClientSetupError("网络客户端缺少代理依赖，请停止服务后运行 python start.py 安装更新（DEEPSEEK_PROXY_DEPENDENCY）；请求尚未发出。") from exc
    except (ValueError, httpx.InvalidURL) as exc:
        raise ClientSetupError("代理地址或网络客户端配置无效（DEEPSEEK_PROXY_CONFIG）；请求尚未发出。请检查 HTTP_PROXY、HTTPS_PROXY、ALL_PROXY，支持 http://、https://、socks5:// 或 socks5h://。") from exc


async def check_connection(model):
    """Read models only: no textbook transfer and no generation tokens."""
    key = api_key()
    try:
        async with create_client(timeout=httpx.Timeout(20, connect=10)) as client:
            response = await client.get("https://api.deepseek.com/models", headers={"Authorization": f"Bearer {key}"})
        if response.status_code != 200:
            messages = {401: "DeepSeek 拒绝了密钥，请检查密钥是否有效。", 402: "DeepSeek 账户余额不足。", 429: "DeepSeek 请求限流，请稍后检查。"}
            raise ClientSetupError(messages.get(response.status_code, "DeepSeek 连接检查失败。") + f"（HTTP {response.status_code}）")
        try:
            data = response.json()
            models = data.get("data") if isinstance(data, dict) else None
            if not isinstance(models, list):
                raise ValueError()
            available = any(isinstance(m, dict) and m.get("id") == model for m in models)
        except (ValueError, UnicodeError) as exc:
            raise ClientSetupError("已收到 HTTP 200，但模型列表格式异常，请检查网络代理（DEEPSEEK_MODELS_FORMAT）。") from exc
        return {"connected": True, "ocr_model_available": available,
                "message": f"DeepSeek 连接正常（HTTP 200），{'已确认可用' if available else '模型列表未包含'} OCR 模型 {model}。此检查未发送教材、不消耗生成 tokens；图片识别效果需实际识别确认。"}
    except httpx.TimeoutException as exc:
        raise ClientSetupError("连接 DeepSeek 超时，请检查代理是否正常运行（DEEPSEEK_TIMEOUT）。") from exc
    except httpx.HTTPError as exc:
        raise ClientSetupError(f"无法连接 DeepSeek，请检查代理、网络或证书（DEEPSEEK_NETWORK:{type(exc).__name__}）。") from exc
