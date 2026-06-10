#version 300 es

/**
 * 全屏 Quad 顶点着色器
 * 输入：标准化设备坐标 [-1,1]，直接传递到裁剪空间
 * 输出：v_uv — 屏幕 UV [0,1]
 */

in vec2 a_position;
out vec2 v_uv;

void main() {
  v_uv = a_position * 0.5 + 0.5;
  gl_Position = vec4(a_position, 0.0, 1.0);
}
