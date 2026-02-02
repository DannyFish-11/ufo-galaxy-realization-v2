import os, shutil, glob, hashlib, mimetypes
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title='Node 06 - Filesystem', version='3.0.0', description='Advanced filesystem operations with security and search')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

ALLOWED_PATHS = os.getenv('ALLOWED_PATHS', '/tmp,/home').split(',')
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', str(100 * 1024 * 1024)))  # 100MB

def is_allowed(path: str) -> bool:
    """检查路径是否在允许的目录中"""
    abs_path = os.path.abspath(path)
    return any(abs_path.startswith(os.path.abspath(p)) for p in ALLOWED_PATHS)

def get_file_info(path: str) -> Dict[str, Any]:
    """获取文件详细信息"""
    stat = os.stat(path)
    return {
        'name': os.path.basename(path),
        'path': path,
        'size': stat.st_size,
        'is_dir': os.path.isdir(path),
        'is_file': os.path.isfile(path),
        'is_symlink': os.path.islink(path),
        'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
        'accessed': datetime.fromtimestamp(stat.st_atime).isoformat(),
        'permissions': oct(stat.st_mode)[-3:],
        'mime_type': mimetypes.guess_type(path)[0] if os.path.isfile(path) else None
    }

def calculate_checksum(path: str, algorithm: str = 'sha256') -> str:
    """计算文件校验和"""
    hash_func = hashlib.new(algorithm)
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_func.update(chunk)
    return hash_func.hexdigest()

class FileRequest(BaseModel):
    path: str
    content: Optional[str] = None
    dest: Optional[str] = None
    encoding: Optional[str] = 'utf-8'

class SearchRequest(BaseModel):
    path: str
    pattern: str = '*'
    recursive: bool = False
    content_search: Optional[str] = None

class PermissionRequest(BaseModel):
    path: str
    mode: str  # e.g., '755', '644'

@app.get('/health')
async def health():
    """健康检查"""
    return {
        'status': 'healthy',
        'node_id': '06',
        'name': 'Filesystem',
        'allowed_paths': ALLOWED_PATHS,
        'max_file_size': MAX_FILE_SIZE
    }

@app.post('/read')
async def read_file(request: FileRequest):
    """读取文件内容"""
    if not is_allowed(request.path):
        raise HTTPException(status_code=403, detail='Path not allowed')
    if not os.path.exists(request.path):
        raise HTTPException(status_code=404, detail='File not found')
    if not os.path.isfile(request.path):
        raise HTTPException(status_code=400, detail='Path is not a file')
    
    try:
        with open(request.path, 'r', encoding=request.encoding) as f:
            content = f.read()
        return {'success': True, 'content': content, 'size': len(content)}
    except UnicodeDecodeError:
        # 如果文本解码失败，返回二进制内容的 base64
        import base64
        with open(request.path, 'rb') as f:
            content = base64.b64encode(f.read()).decode()
        return {'success': True, 'content': content, 'encoding': 'base64', 'size': len(content)}

@app.post('/write')
async def write_file(request: FileRequest):
    """写入文件内容"""
    if not is_allowed(request.path):
        raise HTTPException(status_code=403, detail='Path not allowed')
    
    os.makedirs(os.path.dirname(request.path) or '.', exist_ok=True)
    with open(request.path, 'w', encoding=request.encoding) as f:
        f.write(request.content or '')
    return {'success': True, 'path': request.path, 'size': len(request.content or '')}

@app.post('/append')
async def append_file(request: FileRequest):
    """追加内容到文件"""
    if not is_allowed(request.path):
        raise HTTPException(status_code=403, detail='Path not allowed')
    
    with open(request.path, 'a', encoding=request.encoding) as f:
        f.write(request.content or '')
    return {'success': True, 'path': request.path}

@app.delete('/delete')
async def delete_file(path: str):
    """删除文件或目录"""
    if not is_allowed(path):
        raise HTTPException(status_code=403, detail='Path not allowed')
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail='Path not found')
    
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)
    return {'success': True, 'path': path}

@app.post('/copy')
async def copy_file(request: FileRequest):
    """复制文件或目录"""
    if not is_allowed(request.path) or not is_allowed(request.dest):
        raise HTTPException(status_code=403, detail='Path not allowed')
    
    if os.path.isdir(request.path):
        shutil.copytree(request.path, request.dest)
    else:
        shutil.copy2(request.path, request.dest)
    return {'success': True, 'src': request.path, 'dest': request.dest}

