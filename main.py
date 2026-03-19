#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金灯塔胜算 Skill - 主入口（完整版）
飞书集成 BI 报表技能，支持自然语言查询、HTML 可视化报表生成、OSS 上传、定时推送和胜算平台发布

包含完整的飞书 OAuth 授权流程，可直接获取用户绑定的手机号。
"""

import json
import os
import base64
import uuid
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

# ==================== 配置常量 ====================

SKILL_NAME = "金灯塔胜算"
VERSION = "1.0.0"

# 🚨 飞书应用配置（请替换成你的真实配置）
FEISHU_APP_ID = "cli_xxxxx"  # ← 替换成你的飞书应用 App ID
FEISHU_APP_SECRET = "xxxxx"  # ← 替换成你的飞书应用 App Secret
FEISHU_REDIRECT_URI = "https://你的域名/oauth/callback"  # ← 替换成你的回调地址

# 🚨 胜算系统 API 基础地址（请替换成你的真实地址）
SHENGSAUN_BASE_URL = "https://api.shengsuan.example.com"

# 🚨 OSS 配置（或从胜算初始化接口动态获取）
OSS_DOMAIN = "https://oss.example.com"
OSS_UPLOAD_API = f"{SHENGSAUN_BASE_URL}/oss/upload"
OSS_STATIC_DOMAIN = "https://static.oss.example.com"

# ==================== 会话状态管理 ====================

class SessionContext:
    """会话上下文，存储初始化后的配置和状态"""
    
    def __init__(self):
        self.user_open_id: Optional[str] = None
        self.user_phone: Optional[str] = None
        self.user_access_token: Optional[str] = None
        self.user_refresh_token: Optional[str] = None
        self.token_expires_in: int = 7200  # 默认 2 小时
        
        self.system_name: Optional[str] = None
        self.system_token: Optional[str] = None
        self.system_token_expires_at: Optional[datetime] = None
        
        self.oss_domain: str = OSS_DOMAIN
        self.oss_api: str = OSS_UPLOAD_API
        self.oss_static_domain: str = OSS_STATIC_DOMAIN
        self.supported_systems: List[str] = []
        self.api_registry: Dict[str, Any] = {}
        self.last_report_url: Optional[str] = None
        self.initialized: bool = False
        self.oauth_completed: bool = False
    
    def is_system_token_valid(self) -> bool:
        """检查胜算系统 token 是否有效（距过期还有 5 分钟以上）"""
        if not self.system_token_expires_at:
            return False
        return datetime.now() < (self.system_token_expires_at - timedelta(minutes=5))
    
    def is_user_access_token_valid(self) -> bool:
        """检查飞书 user_access_token 是否有效"""
        # 简化判断：假设 token 有效期 2 小时，这里可以根据实际刷新时间判断
        return bool(self.user_access_token)
    
    def to_dict(self) -> Dict:
        """序列化为字典（用于持久化）"""
        return {
            "user_open_id": self.user_open_id,
            "user_phone": self.user_phone,
            "user_access_token": self.user_access_token,
            "user_refresh_token": self.user_refresh_token,
            "token_expires_in": self.token_expires_in,
            "system_name": self.system_name,
            "system_token": self.system_token,
            "system_token_expires_at": self.system_token_expires_at.isoformat() if self.system_token_expires_at else None,
            "oss_domain": self.oss_domain,
            "oss_api": self.oss_api,
            "oss_static_domain": self.oss_static_domain,
            "supported_systems": self.supported_systems,
            "api_registry": self.api_registry,
            "last_report_url": self.last_report_url,
            "initialized": self.initialized,
            "oauth_completed": self.oauth_completed
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "SessionContext":
        """从字典反序列化"""
        ctx = cls()
        ctx.user_open_id = data.get("user_open_id")
        ctx.user_phone = data.get("user_phone")
        ctx.user_access_token = data.get("user_access_token")
        ctx.user_refresh_token = data.get("user_refresh_token")
        ctx.token_expires_in = data.get("token_expires_in", 7200)
        ctx.system_name = data.get("system_name")
        ctx.system_token = data.get("system_token")
        expires_str = data.get("system_token_expires_at")
        ctx.system_token_expires_at = datetime.fromisoformat(expires_str) if expires_str else None
        ctx.oss_domain = data.get("oss_domain", OSS_DOMAIN)
        ctx.oss_api = data.get("oss_api", OSS_UPLOAD_API)
        ctx.oss_static_domain = data.get("oss_static_domain", OSS_STATIC_DOMAIN)
        ctx.supported_systems = data.get("supported_systems", [])
        ctx.api_registry = data.get("api_registry", {})
        ctx.last_report_url = data.get("last_report_url")
        ctx.initialized = data.get("initialized", False)
        ctx.oauth_completed = data.get("oauth_completed", False)
        return ctx


# 全局会话上下文（实际使用时应从存储中加载）
_session_context: Optional[SessionContext] = None


def get_context() -> SessionContext:
    """获取当前会话上下文"""
    global _session_context
    if _session_context is None:
        _session_context = SessionContext()
    return _session_context


def reset_context():
    """重置会话上下文（用于重新初始化）"""
    global _session_context
    _session_context = SessionContext()


# ==================== 飞书 OAuth 授权模块（完整实现） ====================

async def feishu_oauth_request(scopes: List[str]) -> Dict:
    """
    生成飞书授权链接，用户点击后完成授权
    
    Args:
        scopes: 请求的权限列表，例如：
                ['contact:employee.read', 'im:message.send', 'calendar:task.write']
    
    Returns:
        包含授权链接的字典，用户点击后跳转到飞书授权页面
    """
    if not FEISHU_APP_ID or FEISHU_APP_ID == "cli_xxxxx":
        return {
            "status": "error",
            "message": "⚠️ 尚未配置飞书应用信息\n\n请在 main.py 中设置：\n- FEISHU_APP_ID\n- FEISHU_APP_SECRET\n- FEISHU_REDIRECT_URI"
        }
    
    # 生成 state 防止 CSRF 攻击
    state = str(uuid.uuid4())
    
    # 构建授权链接
    params = {
        "app_id": FEISHU_APP_ID,
        "redirect_uri": FEISHU_REDIRECT_URI,
        "state": state,
        "scope": " ".join(scopes)
    }
    
    auth_url = "https://open.feishu.cn/open-apis/authen/v1/authorize?" + urllib.parse.urlencode(params)
    
    # 保存 state 到上下文（用于后续验证）
    ctx = get_context()
    ctx._oauth_state = state  # type: ignore
    
    return {
        "status": "pending",
        "auth_url": auth_url,
        "state": state,
        "message": f"""📱 **Step 1: 飞书授权**

