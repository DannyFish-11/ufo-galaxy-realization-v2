# Node_06_Filesystem

文件系统管理节点，提供文件读写、目录操作、文件搜索等功能。

## 端口
8006

## 环境变量
- `FS_BASE_PATH`: 根目录（默认 /tmp/galaxy_fs）
- `FS_MAX_FILE_SIZE`: 最大文件大小（默认 100MB）

## API
- `GET /health` - 健康检查
- `GET /status` - 节点状态
- `POST /files/read` - 读取文件
- `POST /files/write` - 写入文件
- `POST /files/delete` - 删除文件
- `GET /files/list` - 列出目录
- `POST /files/move` - 移动文件
