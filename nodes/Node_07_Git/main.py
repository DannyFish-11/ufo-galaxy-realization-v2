import os, subprocess, json
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title='Node 07 - Git', version='3.0.0', description='Complete Git operations with branch, tag, log, and diff support')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

class GitRequest(BaseModel):
    repo_path: str
    command: Optional[str] = None
    url: Optional[str] = None
    message: Optional[str] = None
    branch: Optional[str] = None
    tag: Optional[str] = None
    remote: Optional[str] = 'origin'
    files: Optional[List[str]] = None

def run_git(repo_path: str, args: list, timeout: int = 60) -> dict:
    """执行 Git 命令"""
    try:
        if not os.path.exists(repo_path):
            return {'success': False, 'error': f'Repository path does not exist: {repo_path}'}
        
        result = subprocess.run(
            ['git'] + args,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            'success': result.returncode == 0,
            'output': result.stdout.strip(),
            'error': result.stderr.strip(),
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': f'Command timeout after {timeout}s'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

@app.get('/health')
async def health():
    """健康检查"""
    git_version = subprocess.run(['git', '--version'], capture_output=True, text=True)
    return {
        'status': 'healthy',
        'node_id': '07',
        'name': 'Git',
        'git_version': git_version.stdout.strip()
    }

@app.post('/init')
async def init_repo(path: str, bare: bool = False):
    """初始化 Git 仓库"""
    os.makedirs(path, exist_ok=True)
    args = ['init']
    if bare:
        args.append('--bare')
    result = run_git(path, args)
    return result

@app.post('/clone')
async def clone(url: str, path: str, branch: Optional[str] = None, depth: Optional[int] = None):
    """克隆仓库"""
    args = ['clone', url, path]
    if branch:
        args.extend(['-b', branch])
    if depth:
        args.extend(['--depth', str(depth)])
    
    result = subprocess.run(args, capture_output=True, text=True, timeout=300)
    return {
        'success': result.returncode == 0,
        'path': path,
        'output': result.stdout.strip(),
        'error': result.stderr.strip()
    }

@app.post('/status')
async def status(request: GitRequest):
    """获取仓库状态"""
    result = run_git(request.repo_path, ['status', '--porcelain'])
    if result['success']:
        # 解析 porcelain 格式
        lines = result['output'].split('\n') if result['output'] else []
        files = []
        for line in lines:
            if line:
                status_code = line[:2]
                filename = line[3:]
                files.append({'status': status_code, 'file': filename})
        result['files'] = files
    return result

@app.post('/add')
async def add_files(request: GitRequest):
    """添加文件到暂存区"""
    if request.files:
        return run_git(request.repo_path, ['add'] + request.files)
    else:
        return run_git(request.repo_path, ['add', '-A'])

@app.post('/commit')
async def commit(request: GitRequest):
    """提交更改"""
    if not request.message:
        raise HTTPException(status_code=400, detail='message required')
    
    # 先添加所有文件
    if request.files:
        add_result = run_git(request.repo_path, ['add'] + request.files)
    else:
        add_result = run_git(request.repo_path, ['add', '-A'])
    
    if not add_result['success']:
        return add_result
    
    return run_git(request.repo_path, ['commit', '-m', request.message])

@app.post('/push')
async def push(request: GitRequest):
    """推送到远程仓库"""
    args = ['push']
    if request.remote:
        args.append(request.remote)
    if request.branch:
        args.append(request.branch)
    return run_git(request.repo_path, args, timeout=300)

@app.post('/pull')
async def pull(request: GitRequest):
    """从远程仓库拉取"""
    args = ['pull']
    if request.remote:
        args.append(request.remote)
    if request.branch:
        args.append(request.branch)
    return run_git(request.repo_path, args, timeout=300)

@app.post('/fetch')
async def fetch(request: GitRequest):
    """从远程仓库获取"""
    args = ['fetch']
    if request.remote:
        args.append(request.remote)
    return run_git(request.repo_path, args, timeout=300)

@app.post('/branch/list')
async def list_branches(request: GitRequest):
    """列出所有分支"""
    result = run_git(request.repo_path, ['branch', '-a'])
    if result['success']:
        branches = [b.strip().lstrip('* ') for b in result['output'].split('\n') if b.strip()]
        result['branches'] = branches
    return result

@app.post('/branch/create')
async def create_branch(request: GitRequest):
    """创建分支"""
    if not request.branch:
        raise HTTPException(status_code=400, detail='branch name required')
    return run_git(request.repo_path, ['branch', request.branch])

@app.post('/branch/delete')
async def delete_branch(request: GitRequest):
    """删除分支"""
    if not request.branch:
        raise HTTPException(status_code=400, detail='branch name required')
    return run_git(request.repo_path, ['branch', '-d', request.branch])

@app.post('/checkout')
async def checkout(request: GitRequest):
    """切换分支或恢复文件"""
    if not request.branch:
        raise HTTPException(status_code=400, detail='branch name required')
    return run_git(request.repo_path, ['checkout', request.branch])

@app.post('/merge')
async def merge(request: GitRequest):
    """合并分支"""
    if not request.branch:
        raise HTTPException(status_code=400, detail='branch name required')
    return run_git(request.repo_path, ['merge', request.branch])

@app.post('/log')
async def get_log(request: GitRequest, limit: int = 10):
    """获取提交日志"""
    result = run_git(request.repo_path, ['log', f'-{limit}', '--pretty=format:%H|%an|%ae|%ad|%s', '--date=iso'])
    if result['success']:
        commits = []
        for line in result['output'].split('\n'):
            if line:
                parts = line.split('|')
                if len(parts) == 5:
                    commits.append({
                        'hash': parts[0],
                        'author': parts[1],
                        'email': parts[2],
                        'date': parts[3],
                        'message': parts[4]
                    })
        result['commits'] = commits
    return result

@app.post('/diff')
async def get_diff(request: GitRequest, cached: bool = False):
    """获取差异"""
    args = ['diff']
    if cached:
        args.append('--cached')
    if request.files:
        args.extend(request.files)
    return run_git(request.repo_path, args)

@app.post('/tag/list')
async def list_tags(request: GitRequest):
    """列出所有标签"""
    result = run_git(request.repo_path, ['tag', '-l'])
    if result['success']:
        tags = [t.strip() for t in result['output'].split('\n') if t.strip()]
        result['tags'] = tags
    return result

@app.post('/tag/create')
async def create_tag(request: GitRequest):
    """创建标签"""
    if not request.tag:
        raise HTTPException(status_code=400, detail='tag name required')
    args = ['tag', request.tag]
    if request.message:
        args.extend(['-a', '-m', request.message])
    return run_git(request.repo_path, args)

@app.post('/tag/delete')
async def delete_tag(request: GitRequest):
    """删除标签"""
    if not request.tag:
        raise HTTPException(status_code=400, detail='tag name required')
    return run_git(request.repo_path, ['tag', '-d', request.tag])

@app.post('/remote/list')
async def list_remotes(request: GitRequest):
    """列出远程仓库"""
    result = run_git(request.repo_path, ['remote', '-v'])
    if result['success']:
        remotes = {}
        for line in result['output'].split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 2:
                    name, url = parts[0], parts[1]
                    if name not in remotes:
                        remotes[name] = url
        result['remotes'] = remotes
    return result

@app.post('/remote/add')
async def add_remote(request: GitRequest):
    """添加远程仓库"""
    if not request.remote or not request.url:
        raise HTTPException(status_code=400, detail='remote name and url required')
    return run_git(request.repo_path, ['remote', 'add', request.remote, request.url])

@app.post('/stash')
async def stash_changes(request: GitRequest):
    """暂存更改"""
    args = ['stash']
    if request.message:
        args.extend(['save', request.message])
    return run_git(request.repo_path, args)

@app.post('/stash/pop')
async def stash_pop(request: GitRequest):
    """恢复暂存的更改"""
    return run_git(request.repo_path, ['stash', 'pop'])

@app.post('/reset')
async def reset(request: GitRequest, hard: bool = False):
    """重置到指定提交"""
    args = ['reset']
    if hard:
        args.append('--hard')
    if request.branch:
        args.append(request.branch)
    return run_git(request.repo_path, args)

@app.post('/mcp/call')
async def mcp_call(request: dict):
    """MCP 工具调用接口"""
    tool = request.get('tool', '')
    params = request.get('params', {})
    
    if tool == 'init': return await init_repo(params.get('path'), params.get('bare', False))
    elif tool == 'clone': return await clone(params.get('url'), params.get('path'), params.get('branch'), params.get('depth'))
    elif tool == 'status': return await status(GitRequest(**params))
    elif tool == 'add': return await add_files(GitRequest(**params))
    elif tool == 'commit': return await commit(GitRequest(**params))
    elif tool == 'push': return await push(GitRequest(**params))
    elif tool == 'pull': return await pull(GitRequest(**params))
    elif tool == 'fetch': return await fetch(GitRequest(**params))
    elif tool == 'branch_list': return await list_branches(GitRequest(**params))
    elif tool == 'branch_create': return await create_branch(GitRequest(**params))
    elif tool == 'branch_delete': return await delete_branch(GitRequest(**params))
    elif tool == 'checkout': return await checkout(GitRequest(**params))
    elif tool == 'merge': return await merge(GitRequest(**params))
    elif tool == 'log': return await get_log(GitRequest(**params), params.get('limit', 10))
    elif tool == 'diff': return await get_diff(GitRequest(**params), params.get('cached', False))
    elif tool == 'tag_list': return await list_tags(GitRequest(**params))
    elif tool == 'tag_create': return await create_tag(GitRequest(**params))
    elif tool == 'tag_delete': return await delete_tag(GitRequest(**params))
    elif tool == 'remote_list': return await list_remotes(GitRequest(**params))
    elif tool == 'remote_add': return await add_remote(GitRequest(**params))
    elif tool == 'stash': return await stash_changes(GitRequest(**params))
    elif tool == 'stash_pop': return await stash_pop(GitRequest(**params))
    elif tool == 'reset': return await reset(GitRequest(**params), params.get('hard', False))
    raise HTTPException(status_code=400, detail=f'Unknown tool: {tool}')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8007)
