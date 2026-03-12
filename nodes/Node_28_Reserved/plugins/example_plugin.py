# Example Plugin for Node_28_PluginManager
PLUGIN_NAME = "ExamplePlugin"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "示例插件：演示插件系统基本用法"

async def execute(params: dict) -> dict:
    message = params.get("message", "Hello from ExamplePlugin!")
    return {"success": True, "result": message, "plugin": PLUGIN_NAME}