请点击以下链接完成授权：

🔗 [**立即授权**]({auth_url})

**请求的权限：**
- 📞 获取用户手机号（用于身份识别）
- 💬 发送飞书消息（用于推送报表）
- ⏰ 创建定时任务（用于自动推送）

授权完成后，请回复 **"已授权"** 继续下一步。"""
    }


async def feishu_exchange_code(code: str, state: str) -> Dict:
    """
    用授权码换取 user_access_token
    
    Args:
        code: 授权回调返回的 code
        state: 之前生成的 state（用于验证）
    
    Returns:
        包含 user_access_token 的字典
    """
    import aiohttp
    
    ctx = get_context()
    
    # 验证 state
    if getattr(ctx, '_oauth_state', None) != state:
        return {"success": False, "error": "State 验证失败，请重新授权"}
    
    # 构建 Basic Auth header
    credentials = f"{FEISHU_APP_ID}:{FEISHU_APP_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    
    payload = {
        "grant_type": "authorization_code",
        "code": code
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://open.feishu.cn/open-apis/authen/v1/access_token",
                json=payload,
                headers={
                    "Authorization": f"Basic {encoded_credentials}",
                    "Content-Type": "application/json"
                }
            ) as resp:
                result = await resp.json()
                
                if result.get("code") == 0:
                    data = result.get("data", {})
                    ctx.user_access_token = data.get("access_token")
                    ctx.user_refresh_token = data.get("refresh_token")
                    ctx.token_expires_in = data.get("expires_in", 7200)
                    ctx.oauth_completed = True
                    
                    return {
                        "success": True,
                        "access_token": ctx.user_access_token,
                        "expires_in": ctx.token_expires_in
                    }
                else:
                    return {
                        "success": False,
                        "error": result.get("msg", "Unknown error"),
                        "code": result.get("code")
                    }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def feishu_get_user_info(access_token: str) -> Dict:
    """
    获取当前用户信息（包括 open_id）
    
    GET https://open.feishu.cn/open-apis/authen/v1/user_info
    """
    import aiohttp
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://open.feishu.cn/open-apis/authen/v1/user_info",
                headers={"Authorization": f"Bearer {access_token}"}
            ) as resp:
                result = await resp.json()
                
                if result.get("code") == 0:
                    return {
                        "success": True,
                        "data": result.get("data", {})
                    }
                else:
                    return {
                        "success": False,
                        "error": result.get("msg", "Unknown error")
                    }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def feishu_get_user_phone(access_token: str) -> Dict:
    """
    用 access_token 获取用户手机号
    
    GET https://open.feishu.cn/open-apis/contact/v3/users/:user_id?mobile=1
    
    Returns:
        {"success": True, "phone": "13812345678", "open_id": "ou_xxxxx"}
        或 {"success": False, "error": "..."}
    """
    import aiohttp
    
    # Step 1: 先获取用户 open_id
    user_info_result = await feishu_get_user_info(access_token)
    if not user_info_result["success"]:
        return user_info_result
    
    user_data = user_info_result.get("data", {}).get("user", {})
    open_id = user_data.get("open_id")
    
    if not open_id:
        return {"success": False, "error": "无法获取用户 open_id"}
    
    # Step 2: 用 open_id 获取手机号
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://open.feishu.cn/open-apis/contact/v3/users/{open_id}?user_id_type=open_id&mobile=1",
                headers={"Authorization": f"Bearer {access_token}"}
            ) as resp:
                result = await resp.json()
                
                if result.get("code") == 0:
                    phone = result.get("data", {}).get("user", {}).get("mobile")
                    
                    # 更新上下文
                    ctx = get_context()
                    ctx.user_open_id = open_id
                    ctx.user_phone = phone
                    
                    return {
                        "success": True,
                        "phone": phone,
                        "open_id": open_id
                    }
                else:
                    return {
                        "success": False,
                        "error": result.get("msg", "获取手机号失败"),
                        "code": result.get("code")
                    }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def feishu_refresh_access_token(refresh_token: str) -> Dict:
    """
    用 refresh_token 刷新 access_token
    
    POST https://open.feishu.cn/open-apis/authen/v1/refresh_access_token
    """
    import aiohttp
    
    credentials = f"{FEISHU_APP_ID}:{FEISHU_APP_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://open.feishu.cn/open-apis/authen/v1/refresh_access_token",
                json=payload,
                headers={
                    "Authorization": f"Basic {encoded_credentials}",
                    "Content-Type": "application/json"
                }
            ) as resp:
                result = await resp.json()
                
                if result.get("code") == 0:
                    data = result.get("data", {})
                    ctx = get_context()
                    ctx.user_access_token = data.get("access_token")
                    ctx.user_refresh_token = data.get("refresh_token")
                    
                    return {
                        "success": True,
                        "access_token": ctx.user_access_token,
                        "expires_in": data.get("expires_in", 7200)
                    }
                else:
                    return {
                        "success": False,
                        "error": result.get("msg", "刷新 token 失败")
                    }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== 胜算系统 API 客户端 ====================

async def shengsuan_get_supported_systems() -> Dict:
    """
    获取胜算平台支持的系统列表
    GET /auth/supported-systems
    
    返回：
    {
        "systems": ["销售系统", "订单系统", ...],
        "oss_domain": "...",
        "oss_api": "...",
        "oss_static_domain": "..."
    }
    """
    import aiohttp
    
    # TODO: 替换成真实的 API 调用
    # async with aiohttp.ClientSession() as session:
    #     async with session.get(f"{SHENGSAUN_BASE_URL}/auth/supported-systems") as resp:
    #         return await resp.json()
    
    # 模拟返回（演示用）
    return {
        "systems": ["销售系统", "订单系统", "用户系统", "财务系统"],
        "oss_domain": OSS_DOMAIN,
        "oss_api": OSS_UPLOAD_API,
        "oss_static_domain": OSS_STATIC_DOMAIN
    }


async def shengsuan_get_system_token(phone: str, system_name: str) -> Dict:
    """
    获取系统访问 Token
    POST /auth/system-token
    
    入参：{ "phone": "13812345678", "system_name": "销售系统" }
    返回：{ "token": "...", "expires_at": "2026-03-19T16:00:00" }
    """
    import aiohttp
    
    # TODO: 替换成真实的 API 调用
    # async with aiohttp.ClientSession() as session:
    #     async with session.post(
    #         f"{SHENGSAUN_BASE_URL}/auth/system-token",
    #         json={"phone": phone, "system_name": system_name}
    #     ) as resp:
    #         return await resp.json()
    
    # 模拟返回（演示用）
    expires_at = datetime.now() + timedelta(hours=2)
    return {
        "token": f"mock_token_{system_name}_{phone}",
        "expires_at": expires_at.isoformat()
    }


async def shengsuan_get_api_registry(token: str) -> Dict:
    """
    获取系统 API 注册表
    GET /system/api-registry
    
    返回每个接口的完整文档信息
    """
    import aiohttp
    
    # TODO: 替换成真实的 API 调用
    # async with aiohttp.ClientSession() as session:
    #     async with session.get(
    #         f"{SHENGSAUN_BASE_URL}/system/api-registry",
    #         headers={"Authorization": f"Bearer {token}"}
    #     ) as resp:
    #         return await resp.json()
    
    # 模拟返回（演示用）
    return {
        "apis": [
            {
                "api_id": "sales_trend",
                "name": "销售趋势查询",
                "method": "GET",
                "endpoint": "/api/sales/trend",
                "params": [
                    {"name": "start_date", "type": "string", "required": True, "desc": "开始日期 YYYY-MM-DD"},
                    {"name": "end_date", "type": "string", "required": True, "desc": "结束日期 YYYY-MM-DD"},
                    {"name": "dimension", "type": "string", "required": False, "desc": "维度：channel/product/region"}
                ],
                "response_schema": {
                    "type": "array",
                    "items": {
                        "date": "string",
                        "value": "number",
                        "dimension": "string"
                    }
                }
            },
            {
                "api_id": "order_stats",
                "name": "订单统计",
                "method": "GET",
                "endpoint": "/api/orders/stats",
                "params": [
                    {"name": "date_range", "type": "string", "required": True, "desc": "时间范围：today/yesterday/last_7days/last_month"},
                    {"name": "group_by", "type": "string", "required": False, "desc": "分组字段：channel/status"}
                ],
                "response_schema": {
                    "type": "object",
                    "properties": {
                        "total_orders": "number",
                        "total_amount": "number",
                        "details": "array"
                    }
                }
            }
        ]
    }


async def shengsuan_call_api(token: str, api_def: Dict, params: Dict) -> Any:
    """
    调用胜算系统 API
    
    根据 api_def 中的 endpoint 和 method 发起真实请求
    """
    import aiohttp
    
    # TODO: 替换成真实的 API 调用
    # url = f"{SHENGSAUN_BASE_URL}{api_def['endpoint']}"
    # method = api_def['method'].upper()
    #
    # async with aiohttp.ClientSession() as session:
    #     if method == "GET":
    #         async with session.get(url, params=params, headers={"Authorization": f"Bearer {token}"}) as resp:
    #             return await resp.json()
    #     elif method == "POST":
    #         async with session.post(url, json=params, headers={"Authorization": f"Bearer {token}"}) as resp:
    #             return await resp.json()
    
    # 模拟返回数据（演示用）
    api_id = api_def.get("api_id")
    
    if api_id == "sales_trend":
        return [
            {"date": "2026-03-01", "value": 12500, "dimension": "渠道 A"},
            {"date": "2026-03-02", "value": 15800, "dimension": "渠道 A"},
            {"date": "2026-03-03", "value": 13200, "dimension": "渠道 A"},
            {"date": "2026-03-04", "value": 18900, "dimension": "渠道 A"},
            {"date": "2026-03-05", "value": 21000, "dimension": "渠道 A"},
        ]
    elif api_id == "order_stats":
        return {
            "total_orders": 1250,
            "total_amount": 458900,
            "details": [
                {"channel": "线上", "orders": 800, "amount": 320000},
                {"channel": "线下", "orders": 450, "amount": 138900}
            ]
        }
    
    return {"error": "Unknown API"}


# ==================== 意图识别模块 ====================

def parse_intent(user_input: str, api_registry: Dict) -> Dict:
    """
    解析用户意图，匹配 API 接口
    
    返回：{"matched_api": api_def, "params": {...}, "confidence": 0.95}
    """
    # TODO: 可以用 LLM 实现更智能的意图识别
    # 当前使用简单规则匹配
    
    user_input_lower = user_input.lower()
    
    # 匹配销售趋势
    if any(kw in user_input_lower for kw in ["销售", "销售额", "趋势"]):
        api_def = next((api for api in api_registry.get("apis", []) if api["api_id"] == "sales_trend"), None)
        if api_def:
            params = extract_time_params(user_input)
            return {"matched_api": api_def, "params": params, "confidence": 0.9}
    
    # 匹配订单统计
    if any(kw in user_input_lower for kw in ["订单", "单量"]):
        api_def = next((api for api in api_registry.get("apis", []) if api["api_id"] == "order_stats"), None)
        if api_def:
            params = {"date_range": "last_7days"}  # 默认最近 7 天
            return {"matched_api": api_def, "params": params, "confidence": 0.85}
    
    return {"matched_api": None, "params": {}, "confidence": 0.0}


def extract_time_params(text: str) -> Dict:
    """从文本中提取时间参数"""
    now = datetime.now()
    
    if "上个月" in text:
        first_day = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
        last_day = now.replace(day=1) - timedelta(days=1)
        return {"start_date": first_day.strftime("%Y-%m-%d"), "end_date": last_day.strftime("%Y-%m-%d")}
    
    if "上周" in text:
        delta = now.weekday() + 7
        last_monday = now - timedelta(days=delta)
        last_sunday = last_monday + timedelta(days=6)
        return {"start_date": last_monday.strftime("%Y-%m-%d"), "end_date": last_sunday.strftime("%Y-%m-%d")}
    
    # 默认最近 7 天
    end_date = now
    start_date = now - timedelta(days=6)
    return {"start_date": start_date.strftime("%Y-%m-%d"), "end_date": end_date.strftime("%Y-%m-%d")}


# ==================== HTML 报表生成器 ====================

def generate_html_report(
    system_name: str,
    report_name: str,
    time_range: str,
    chart_type: str,
    chart_data: List[Dict],
    table_data: List[Dict],
    summary: str,
    suggestions: List[str],
    oss_static_domain: str
) -> str:
    """
    生成完整的 HTML 报表文件（响应式，含 ECharts 图表）
    """
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{report_name} - {system_name}</title>
    <script src="{oss_static_domain}/libs/echarts/echarts.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background: #f5f7fa; color: #333; line-height: 1.6; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        
        /* 标题区 */
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 12px; margin-bottom: 20px; }}
        .header h1 {{ font-size: 28px; margin-bottom: 8px; }}
        .header .meta {{ opacity: 0.9; font-size: 14px; }}
        
        /* 筛选区 */
        .filters {{ background: white; padding: 20px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        .filters .filter-row {{ display: flex; gap: 15px; flex-wrap: wrap; align-items: center; }}
        .filters label {{ font-weight: 600; font-size: 14px; }}
        .filters input, .filters select {{ padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }}
        .filters button {{ background: #667eea; color: white; border: none; padding: 8px 20px; border-radius: 6px; cursor: pointer; font-weight: 600; }}
        .filters button:hover {{ background: #5568d3; }}
        
        /* 图表区 */
        .chart-container {{ background: white; padding: 20px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        #chart {{ width: 100%; height: 400px; }}
        
        /* 表格区 */
        .table-container {{ background: white; padding: 20px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; font-weight: 600; position: sticky; top: 0; }}
        tr:nth-child(even) {{ background: #fafbfc; }}
        tr:hover {{ background: #f0f4ff; }}
        
        /* 总结区 */
        .summary {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        .summary h3 {{ color: #667eea; margin-bottom: 12px; }}
        .summary p {{ margin-bottom: 15px; }}
        .summary ul {{ margin-left: 20px; }}
        .summary li {{ margin-bottom: 8px; }}
        .footer {{ margin-top: 20px; font-size: 12px; color: #999; text-align: center; }}
        
        /* 响应式 */
        @media (max-width: 768px) {{
            .header h1 {{ font-size: 22px; }}
            .filters .filter-row {{ flex-direction: column; align-items: stretch; }}
            #chart {{ height: 300px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- 标题区 -->
        <div class="header">
            <h1>{report_name}</h1>
            <div class="meta">{system_name} · {time_range}</div>
        </div>
        
        <!-- 筛选区 -->
        <div class="filters">
            <div class="filter-row">
                <label>时间范围：</label>
                <input type="date" id="startDate" value="{chart_data[0]['date'] if chart_data else ''}">
                <input type="date" id="endDate" value="{chart_data[-1]['date'] if chart_data else ''}">
                <label>维度：</label>
                <select id="dimension">
                    <option value="channel">渠道</option>
                    <option value="product">产品</option>
                    <option value="region">区域</option>
                </select>
                <button onclick="refreshData()">🔍 查询</button>
            </div>
        </div>
        
        <!-- 图表区 -->
        <div class="chart-container">
            <div id="chart"></div>
        </div>
        
        <!-- 表格区 -->
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        {''.join(f'<th>{k}</th>' for k in table_data[0].keys()) if table_data else ''}
                    </tr>
                </thead>
                <tbody>
                    {''.join(f"<tr>{''.join(f'<td>{v}</td>' for v in row.values())}</tr>" for row in table_data) if table_data else ''}
                </tbody>
            </table>
        </div>
        
        <!-- 总结区 -->
        <div class="summary">
            <h3>📊 数据总结</h3>
            <p>{summary}</p>
            <h3>💡 建议</h3>
            <ul>
                {''.join(f'<li>{s}</li>' for s in suggestions)}
            </ul>
        </div>
        
        <div class="footer">
            生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 数据来源：{system_name}
        </div>
    </div>
    
    <script>
        // ECharts 图表初始化
        const chartDom = document.getElementById('chart');
        const myChart = echarts.init(chartDom);
        
        const option = {{
            title: {{ text: '{report_name}', left: 'center' }},
            tooltip: {{ trigger: 'axis' }},
            legend: {{ data: ['数值'], bottom: 0 }},
            xAxis: {{
                type: 'category',
                data: [{', '.join(f"'{item['date']}'" for item in chart_data) if chart_data else ''}]
            }},
            yAxis: {{ type: 'value' }},
            series: [{{
                name: '数值',
                type: '{'line' if chart_type == 'line' else 'bar'}',
                data: [{', '.join(str(item['value']) for item in chart_data) if chart_data else ''}],
                smooth: true,
                itemStyle: {{ color: '#667eea' }}
            }}]
        }};
        
        myChart.setOption(option);
        
        // 响应式调整
        window.addEventListener('resize', () => myChart.resize());
        
        // 查询功能（占位）
        async function refreshData() {{
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;
            const dimension = document.getElementById('dimension').value;
            
            // TODO: 调用真实 API
            console.log('查询条件:', {{ startDate, endDate, dimension }});
            alert('查询功能开发中...');
        }}
    </script>
</body>
</html>"""
    
    return html


