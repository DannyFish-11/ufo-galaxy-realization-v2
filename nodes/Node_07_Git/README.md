# Node_07_Git

Git 版本控制节点，提供仓库初始化、提交、推送、分支管理等 Git 操作。

## 端口
8007

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /init` - 初始化仓库
- `POST /clone` - 克隆仓库
- `POST /status` - 查看 Git 状态
- `POST /add` - 暂存文件
- `POST /commit` - 提交
- `POST /push` - 推送
- `POST /pull` - 拉取
- `POST /branch/list` - 列出分支
