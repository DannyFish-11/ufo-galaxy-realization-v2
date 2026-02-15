"""
书法卷轴式 UI 组件 - ScrollPaperView
实现书法卷轴的展开和收回动画
"""

import logging
from typing import Optional, Callable, Tuple
from dataclasses import dataclass
from enum import Enum
import math

logger = logging.getLogger(__name__)


class ScrollState(Enum):
    """卷轴状态"""
    CLOSED = "closed"  # 完全收起
    OPENING = "opening"  # 正在展开
    OPEN = "open"  # 完全展开
    CLOSING = "closing"  # 正在收回
    PARTIAL = "partial"  # 部分展开


@dataclass
class ScrollConfig:
    """卷轴配置"""
    # 尺寸
    max_width: int = 400  # 最大宽度（像素）
    min_width: int = 0  # 最小宽度
    height: int = 600  # 高度
    
    # 动画
    open_duration: float = 0.4  # 展开动画时长（秒）
    close_duration: float = 0.3  # 收回动画时长（秒）
    damping: float = 0.8  # 阻尼系数（0-1）
    
    # 视觉
    background_color: Tuple[int, int, int, int] = (255, 255, 255, 217)  # RGBA
    edge_blur: int = 10  # 边缘模糊（像素）
    ink_fade: bool = True  # 墨迹渐变效果
    
    # 交互
    swipe_threshold: float = 50.0  # 滑动阈值（像素）
    velocity_threshold: float = 100.0  # 速度阈值（像素/秒）


