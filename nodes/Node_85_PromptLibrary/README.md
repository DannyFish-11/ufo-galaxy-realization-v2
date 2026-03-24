# Node_85_PromptLibrary

提示词库服务节点，提供提示词模板的存储、检索、创建与更新管理。

## 端口
8085

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `GET /prompts` - 列出所有提示词
- `GET /prompts/{prompt_id}` - 获取提示词详情
- `POST /prompts` - 新建提示词
- `PUT /prompts/{prompt_id}` - 更新提示词
