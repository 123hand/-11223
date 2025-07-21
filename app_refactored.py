# app_refactored.py - 重构后的多模态面试评测智能体主程序（仅流式ASR版本）
import time
import json
import logging
import threading
import os
import cv2
import pyaudio
import numpy as np
from datetime import datetime
import queue 
import re
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, List, Any

# 从 config.py 导入配置
from config import (
    # Spark配置
    SPARK_HTTP_API_PASSWORD,
    SPARK_MODEL_VERSION,
    
    # ASR配置
    XFYUN_ASR_APPID,
    XFYUN_ASR_API_SECRET,
    XFYUN_ASR_API_KEY, 
    ASR_FINAL_RESULT_TIMEOUT,
    
    # TTS配置
    XFYUN_TTS_APPID,
    XFYUN_TTS_API_KEY,
    XFYUN_TTS_API_SECRET,
    XFYUN_TTS_VOICE_NAME,
    XFYUN_TTS_AUE_FORMAT,
    XFYUN_TTS_AUF_RATE,
    
    # 视频配置
    CAMERA_INDEX,
    VIDEO_RESOLUTION,
    VIDEO_FPS,
    VIDEO_OUTPUT_DIR,
    
    # 面试配置
    INTERVIEW_TOTAL_QUESTIONS,
    ASR_MAX_FAILURES,
    ASR_TIMEOUT,
    TTS_WAIT_TIMEOUT,
    
    # 性能配置
    THREAD_HEALTH_CHECK_INTERVAL,
    
    # 错误处理配置
    ENABLE_AUTO_RECOVERY,
    RECOVERY_MAX_ATTEMPTS,
    RECOVERY_INTERVAL,
    
    # 日志配置
    LOG_LEVEL,
    LOG_FORMAT,
    
    # 音频配置
    AUDIO_INPUT_DEVICE_INDEX
)

# 配置日志
logging.basicConfig(level=getattr(logging, LOG_LEVEL), format=LOG_FORMAT)

# 导入客户端和分析模块
from xfyun_spark_client import SparkClient
from xfyun_tts_client import XfyunTTSClient
from voice_analyzer import VoiceAnalyzer
from error_handler import ErrorHandler, ComponentHealthMonitor
from xfyun_asr_client import XfyunASRClient

class InterviewState(Enum):
    """面试状态枚举"""
    INITIAL = "INITIAL"
    GREETING = "GREETING"
    QUESTIONING = "QUESTIONING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"

@dataclass
class InterviewConfig:
    """面试配置数据类"""
    total_questions: int = INTERVIEW_TOTAL_QUESTIONS
    max_asr_failures: int = ASR_MAX_FAILURES
    asr_timeout: float = ASR_TIMEOUT
    tts_wait_timeout: float = TTS_WAIT_TIMEOUT

