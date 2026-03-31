"""
Galaxy - Route Modules Package
====================================

Groups routes by domain, assembled in core/api_routes.py.

Domain modules (Batch PR-4 structure):
  health.py       — /api/v1/health/*             (统一健康管理)
  diagnostics.py  — /api/v1/concurrency/*, /api/v1/errors/*, /api/v1/discovery/*,
                    /api/v1/security/*, /api/v1/config/*  (系统诊断)
  monitoring.py   — /api/v1/monitoring/*         (监控仪表盘 & 告警)
  devices.py      — /api/v1/devices/*            (设备管理)
  nodes.py        — /api/v1/nodes/*, /api/v1/agent/* (节点 & Agent)
  system.py       — /api/v1/system/*, /api/config (系统状态)
  chat.py         — /api/v1/chat                 (对话接口)
  command.py      — /api/v1/command/*            (命令路由)
  ai.py           — /api/v1/ai/*                 (AI 意图)
  vision.py       — /api/v1/vision/*             (视觉理解)
  tasks.py        — /api/v1/tasks/*              (任务管理)
  projection.py   — /api/v1/projection/*         (运行时状态投影)
  relay.py        — /api/v1/relay/*              (代理转发)
  hybrid.py       — /api/v1/rag/*, /api/v1/mesh/*, /api/v1/hybrid/* (混合执行)
  vault.py        — /api/v1/vault/*              (凭证管理)
  cost.py         — /api/v1/cost/*               (成本追踪)
  channels.py     — /api/v1/channels/*           (渠道插件)
  federation.py   — /api/v1/federation/*         (多实例联邦)

Route aggregation authority:  core/api_routes.py  (CANONICAL_API_ROUTES_AUTHORITY)
Dashboard legacy surface:     dashboard/backend/main.py  (DASHBOARD_LEGACY_SURFACE_AUTHORITY)
"""