# ==================== OSS 上传模块（占位） ====================

async def oss_upload(html_content: str, filename: str) -> Dict:
    """
    上传 HTML 文件到 OSS
    POST {oss_api}
    
    TODO: 替换成真实的 OSS 上传接口
    """
    import aiohttp
    
    # TODO: 真实实现
    # form_data = aiohttp.FormData()
    # form_data.add_field('file', html_content.encode('utf-8'), filename=filename, content_type='text/html')
    #
    # async with aiohttp.ClientSession() as session:
    #     async with session.post(OSS_UPLOAD_API, data=form_data) as resp:
    #         return await resp.json()
    
    # 模拟返回（演示用）
    return {
        "success": True,
        "preview_url": f"{OSS_DOMAIN}/reports/{filename}"
    }


# ==================== 主命令处理 ====================

async def handle_command(command: str, args: List[str], user_input: str) -> str:
    """
    处理用户命令
    """
    ctx = get_context()
    
    if command == "初始化":
        reset_context()  # 重置状态
        return await cmd_initialize(ctx)
    
    elif command == "授权":
        return await cmd_oauth(ctx)
    
    elif command == "系统列表":
        return await cmd_system_list(ctx)
    
    elif command == "切换系统":
        if not args:
            return "❌ 请指定系统名称，例如：/金灯塔胜算 切换系统 销售系统"
        return await cmd_switch_system(ctx, args[0])
    
    elif command == "我的任务":
        return await cmd_my_tasks(ctx)
    
    elif command == "取消任务":
        if not args:
            return "❌ 请指定任务 ID"
        return await cmd_cancel_task(ctx, args[0])
    
    elif command == "帮助":
        return cmd_help()
    
    else:
        # 尝试作为自然语言查询处理
        return await handle_natural_language(ctx, user_input)