class ScrollPaperView:
    """书法卷轴视图"""
    
    def __init__(self, config: Optional[ScrollConfig] = None):
        """
        初始化书法卷轴视图
        
        Args:
            config: 卷轴配置
        """
        self.config = config or ScrollConfig()
        self.state = ScrollState.CLOSED
        self.current_width = self.config.min_width
        self.target_width = self.config.min_width
        self.animation_progress = 0.0
        
        # 回调函数
        self.on_state_change: Optional[Callable[[ScrollState], None]] = None
        self.on_width_change: Optional[Callable[[int], None]] = None
        
        logger.info("ScrollPaperView 初始化完成")
    
    def open(self, animated: bool = True):
        """
        展开卷轴
        
        Args:
            animated: 是否使用动画
        """
        if self.state == ScrollState.OPEN:
            return
        
        logger.info("展开卷轴")
        
        self.target_width = self.config.max_width
        
        if animated:
            self.state = ScrollState.OPENING
            self.animation_progress = 0.0
        else:
            self.current_width = self.target_width
            self.state = ScrollState.OPEN
            self._notify_state_change()
    
    def close(self, animated: bool = True):
        """
        收回卷轴
        
        Args:
            animated: 是否使用动画
        """
        if self.state == ScrollState.CLOSED:
            return
        
        logger.info("收回卷轴")
        
        self.target_width = self.config.min_width
        
        if animated:
            self.state = ScrollState.CLOSING
            self.animation_progress = 0.0
        else:
            self.current_width = self.target_width
            self.state = ScrollState.CLOSED
            self._notify_state_change()
    
    def set_width(self, width: int):
        """
        设置宽度（用于手势拖动）
        
        Args:
            width: 目标宽度
        """
        width = max(self.config.min_width, min(width, self.config.max_width))
        
        if width != self.current_width:
            self.current_width = width
            self.target_width = width
            
            # 更新状态
            if width == self.config.min_width:
                self.state = ScrollState.CLOSED
            elif width == self.config.max_width:
                self.state = ScrollState.OPEN
            else:
                self.state = ScrollState.PARTIAL
            
            self._notify_width_change()
            self._notify_state_change()
    
    def update(self, delta_time: float):
        """
        更新动画
        
        Args:
            delta_time: 时间增量（秒）
        """
        if self.state not in [ScrollState.OPENING, ScrollState.CLOSING]:
            return
        
        # 计算动画时长
        duration = (
            self.config.open_duration if self.state == ScrollState.OPENING
            else self.config.close_duration
        )
        
        # 更新进度
        self.animation_progress += delta_time / duration
        
        if self.animation_progress >= 1.0:
            # 动画完成
            self.animation_progress = 1.0
            self.current_width = self.target_width
            self.state = (
                ScrollState.OPEN if self.target_width == self.config.max_width
                else ScrollState.CLOSED
            )
            self._notify_state_change()
        else:
            # 计算当前宽度（使用缓动函数）
            eased_progress = self._ease_out_cubic(self.animation_progress)
            
            # 应用阻尼
            if self.config.damping < 1.0:
                eased_progress = self._apply_damping(eased_progress, self.config.damping)
            
            # 计算宽度
            start_width = (
                self.config.min_width if self.state == ScrollState.OPENING
                else self.config.max_width
            )
            width_delta = self.target_width - start_width
            self.current_width = int(start_width + width_delta * eased_progress)
        
        self._notify_width_change()
    
    def handle_swipe(self, delta_x: float, velocity_x: float):
        """
        处理滑动手势
        
        Args:
            delta_x: X 方向位移（像素）
            velocity_x: X 方向速度（像素/秒）
        """
        # 根据滑动方向和速度决定展开或收回
        if abs(delta_x) > self.config.swipe_threshold or abs(velocity_x) > self.config.velocity_threshold:
            if delta_x < 0:  # 向左滑动 -> 展开
                self.open()
            else:  # 向右滑动 -> 收回
                self.close()
    
    def _ease_out_cubic(self, t: float) -> float:
        """
        三次缓出函数
        
        Args:
            t: 输入值 (0-1)
            
        Returns:
            输出值 (0-1)
        """
        return 1 - math.pow(1 - t, 3)
    
    def _apply_damping(self, progress: float, damping: float) -> float:
        """
        应用阻尼效果
        
        Args:
            progress: 进度 (0-1)
            damping: 阻尼系数 (0-1)
            
        Returns:
            阻尼后的进度
        """
        # 使用弹簧阻尼模型
        omega = 2.0 * math.pi / damping
        return 1 - math.exp(-omega * progress) * math.cos(omega * progress)
    
    def _notify_state_change(self):
        """通知状态变化"""
        if self.on_state_change:
            self.on_state_change(self.state)
    
    def _notify_width_change(self):
        """通知宽度变化"""
        if self.on_width_change:
            self.on_width_change(self.current_width)
    
    def get_ink_fade_alpha(self, x: float) -> float:
        """
        获取墨迹渐变透明度
        
        Args:
            x: X 坐标（0-1，0 为左边缘，1 为右边缘）
            
        Returns:
            透明度 (0-1)
        """
        if not self.config.ink_fade:
            return 1.0
        
        # 使用高斯函数模拟墨迹晕染
        # 左边缘渐变
        if x < 0.1:
            return x / 0.1
        # 右边缘渐变
        elif x > 0.9:
            return (1.0 - x) / 0.1
        else:
            return 1.0
    
    def get_render_data(self) -> dict:
        """
        获取渲染数据
        
        Returns:
            渲染数据字典
        """
        return {
            'state': self.state.value,
            'width': self.current_width,
            'height': self.config.height,
            'background_color': self.config.background_color,
            'edge_blur': self.config.edge_blur,
            'animation_progress': self.animation_progress
        }


class InkBrushAnimation:
    """墨迹动画"""
    
    def __init__(self):
        """初始化墨迹动画"""
        self.particles: list = []
        self.time = 0.0
        
        logger.info("InkBrushAnimation 初始化完成")
    
    def add_stroke(self, start_x: float, start_y: float, end_x: float, end_y: float):
        """
        添加笔画
        
        Args:
            start_x: 起始 X 坐标
            start_y: 起始 Y 坐标
            end_x: 结束 X 坐标
            end_y: 结束 Y 坐标
        """
        # 生成粒子
        num_particles = int(math.sqrt((end_x - start_x)**2 + (end_y - start_y)**2) / 5)
        
        for i in range(num_particles):
            t = i / max(num_particles - 1, 1)
            x = start_x + (end_x - start_x) * t
            y = start_y + (end_y - start_y) * t
            
            # 添加随机偏移（模拟毛笔晕染）
            import random
            offset_x = random.uniform(-2, 2)
            offset_y = random.uniform(-2, 2)
            
            particle = {
                'x': x + offset_x,
                'y': y + offset_y,
                'size': random.uniform(1, 3),
                'alpha': random.uniform(0.3, 0.8),
                'lifetime': random.uniform(0.5, 1.5)
            }
            
            self.particles.append(particle)
    
    def update(self, delta_time: float):
        """
        更新动画
        
        Args:
            delta_time: 时间增量（秒）
        """
        self.time += delta_time
        
        # 更新粒子
        self.particles = [
            p for p in self.particles
            if p['lifetime'] > 0
        ]
        
        for particle in self.particles:
            particle['lifetime'] -= delta_time
            # 淡出效果
            particle['alpha'] *= 0.95
    
    def get_particles(self) -> list:
        """获取粒子列表"""
        return self.particles


