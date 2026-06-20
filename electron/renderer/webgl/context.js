/**
 * WebGL 2.0 上下文管理
 * 负责：初始化 WebGL、创建全屏 Quad、编译 Shader、管理 Program
 */

class WebGLContext {
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = null;
    this.program = null;
    this.vao = null;
    this.uniforms = {};
  }

  // ── 初始化 ──────────────────────────────────────

  async init() {
    // 请求 WebGL 2.0 上下文
    this.gl = this.canvas.getContext('webgl2', {
      alpha: true,
      premultipliedAlpha: false,
      antialias: false,
      preserveDrawingBuffer: false,
    });

    if (!this.gl) {
      throw new Error('WebGL 2.0 not supported');
    }

    // 加载并编译 shader
    const [vertSrc, fragSrc] = await Promise.all([
      this._loadShader('shaders/main.vert'),
      this._loadShader('shaders/lumiv.frag'),
    ]);

    this.program = this._createProgram(vertSrc, fragSrc);
    if (!this.program) {
      throw new Error('Failed to create shader program');
    }

    this.gl.useProgram(this.program);

    // 创建全屏 Quad
    this._createFullscreenQuad();

    // 缓存 uniform locations
    this._cacheUniforms([
      'u_time',
      'u_resolution',
      'u_depth',
      'u_intent',
      'u_speaking',
    ]);

    // 设置 WebGL 状态
    this.gl.enable(this.gl.BLEND);
    this.gl.blendFunc(this.gl.SRC_ALPHA, this.gl.ONE_MINUS_SRC_ALPHA);

    return this;
  }

  // ── Shader 加载 ─────────────────────────────────

  _loadShader(url) {
    return fetch(url).then(r => {
      if (!r.ok) throw new Error(`Failed to load ${url}: ${r.status}`);
      return r.text();
    });
  }

  // ── Shader 编译 ─────────────────────────────────

  _createProgram(vertSrc, fragSrc) {
    const gl = this.gl;

    const vertShader = this._compileShader(gl.VERTEX_SHADER, vertSrc);
    const fragShader = this._compileShader(gl.FRAGMENT_SHADER, fragSrc);
    if (!vertShader || !fragShader) return null;

    const program = gl.createProgram();
    gl.attachShader(program, vertShader);
    gl.attachShader(program, fragShader);
    gl.linkProgram(program);

    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error('Program link error:', gl.getProgramInfoLog(program));
      gl.deleteProgram(program);
      return null;
    }

    gl.deleteShader(vertShader);
    gl.deleteShader(fragShader);

    return program;
  }

  _compileShader(type, source) {
    const gl = this.gl;
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);

    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      console.error(
        `Shader compile error (${type === this.gl.VERTEX_SHADER ? 'vert' : 'frag'}):`,
        gl.getShaderInfoLog(shader)
      );
      gl.deleteShader(shader);
      return null;
    }
    return shader;
  }

  // ── 全屏 Quad ───────────────────────────────────

  _createFullscreenQuad() {
    const gl = this.gl;

    // 两个三角形组成全屏 quad
    // 位置属性：vec2 [-1, 1]
    const positions = new Float32Array([
      -1, -1,  // 左下
       1, -1,  // 右下
      -1,  1,  // 左上
       1,  1,  // 右上
    ]);

    // VAO
    this.vao = gl.createVertexArray();
    gl.bindVertexArray(this.vao);

    // VBO
    const vbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);

    // 属性绑定
    const aPosition = gl.getAttribLocation(this.program, 'a_position');
    gl.enableVertexAttribArray(aPosition);
    gl.vertexAttribPointer(aPosition, 2, gl.FLOAT, false, 0, 0);

    gl.bindVertexArray(null);
  }

  // ── Uniform 管理 ────────────────────────────────

  _cacheUniforms(names) {
    for (const name of names) {
      this.uniforms[name] = this.gl.getUniformLocation(this.program, name);
    }
  }

  setUniform(name, value) {
    const loc = this.uniforms[name];
    if (loc === null || loc === undefined) return;

    const gl = this.gl;
    if (typeof value === 'number') {
      gl.uniform1f(loc, value);
    } else if (value.length === 2) {
      gl.uniform2f(loc, value[0], value[1]);
    }
  }

  // ── 渲染 ────────────────────────────────────────

  render() {
    const gl = this.gl;
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.bindVertexArray(this.vao);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.bindVertexArray(null);
  }

  // 仅清屏（不跑片段着色器）。静默/空闲帧用它代替 render()，避免软件渲染下
  // 每帧跑全屏着色器把 CPU 打满。
  clear() {
    const gl = this.gl;
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }

  // ── 资源释放 ────────────────────────────────────

  destroy() {
    const gl = this.gl;
    if (this.vao) gl.deleteVertexArray(this.vao);
    if (this.program) gl.deleteProgram(this.program);
  }
}

// 导出
if (typeof module !== 'undefined') module.exports = { WebGLContext };