async def cmd_initialize(ctx: SessionContext) -> str:
    """执行初始化流程"""
    steps = []
    
    # Step 1: 飞书授权
    oauth_result = await feishu_oauth_request([
        "contact:employee.read",
        "im:message.send",
        "calendar:task.write"
    ])
    
    if oauth_result.get("status") == "error":
        return oauth_result["message"]
    
    return oauth_result["message"]


async def cmd_oauth(ctx: SessionContext) -> str:
    """处理"已授权"回调（需要配合 webhook 或手动输入 code）"""
    # 这个命令通常不直接使用，而是通过回调处理
    return "ℹ️ 授权回调需要通过飞书开放平台的回调 URL 自动处理。\n\n如果你已完成授权但未被识别，请尝试重新执行 `/金灯塔胜算 初始化`"


async def cmd_system_list(ctx: SessionContext) -> str:
    """查看支持的系统列表"""
    if not ctx.oauth_completed:
        return "⚠️ 请先完成飞书授权，执行 `/金灯塔胜算 初始化`"
    
    if not ctx.supported_systems:
        # 加载系统配置
        config = await shengsuan_get_supported_systems()
        ctx.supported_systems = config["systems"]
        ctx.oss_domain = config["oss_domain"]
        ctx.oss_api = config["oss_api"]
        ctx.oss_static_domain = config["oss_static_domain"]
    
    lines = ["📋 **支持的业务系统：**"]
    for i, sys in enumerate(ctx.supported_systems, 1):
        current = " ✅ (当前)" if sys == ctx.system_name else ""
        lines.append(f"  {i}. {sys}{current}")
    
    return "\n".join(lines)


