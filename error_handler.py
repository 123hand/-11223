# error_handler.py - 错误处理和恢复模块
import logging
import time
import threading
from typing import Callable, Optional, Any
from config import ENABLE_AUTO_RECOVERY, RECOVERY_MAX_ATTEMPTS, RECOVERY_INTERVAL

class ErrorHandler:
    """错误处理器 - 提供统一的错误处理和恢复机制"""
    
    def __init__(self):
        self.recovery_attempts = {}
        self.recovery_callbacks = {}
        self.lock = threading.Lock()
    
    def register_recovery_callback(self, component_name: str, callback: Callable[[], bool]):
        """注册组件恢复回调函数"""
        with self.lock:
            self.recovery_callbacks[component_name] = callback
            self.recovery_attempts[component_name] = 0
        logging.info(f"已注册组件 {component_name} 的恢复回调")
    
    def handle_error(self, component_name: str, error: Exception, context: str = "") -> bool:
        """处理组件错误"""
        logging.error(f"组件 {component_name} 发生错误: {error} (上下文: {context})")
        
        if not ENABLE_AUTO_RECOVERY:
            logging.warning("自动恢复已禁用，跳过恢复尝试")
            return False
        
        return self._attempt_recovery(component_name)
    
    def _attempt_recovery(self, component_name: str) -> bool:
        """尝试恢复组件"""
        with self.lock:
            if component_name not in self.recovery_callbacks:
                logging.warning(f"组件 {component_name} 没有注册恢复回调")
                return False
            
            attempts = self.recovery_attempts[component_name]
            if attempts >= RECOVERY_MAX_ATTEMPTS:
                logging.error(f"组件 {component_name} 已达到最大恢复尝试次数 ({RECOVERY_MAX_ATTEMPTS})")
                return False
            
            self.recovery_attempts[component_name] = attempts + 1
        
        logging.info(f"尝试恢复组件 {component_name} (第 {attempts + 1} 次)")
        
        try:
            callback = self.recovery_callbacks[component_name]
            success = callback()
            
            if success:
                logging.info(f"组件 {component_name} 恢复成功")
                with self.lock:
                    self.recovery_attempts[component_name] = 0  # 重置尝试次数
                return True
            else:
                logging.warning(f"组件 {component_name} 恢复失败")
                time.sleep(RECOVERY_INTERVAL)
                return False
                
        except Exception as e:
            logging.error(f"组件 {component_name} 恢复过程中发生异常: {e}")
            time.sleep(RECOVERY_INTERVAL)
            return False
    
    def reset_attempts(self, component_name: str):
        """重置组件的恢复尝试次数"""
        with self.lock:
            if component_name in self.recovery_attempts:
                self.recovery_attempts[component_name] = 0
                logging.info(f"已重置组件 {component_name} 的恢复尝试次数")
    
    def get_attempts(self, component_name: str) -> int:
        """获取组件的恢复尝试次数"""
        with self.lock:
            return self.recovery_attempts.get(component_name, 0)

class ComponentHealthMonitor:
    """组件健康监控器"""
    
    def __init__(self, error_handler: ErrorHandler):
        self.error_handler = error_handler
        self.health_status = {}
        self.monitoring = False
        self.monitor_thread = None
        self.stop_event = threading.Event()
    
    def start_monitoring(self):
        """开始监控"""
        if self.monitoring:
            logging.warning("监控已在运行中")
            return
        
        self.monitoring = True
        self.stop_event.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logging.info("组件健康监控已启动")
    
    def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False
        self.stop_event.set()
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        logging.info("组件健康监控已停止")
    
    def register_component(self, name: str, health_check: Callable[[], bool]):
        """注册组件健康检查"""
        self.health_status[name] = {
            'health_check': health_check,
            'last_check': time.time(),
            'is_healthy': True
        }
        logging.info(f"已注册组件 {name} 的健康检查")
    
    def _monitor_loop(self):
        """监控循环"""
        while not self.stop_event.is_set():
            try:
                for name, status in self.health_status.items():
                    try:
                        is_healthy = status['health_check']()
                        status['is_healthy'] = is_healthy
                        status['last_check'] = time.time()
                        
                        if not is_healthy:
                            logging.warning(f"组件 {name} 健康检查失败")
                            self.error_handler.handle_error(name, Exception("健康检查失败"), "监控检测")
                    except Exception as e:
                        logging.error(f"组件 {name} 健康检查异常: {e}")
                        status['is_healthy'] = False
                        status['last_check'] = time.time()
                
                time.sleep(5)  # 每5秒检查一次
            except Exception as e:
                logging.error(f"监控循环异常: {e}")
                time.sleep(5)
    
    def get_component_status(self, name: str) -> Optional[dict]:
        """获取组件状态"""
        return self.health_status.get(name)
    
    def is_component_healthy(self, name: str) -> bool:
        """检查组件是否健康"""
        status = self.get_component_status(name)
        return status['is_healthy'] if status else False 