@app.post('/move')
async def move_file(request: FileRequest):
    """移动文件或目录"""
    if not is_allowed(request.path) or not is_allowed(request.dest):
        raise HTTPException(status_code=403, detail='Path not allowed')
    
    shutil.move(request.path, request.dest)
    return {'success': True, 'src': request.path, 'dest': request.dest}

@app.post('/mkdir')
async def make_directory(path: str, parents: bool = True):
    """创建目录"""
    if not is_allowed(path):
        raise HTTPException(status_code=403, detail='Path not allowed')
    
    os.makedirs(path, exist_ok=parents)
    return {'success': True, 'path': path}

@app.get('/list')
async def list_dir(path: str, pattern: str = '*', detailed: bool = False):
    """列出目录内容"""
    if not is_allowed(path):
        raise HTTPException(status_code=403, detail='Path not allowed')
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail='Path not found')
    
    files = glob.glob(os.path.join(path, pattern))
    result = []
    for f in sorted(files):
        if detailed:
            result.append(get_file_info(f))
        else:
            stat = os.stat(f)
            result.append({
                'name': os.path.basename(f),
                'path': f,
                'size': stat.st_size,
                'is_dir': os.path.isdir(f)
            })
    return {'success': True, 'files': result, 'count': len(result)}

@app.post('/search')
async def search_files(request: SearchRequest):
    """搜索文件"""
    if not is_allowed(request.path):
        raise HTTPException(status_code=403, detail='Path not allowed')
    
    results = []
    pattern = request.pattern
    
    if request.recursive:
        search_pattern = os.path.join(request.path, '**', pattern)
        files = glob.glob(search_pattern, recursive=True)
    else:
        search_pattern = os.path.join(request.path, pattern)
        files = glob.glob(search_pattern)
    
    for f in files:
        file_info = get_file_info(f)
        
        # 如果需要内容搜索
        if request.content_search and os.path.isfile(f):
            try:
                with open(f, 'r', encoding='utf-8') as file:
                    if request.content_search in file.read():
                        file_info['matched_content'] = True
                        results.append(file_info)
            except Exception:
                pass
        else:
            results.append(file_info)
    
    return {'success': True, 'results': results, 'count': len(results)}

@app.get('/info')
async def get_info(path: str, checksum: bool = False):
    """获取文件或目录详细信息"""
    if not is_allowed(path):
        raise HTTPException(status_code=403, detail='Path not allowed')
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail='Path not found')
    
    info = get_file_info(path)
    
    if checksum and os.path.isfile(path):
        info['sha256'] = calculate_checksum(path, 'sha256')
        info['md5'] = calculate_checksum(path, 'md5')
    
    return {'success': True, 'info': info}

@app.post('/chmod')
async def change_permissions(request: PermissionRequest):
    """修改文件权限"""
    if not is_allowed(request.path):
        raise HTTPException(status_code=403, detail='Path not allowed')
    if not os.path.exists(request.path):
        raise HTTPException(status_code=404, detail='Path not found')
    
    mode = int(request.mode, 8)  # 八进制转换
    os.chmod(request.path, mode)
    return {'success': True, 'path': request.path, 'mode': request.mode}

@app.get('/disk_usage')
async def get_disk_usage(path: str):
    """获取磁盘使用情况"""
    if not is_allowed(path):
        raise HTTPException(status_code=403, detail='Path not allowed')
    
    usage = shutil.disk_usage(path)
    return {
        'success': True,
        'total': usage.total,
        'used': usage.used,
        'free': usage.free,
        'percent': (usage.used / usage.total) * 100
    }

@app.post('/mcp/call')
async def mcp_call(request: dict):
    """MCP 工具调用接口"""
    tool = request.get('tool', '')
    params = request.get('params', {})
    
    if tool == 'read': return await read_file(FileRequest(**params))
    elif tool == 'write': return await write_file(FileRequest(**params))
    elif tool == 'append': return await append_file(FileRequest(**params))
    elif tool == 'delete': return await delete_file(params.get('path'))
    elif tool == 'copy': return await copy_file(FileRequest(**params))
    elif tool == 'move': return await move_file(FileRequest(**params))
    elif tool == 'mkdir': return await make_directory(params.get('path'), params.get('parents', True))
    elif tool == 'list': return await list_dir(params.get('path'), params.get('pattern', '*'), params.get('detailed', False))
    elif tool == 'search': return await search_files(SearchRequest(**params))
    elif tool == 'info': return await get_info(params.get('path'), params.get('checksum', False))
    elif tool == 'chmod': return await change_permissions(PermissionRequest(**params))
    elif tool == 'disk_usage': return await get_disk_usage(params.get('path'))
    raise HTTPException(status_code=400, detail=f'Unknown tool: {tool}')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8006)