async def cmd_switch_system(ctx: SessionContext, system_name: str) -> str:
    """切换到指定系统"""
    if not ctx.oauth_completed:
        return "⚠️ 请先完成飞书授权，执行 `/金灯塔胜算 初始化`"
    
    if not ctx.supported_systems:
        config = await shengsuan_get_supported_systems()
        ctx.supported_systems = config["systems"]
    
    if system_name not in ctx.supported_systems:
        return f"❌ 未知系统 '{system_name}'，可用系统：{', '.join(ctx.supported_systems)}"
    
    ctx.system_name = system_name
    
    # 获取系统 Token
    phone = ctx.user_phone or "unknown"
    token_result = await shengsuan_get_system_token(phone, system_name)
    ctx.system_token = token_result["token"]
    ctx.system_token_expires_at = datetime.fromisoformat(token_result["expires_at"])
    
    # 加载 API 注册表
    api_registry = await shengsuan_get_api_registry(ctx.system_token)
    ctx.api_registry = api_registry
    
    return f"""✅ 已切换到 **{system_name}**
   
🔑 Token 已获取（有效期至 {ctx.system_token_expires_at.strftime('%Y-%m-%d %H:%M')}）
📚 已加载 {len(api_registry.get('apis', []))} 个 API 接口

现在可以开始查询数据了，例如：
- "给我看上个月的销售趋势"
- "生成上周的订单统计报表"
"""


