"""
UFO Galaxy - 统一鉴权模块
========================

提供 API Token 和 Device ID 鉴权机制。

Author: Copilot
Date: 2026-02-12
"""

import os
import logging
from typing import Optional
from fastapi import Header, HTTPException, status

logger = logging.getLogger("UFO-Galaxy.Auth")


def verify_api_token(token: str) -> bool:
    """
    验证 API Token
    
    Args:
        token: API Token 字符串
        
    Returns:
        bool: Token 是否有效
    """
    # 从环境变量读取 token
    expected_token = os.getenv("UFO_API_TOKEN")
    
    # 如果未设置环境变量，跳过鉴权（开发模式）
    if not expected_token:
        logger.debug("UFO_API_TOKEN 未设置，跳过 Token 鉴权（开发模式）")
        return True
    
    # 验证 token
    is_valid = token == expected_token
    if not is_valid:
        logger.warning(f"无效的 API Token")
    
    return is_valid


def verify_device_id(device_id: str) -> bool:
    """
    验证 Device ID
    
    Args:
        device_id: 设备 ID
        
    Returns:
        bool: Device ID 是否有效
    """
    # 基本验证：非空且长度合理
    if not device_id or len(device_id) < 3:
        logger.warning(f"无效的 Device ID: {device_id}")
        return False
    
    # 可以在此处添加更多验证逻辑，如：
    # - 检查设备是否已注册
    # - 检查设备状态
    # - 检查设备权限等
    
    return True


async def require_auth(
    authorization: Optional[str] = Header(None),
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID")
) -> dict:
    """
    FastAPI 依赖函数，用于端点鉴权
    
    Args:
        authorization: Authorization header (Bearer token)
        x_device_id: X-Device-ID header
        
    Returns:
        dict: 包含认证信息的字典
        
    Raises:
        HTTPException: 鉴权失败时抛出 401 异常
    """
    # 从环境变量读取 token
    expected_token = os.getenv("UFO_API_TOKEN")
    
    # 如果未设置环境变量，跳过鉴权（开发模式）
    if not expected_token:
        logger.debug("UFO_API_TOKEN 未设置，跳过鉴权（开发模式）")
        return {
            "authenticated": True,
            "device_id": x_device_id,
            "dev_mode": True
        }
    
    # 验证 Authorization header
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 提取 Bearer token
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = parts[1]
    
    # 验证 token
    if not verify_api_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 验证 device_id（如果提供）
    if x_device_id and not verify_device_id(x_device_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Device ID"
        )
    
    logger.info(f"认证成功: device_id={x_device_id}")
    
    return {
        "authenticated": True,
        "device_id": x_device_id,
        "dev_mode": False
    }