class CalligraphyText:
    """书法文本"""
    
    def __init__(self, font_family: str = "思源黑体", font_size: int = 16):
        """
        初始化书法文本
        
        Args:
            font_family: 字体族
            font_size: 字体大小
        """
        self.font_family = font_family
        self.font_size = font_size
        self.vertical = True  # 竖排
        self.right_to_left = True  # 从右到左
        
        logger.info("CalligraphyText 初始化完成")
    
    def layout_text(self, text: str, width: int, height: int) -> list:
        """
        布局文本
        
        Args:
            text: 文本内容
            width: 容器宽度
            height: 容器高度
            
        Returns:
            字符位置列表 [(char, x, y), ...]
        """
        positions = []
        
        if self.vertical:
            # 竖排布局
            line_spacing = self.font_size * 2
            char_spacing = self.font_size * 1.5
            
            current_x = width - line_spacing if self.right_to_left else line_spacing
            current_y = char_spacing
            
            for char in text:
                if char == '\n':
                    # 换列
                    if self.right_to_left:
                        current_x -= line_spacing
                    else:
                        current_x += line_spacing
                    current_y = char_spacing
                else:
                    positions.append((char, current_x, current_y))
                    current_y += char_spacing
                    
                    # 换列
                    if current_y > height - char_spacing:
                        if self.right_to_left:
                            current_x -= line_spacing
                        else:
                            current_x += line_spacing
                        current_y = char_spacing
        else:
            # 横排布局（备用）
            line_spacing = self.font_size * 1.5
            char_spacing = self.font_size
            
            current_x = char_spacing
            current_y = line_spacing
            
            for char in text:
                if char == '\n':
                    current_x = char_spacing
                    current_y += line_spacing
                else:
                    positions.append((char, current_x, current_y))
                    current_x += char_spacing
                    
                    if current_x > width - char_spacing:
                        current_x = char_spacing
                        current_y += line_spacing
        
        return positions


class IslandIndicator:
    """灵动岛指示器"""
    
    def __init__(self, size: int = 60):
        """
        初始化灵动岛指示器
        
        Args:
            size: 指示器大小（像素）
        """
        self.size = size
        self.state = "idle"  # idle, listening, thinking, speaking
        self.animation_phase = 0.0
        
        logger.info("IslandIndicator 初始化完成")
    
    def set_state(self, state: str):
        """
        设置状态
        
        Args:
            state: 状态（idle, listening, thinking, speaking）
        """
        if state != self.state:
            self.state = state
            self.animation_phase = 0.0
            logger.info(f"灵动岛状态: {state}")
    
    def update(self, delta_time: float):
        """
        更新动画
        
        Args:
            delta_time: 时间增量（秒）
        """
        self.animation_phase += delta_time
    
    def get_render_data(self) -> dict:
        """
        获取渲染数据
        
        Returns:
            渲染数据字典
        """
        # 根据状态计算视觉效果
        if self.state == "idle":
            # 静态墨点
            opacity = 0.6
            scale = 1.0
        
        elif self.state == "listening":
            # 呼吸效果
            opacity = 0.6 + 0.2 * math.sin(self.animation_phase * 2 * math.pi)
            scale = 1.0 + 0.1 * math.sin(self.animation_phase * 2 * math.pi)
        
        elif self.state == "thinking":
            # 波动效果
            opacity = 0.7 + 0.3 * abs(math.sin(self.animation_phase * 4 * math.pi))
            scale = 1.0 + 0.15 * abs(math.sin(self.animation_phase * 4 * math.pi))
        
        elif self.state == "speaking":
            # 脉冲效果
            opacity = 0.8
            scale = 1.0 + 0.2 * abs(math.sin(self.animation_phase * 6 * math.pi))
        
        else:
            opacity = 0.6
            scale = 1.0
        
        return {
            'state': self.state,
            'size': int(self.size * scale),
            'opacity': opacity,
            'animation_phase': self.animation_phase
        }