async def cmd_my_tasks(ctx: SessionContext) -> str:
    """查看定时任务"""
    # TODO: 实际从飞书 cron 或胜算系统获取任务列表
    return "📅 **我的定时任务**\n\n暂无任务。使用 `每天上午 9 点推送销售日报` 来创建一个！"


async def cmd_cancel_task(ctx: SessionContext, task_id: str) -> str:
    """取消定时任务"""
    # TODO: 实际调用取消接口
    return f"✅ 任务 {task_id} 已取消"


def cmd_help() -> str:
    """显示帮助信息"""
    return f"""🦞 **{SKILL_NAME} v{VERSION}**

📋 **可用命令：**
- `/金灯塔胜算 初始化` - 执行初始化（飞书授权 + 系统选择）
- `/金灯塔胜算 系统列表` - 查看支持的业务系统
- `/金灯塔胜算 切换系统 <系统名>` - 切换业务系统
- `/金灯塔胜算 我的任务` - 查看定时任务
- `/金灯塔胜算 取消任务 <ID>` - 取消任务
- `/金灯塔胜算 帮助` - 显示此帮助

💬 **自然语言示例：**
- "给我看上个月各渠道的销售额趋势"
- "生成上周订单量的日报表"
- "每天上午 9 点推送昨天的销售数据"
- "把这个报表发布到胜算平台"

🔧 **配置说明：**
请在 main.py 中设置以下配置后才能正常使用：
- FEISHU_APP_ID（飞书应用 App ID）
- FEISHU_APP_SECRET（飞书应用 App Secret）
- FEISHU_REDIRECT_URI（OAuth 回调地址）
- SHENGSAUN_BASE_URL（胜算系统 API 地址）

📚 **详细文档：** 查看 SKILL.md
"""