class InterviewSession:
    """面试会话管理类 - 仅流式ASR版本"""
    
    def __init__(self):
        """初始化面试会话 - 仅流式ASR版本"""
        self.config = InterviewConfig()
        self.state = InterviewState.INITIAL
        self.question_count = 0
        self.is_running = False
        self.stop_event = threading.Event()
        self.last_ai_reply_time = 0
        self.asr_failure_count = 0
        
        # 初始化各组件
        self.tts_client = XfyunTTSClient(
            app_id=XFYUN_TTS_APPID,
            api_key=XFYUN_TTS_API_KEY,
            api_secret=XFYUN_TTS_API_SECRET
        )
        self.tts_client.connect()
        
        self.spark_client = SparkClient(
            api_password=SPARK_HTTP_API_PASSWORD,
            model_version=SPARK_MODEL_VERSION
        )
        
        self.error_handler = ErrorHandler()
        self.health_monitor = ComponentHealthMonitor(self.error_handler)
        
        # 初始化流式ASR客户端
        self.asr_client = XfyunASRClient(
            app_id=XFYUN_ASR_APPID,
            api_key=XFYUN_ASR_API_KEY,
            api_secret=XFYUN_ASR_API_SECRET
        )
        self.asr_client.connect()
        
        self._register_health_checks()
        logging.info("面试会话初始化完成（仅流式ASR）")
    
    def _register_health_checks(self):
        """注册健康检查"""
        self.health_monitor.register_component("TTS", self._check_tts_health)
        self.health_monitor.register_component("Spark", self._check_spark_health)
        self.health_monitor.register_component("ASR", self._check_asr_health)
        logging.info("健康检查已注册")
    
    def _check_tts_health(self):
        try:
            return self.tts_client is not None
        except:
            return False
    
    def _check_spark_health(self):
        try:
            return self.spark_client is not None
        except:
            return False
    
    def _check_asr_health(self):
        try:
            return self.asr_client is not None
        except:
            return False
    
    def start_interview(self) -> bool:
        """开始面试流程"""
        try:
            logging.info("开始面试...（仅流式ASR版本）")
            if not self.tts_client or not self.spark_client or not self.asr_client:
                logging.error("客户端初始化失败")
                return False
                
            self.health_monitor.start_monitoring()
            self.is_running = True
            self.state = InterviewState.INITIAL
            self.question_count = 0

            # 1. 首轮AI播报欢迎+自我介绍
            greeting = "您好，欢迎参加本次面试。请先进行简单的自我介绍。"
            self._play_ai_reply(greeting, is_greeting=True)
            logging.info("首轮TTS播报完毕，准备进入自我介绍环节")

            while self.is_running and self.state != InterviewState.COMPLETED:
                # 2. TTS播报"请开始回答"
                logging.info("TTS播报提示：请开始回答")
                self._play_tts_only("请开始回答")
                
                # 3. 启动流式ASR，等待用户回答
                logging.info("TTS播报完毕，启动流式ASR，等待用户回答")
                user_text = self._start_streaming_asr()
                
                if not user_text or not user_text.strip():
                    logging.warning("未检测到有效语音，重试本轮...")
                    continue
                
                logging.info(f"用户回答: {user_text}")
                
                # 4. 生成AI回复
                ai_reply = self._generate_ai_reply(user_text)
                if ai_reply:
                    self._play_ai_reply(ai_reply)
                
                # 5. 更新面试状态
                self._update_interview_state()
                
                if self.state == InterviewState.COMPLETED:
                    logging.info("面试流程完成")
                    break
            
            return True
            
        except Exception as e:
            logging.error(f"面试流程异常: {e}", exc_info=True)
            return False
    
    def _play_tts_only(self, text: str):
        """仅播放TTS，不生成AI回复"""
        try:
            logging.info(f"TTS播报: {text}")
            
            # 确保TTS连接正常
            if not self.tts_client.is_connection_healthy():
                logging.info("TTS连接异常，重新连接...")
                self.tts_client.connect()
                if not self.tts_client.is_connection_healthy():
                    logging.error("TTS重连失败")
                    return False
            
            # 播放TTS并检查返回值
            success = self.tts_client.synthesize_and_play(text)
            
            if success:
                logging.info("TTS播报完成")
                return True
            else:
                logging.error("TTS播报失败")
                return False
            
        except Exception as e:
            logging.error(f"TTS播报异常: {e}", exc_info=True)
            return False
    
    def _play_ai_reply(self, ai_reply: str, is_greeting: bool = False):
        """播放AI回复"""
        try:
            logging.info(f"播放AI回复: {ai_reply}")
            
            # 确保TTS客户端已初始化
            if not hasattr(self, 'tts_client') or self.tts_client is None:
                logging.error("TTS客户端未初始化")
                return False
            
            # 直接播放完整文本，不分段
            success = self.tts_client.synthesize_and_play(ai_reply)
            
            if success:
                logging.info("AI回复播放完成")
                return True
            else:
                logging.error("AI回复播放失败")
                return False
                
        except Exception as e:
            logging.error(f"播放AI回复时发生错误: {e}")
            return False
    
    def _start_streaming_asr(self, max_seconds=60):
        """启动流式ASR，等待用户回答"""
        try:
            # 确保TTS完全结束
            if hasattr(self.tts_client, 'playback_finished_event'):
                self.tts_client.playback_finished_event.wait(timeout=3)
            if hasattr(self.tts_client, 'audio_stream_closed'):
                self.tts_client.audio_stream_closed.wait(timeout=3)
            
            # 额外等待确保TTS完全结束
            time.sleep(2)
            
            print("请开始答题，系统正在监听...")
            
            # 强制重新连接ASR，确保连接状态正常
            logging.info("准备启动ASR，检查连接状态...")
            if not self.asr_client.is_connected:
                logging.info("ASR连接断开，重新连接...")
                self.asr_client.connect()
                if not self.asr_client.is_connected:
                    logging.error("ASR重连失败")
                    return None
            else:
                logging.info("ASR连接正常")
            
            # 音频配置
            CHUNK = 640  # 40ms一帧
            FORMAT = pyaudio.paInt16
            CHANNELS = 1
            RATE = 16000
            SILENCE_THRESHOLD = 300
            SILENCE_SECONDS = 2
            
            # 初始化音频输入
            audio = pyaudio.PyAudio()
            stream = audio.open(
                format=FORMAT, 
                channels=CHANNELS, 
                rate=RATE, 
                input=True, 
                frames_per_buffer=CHUNK, 
                input_device_index=AUDIO_INPUT_DEVICE_INDEX
            )
            
            # 重置ASR客户端状态
            self.asr_client.final_result_received_event.clear()
            
            # 发送ASR起始帧
            self.asr_client.send_audio(b'', status=0)
            
            silence_count = 0
            start_time = time.time()
            has_speech = False  # 标记是否有语音输入
            
            # 开始录音并发送到ASR
            for i in range(0, int(RATE / CHUNK * max_seconds)):
                data = stream.read(CHUNK)
                audio_data = np.frombuffer(data, dtype=np.int16)
                
                # 检测是否有语音
                if np.abs(audio_data).mean() > SILENCE_THRESHOLD:
                    has_speech = True
                
                # 发送音频帧到ASR
                self.asr_client.send_audio(data, status=1)
                
                # 检测静音
                if np.abs(audio_data).mean() < SILENCE_THRESHOLD:
                    silence_count += 1
                else:
                    silence_count = 0
                
                # 静音超时或达到最大时间，停止录音
                if silence_count > (SILENCE_SECONDS * RATE / CHUNK) and has_speech:
                    print(f"检测到静音{SILENCE_SECONDS}秒，自动停止录音。")
                    break
                
                # 检查是否已经收到最终结果
                if self.asr_client.final_result_received_event.is_set():
                    break
                
                # 检查是否超时
                if time.time() - start_time > max_seconds:
                    print(f"录音时间达到{max_seconds}秒，自动停止。")
                    break
            
            # 发送ASR结束帧
            self.asr_client.send_end_frame()
            
            # 关闭音频流
            stream.stop_stream()
            stream.close()
            audio.terminate()
            
            # 等待ASR最终结果
            result = self.asr_client.get_final_result()
            
            if result and result.strip():
                logging.info(f"ASR识别结果: {result}")
                return result
            else:
                if not has_speech:
                    logging.warning("未检测到语音输入")
                else:
                    logging.warning("ASR未检测到有效语音")
                return None
                
        except Exception as e:
            logging.error(f"流式ASR异常: {e}", exc_info=True)
            return None
    
    def _update_interview_state(self):
        """更新面试状态"""
        if self.state == InterviewState.INITIAL:
            # 自我介绍完成，进入问题阶段
            self.state = InterviewState.QUESTIONING
            self.question_count = 1
            logging.info("面试状态更新：INITIAL -> QUESTIONING，问题计数：1")
        elif self.state == InterviewState.QUESTIONING:
            # 问题回答完成，进入下一个问题
            self.question_count += 1
            logging.info(f"面试状态更新：问题计数 {self.question_count-1} -> {self.question_count}")
            if self.question_count > self.config.total_questions:
                self.state = InterviewState.COMPLETED
                logging.info("面试流程已结束")
    
    def _generate_ai_reply(self, user_input: str) -> str:
        """生成AI回复"""
        try:
            system_prompt = self._get_system_prompt()
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ]
            
            ai_reply = self.spark_client.send_message(messages)
            if not ai_reply:
                ai_reply = "AI未能生成回复，请稍后重试。"
            
            # 清理AI回复中的markdown格式，避免TTS合成失败
            ai_reply = self._clean_ai_reply_for_tts(ai_reply)
            
            logging.info(f"AI回复: {ai_reply}")
            return ai_reply
            
        except Exception as e:
            logging.error(f"生成AI回复异常: {e}", exc_info=True)
            return "AI生成回复失败，请联系管理员。"
    
    def _clean_ai_reply_for_tts(self, text: str) -> str:
        """清理AI回复文本，移除markdown格式，确保TTS能正常合成"""
        import re
        
        # 移除markdown格式标记
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # 移除粗体标记
        text = re.sub(r'\*(.*?)\*', r'\1', text)      # 移除斜体标记
        text = re.sub(r'`(.*?)`', r'\1', text)        # 移除代码标记
        text = re.sub(r'#+\s*', '', text)             # 移除标题标记
        text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)  # 移除链接标记
        
        # 清理多余的空白字符
        text = re.sub(r'\n\s*\n', '\n', text)  # 移除多余的空行
        text = re.sub(r' +', ' ', text)        # 多个空格替换为单个
        text = text.strip()
        
        # 如果文本过长，截断到合理长度（讯飞TTS有长度限制）
        if len(text) > 1000:
            text = text[:1000] + "..."
            logging.warning("AI回复文本过长，已截断")
        
        return text
    
    def _get_system_prompt(self) -> str:
        """获取系统提示词"""
        prompts = {
            InterviewState.INITIAL: "你现在是一个专业的AI面试官。用户进行了自我介绍，请你简要评价该自我介绍，并提出第一个面试问题：'请您详细介绍一下您在某个项目中使用Python进行数据分析的经验，包括您使用的库、遇到的挑战以及如何解决的。'",
            InterviewState.QUESTIONING: {
                1: "用户回答了第一个问题。请你简要评价该回答，并提出第二个问题：'您对人工智能的未来发展有什么看法？您认为它将如何改变我们的生活和工作方式？'",
                2: "用户回答了第二个问题。请你简要评价该回答，并提出第三个问题：'请描述一次您在团队项目中遇到的冲突，您是如何处理这次冲突的？从中您学到了什么？'",
                3: "用户回答了第三个问题。请你简要评价该回答，并告知面试结束，表示感谢和祝愿。"
            }
        }
        
        if self.state == InterviewState.INITIAL:
            return prompts[InterviewState.INITIAL]
        elif self.state == InterviewState.QUESTIONING:
            return prompts[InterviewState.QUESTIONING].get(self.question_count, "面试已结束，感谢您的参与。")
        else:
            return "面试已结束。"

    def cleanup(self):
        """清理资源"""
        logging.info("开始清理资源")
        self.stop_event.set()
        self.is_running = False
        self.health_monitor.stop_monitoring()
        time.sleep(2)
        
        if self.tts_client:
            if hasattr(self.tts_client, 'is_playing') and callable(self.tts_client.is_playing):
                wait_count = 0
                while self.tts_client.is_playing() and wait_count < 100:
                    logging.info("等待TTS最后一次播报完成...")
                    time.sleep(0.1)
                    wait_count += 1
            if hasattr(self.tts_client, 'audio_stream_closed'):
                self.tts_client.audio_stream_closed.wait(timeout=3)
            self.tts_client.close()
            
        if self.asr_client:
            self.asr_client.close()
            
        logging.info("资源清理完成")

def main():
    """主函数"""
    logging.info("多模态面试评测智能体启动（仅流式ASR版本）")
    
    # 创建面试会话
    session = InterviewSession()
    
    try:
        # 开始面试
        success = session.start_interview()
        if success:
            # 等待面试流程真正结束
            while session.is_running:
                time.sleep(1)
            logging.info("面试流程正常结束")
        else:
            logging.error("面试流程异常结束")
    except KeyboardInterrupt:
        logging.info("收到中断信号，正在退出...")
    except Exception as e:
        logging.error(f"程序运行异常: {e}", exc_info=True)
    finally:
        session.cleanup()
        logging.info("程序退出")

if __name__ == "__main__":
    main() 