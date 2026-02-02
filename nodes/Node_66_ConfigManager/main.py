import os, json
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title='Node 66 - ConfigManager', version='2.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

CONFIG_FILE = os.getenv('CONFIG_FILE', '/tmp/galaxy_config.json')
config: Dict[str, Any] = {}

def load_config():
    global config
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)

def save_config():
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

load_config()

class ConfigRequest(BaseModel):
    key: str
    value: Optional[Any] = None

@app.get('/health')
async def health():
    return {'status': 'healthy', 'node_id': '66', 'name': 'ConfigManager', 'config_count': len(config)}

@app.post('/set')
async def set_config(request: ConfigRequest):
    config[request.key] = request.value
    save_config()
    return {'success': True, 'key': request.key, 'value': request.value}

@app.get('/get/{key}')
async def get_config(key: str):
    if key not in config:
        raise HTTPException(status_code=404, detail='Config not found')
    return {'success': True, 'key': key, 'value': config[key]}

@app.get('/all')
async def get_all():
    return {'success': True, 'config': config}

@app.delete('/delete/{key}')
async def delete_config(key: str):
    if key not in config:
        raise HTTPException(status_code=404, detail='Config not found')
    del config[key]
    save_config()
    return {'success': True, 'key': key}

@app.post('/mcp/call')
async def mcp_call(request: dict):
    tool = request.get('tool', '')
    params = request.get('params', {})
    if tool == 'set': return await set_config(ConfigRequest(**params))
    elif tool == 'get': return await get_config(params.get('key'))
    elif tool == 'all': return await get_all()
    elif tool == 'delete': return await delete_config(params.get('key'))
    raise HTTPException(status_code=400, detail=f'Unknown tool: {tool}')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8066)