async def handle_natural_language(ctx: SessionContext, user_input: str) -> str:
    """处理自然语言查询"""
    if not ctx.oauth_completed:
        return "⚠️ 尚未完成飞书授权，请先执行 `/金灯塔胜算 初始化`"
    
    if not ctx.system_name:
        return "⚠️ 尚未选择系统，请先执行 `/金灯塔胜算 系统列表` 查看可用系统，然后执行 `/金灯塔胜算 切换系统 <系统名>`"
    
    # 意图识别
    intent = parse_intent(user_input, ctx.api_registry)
    
    if not intent["matched_api"]:
        return f"❌ 未能理解您的需求：'{user_input}'\n\n请尝试更明确的描述，例如：\n- '查看上个月的销售趋势'\n- '生成上周的订单统计'"
    
    # 确认查询条件
    api_def = intent["matched_api"]
    params = intent["params"]
    
    confirm_msg = f"""🔍 **准备查询：**

📊 接口：{api_def['name']}
📝 参数：{json.dumps(params, ensure_ascii=False, indent=2)}

回复"确认"执行查询，或补充/修改参数。"""
    
    # TODO: 实际应该等待用户确认后再执行
    # 这里为了演示直接执行
    return await execute_query(ctx, api_def, params)


async def execute_query(ctx: SessionContext, api_def: Dict, params: Dict) -> str:
    """执行 API 查询并生成报表"""
    # 检查并刷新系统 Token
    if not ctx.is_system_token_valid():
        phone = ctx.user_phone or "unknown"
        token_result = await shengsuan_get_system_token(phone, ctx.system_name or "unknown")
        ctx.system_token = token_result["token"]
        ctx.system_token_expires_at = datetime.fromisoformat(token_result["expires_at"])
    
    # 调用 API
    data = await shengsuan_call_api(ctx.system_token, api_def, params)
    
    if isinstance(data, dict) and "error" in data:
        return f"❌ API 调用失败：{data['error']}"
    
    # 生成报表
    time_range = f"{params.get('start_date', 'N/A')} ~ {params.get('end_date', 'N/A')}"
    
    # 根据数据类型转换格式
    if isinstance(data, list):
        chart_data = data
        table_data = data
        summary = f"共 {len(data)} 条记录。最高值：{max(item['value'] for item in data):,}，最低值：{min(item['value'] for item in data):,}"
        suggestions = ["建议关注波动较大的日期", "可进一步按渠道/产品维度分析"]
        chart_type = "line"
    else:
        chart_data = [{"date": "总计", "value": data.get("total_amount", 0)}]
        table_data = data.get("details", [])
        summary = f"总订单数：{data.get('total_orders', 0):,}，总金额：{data.get('total_amount', 0):,}"
        suggestions = ["线上渠道占比更高，建议继续加大投入", "线下渠道有增长空间"]
        chart_type = "bar"
    
    html_content = generate_html_report(
        system_name=ctx.system_name or "未知系统",
        report_name=api_def["name"],
        time_range=time_range,
        chart_type=chart_type,
        chart_data=chart_data,
        table_data=table_data,
        summary=summary,
        suggestions=suggestions,
        oss_static_domain=ctx.oss_static_domain
    )
    
    # 上传 OSS
    filename = f"{ctx.system_name}_{api_def['name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    upload_result = await oss_upload(html_content, filename)
    
    if not upload_result.get("success"):
        return f"❌ OSS 上传失败：{upload_result.get('message', 'Unknown error')}"
    
    ctx.last_report_url = upload_result["preview_url"]
    
    return f"""📊 **{api_def['name']}**

🔗 预览地址：{upload_result['preview_url']}

📝 总结与建议：
{summary}
{''.join(f"- {s}" for s in suggestions)}

⏱ 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---
💡 您可以：
- 回复"发布"将此报表发布到胜算平台
- 回复"每天上午 9 点推送"设置定时任务
- 继续提出新的查询需求"""


# ==================== 飞书回调处理（Webhook 入口） ====================

async def handle_feishu_callback(code: str, state: str) -> str:
    """
    处理飞书 OAuth 回调
    
    这是飞书重定向回你的服务器时调用的函数
    需要部署在能接收 HTTP 请求的服务器上
    """
    # 用 code 换取 access_token
    result = await feishu_exchange_code(code, state)
    
    if not result.get("success"):
        return f"❌ 授权失败：{result.get('error')}"
    
    # 获取用户手机号
    phone_result = await feishu_get_user_phone(result["access_token"])
    
    if not phone_result.get("success"):
        return f"❌ 获取手机号失败：{phone_result.get('error')}"
    
    phone = phone_result["phone"]
    
    return f"""✅ **授权成功！**

📞 已获取手机号：{phone}
🎯 接下来请选择业务系统：

`/金灯塔胜算 系统列表`
"""


# ==================== 入口函数 ====================

async def main(user_input: str) -> str:
    """
    主入口函数
    
    Args:
        user_input: 用户输入的命令或自然语言
    
    Returns:
        机器人的回复文本
    """
    # 解析命令
    if user_input.startswith("/金灯塔胜算"):
        parts = user_input.split(maxsplit=2)
        command = parts[1] if len(parts) > 1 else "帮助"
        args = parts[2].split() if len(parts) > 2 else []
        return await handle_command(command, args, user_input)
    elif user_input.lower() in ["已授权", "授权完成", "ok"]:
        # 用户回复"已授权"，提示需要 code
        ctx = get_context()
        if ctx.oauth_completed:
            return "✅ 您已完成授权！\n\n接下来：`/金灯塔胜算 系统列表`"
        else:
            return "ℹ️ 授权回调需要通过飞书开放平台的回调 URL 自动处理。\n\n如果您已点击授权链接并完成授权，系统应自动识别。\n\n如未识别，请重新执行 `/金灯塔胜算 初始化`"
    else:
        # 自然语言处理
        return await handle_natural_language(get_context(), user_input)


# 如果是直接运行此文件（测试用）
if __name__ == "__main__":
    import asyncio
    
    async def test():
        print("🦞 金灯塔胜算 Skill 测试模式（完整版）\n")
        print("="*60)
        print("⚠️ 注意：当前为演示模式，所有 API 返回均为模拟数据")
        print("   要使用真实功能，请在 main.py 中配置：")
        print(f"   - FEISHU_APP_ID: {FEISHU_APP_ID}")
        print(f"   - FEISHU_REDIRECT_URI: {FEISHU_REDIRECT_URI}")
        print(f"   - SHENGSAUN_BASE_URL: {SHENGSAUN_BASE_URL}")
        print("="*60)
        print()
        
        # 测试初始化
        print("【测试】初始化流程")
        print("-"*40)
        result = await main("/金灯塔胜算 初始化")
        print(result)
        print("\n" + "="*60 + "\n")
        
        # 模拟用户已完成授权（测试用）
        ctx = get_context()
        ctx.oauth_completed = True
        ctx.user_phone = "13812345678"
        
        # 测试系统列表
        print("【测试】系统列表")
        print("-"*40)
        result = await main("/金灯塔胜算 系统列表")
        print(result)
        print("\n" + "="*60 + "\n")
        
        # 测试切换系统
        print("【测试】切换系统")
        print("-"*40)
        result = await main("/金灯塔胜算 切换系统 销售系统")
        print(result)
        print("\n" + "="*60 + "\n")
        
        # 测试自然语言查询
        print("【测试】自然语言查询")
        print("-"*40)
        result = await main("给我看上个月的销售趋势")
        print(result)
    
    asyncio.run(test())
