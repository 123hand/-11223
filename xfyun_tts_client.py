# xfyun_tts_client.py
import websocket
import datetime
import hashlib
import base64
import hmac
import json
import ssl
from urllib.parse import urlencode, quote_plus
import time
import logging
import pyaudio # 用于播放音频
import threading # 导入 threading 模块，用于 Event
import re
import traceback
import wave
import os
from dateutil.tz import tzlocal

# 注意：这里移除 logging.basicConfig，由 app.py 统一配置

# 定义 WebSocket URL
TTS_HOST = "tts-api.xfyun.cn"
TTS_PATH = "/v2/tts"
TTS_URL = f"wss://{TTS_HOST}{TTS_PATH}"

# 从 config.py 导入 TTS 凭证和配置
try:
    from config import (
        XFYUN_TTS_APPID,
        XFYUN_TTS_API_SECRET,
        XFYUN_TTS_API_KEY,
        XFYUN_TTS_VOICE_NAME,
        XFYUN_TTS_AUE_FORMAT,
        XFYUN_TTS_AUF_RATE
    )
except ImportError:
    logging.error("错误: 无法从 config.py 导入讯飞 TTS 凭证或相关配置。请检查 config.py 文件是否存在且配置正确。")
    # 提供默认值以避免程序崩溃，但实际应用中应确保配置正确
    XFYUN_TTS_APPID = "YOUR_TTS_APPID"
    XFYUN_TTS_API_SECRET = "YOUR_TTS_API_SECRET"
    XFYUN_TTS_API_KEY = "YOUR_TTS_API_KEY"
    XFYUN_TTS_VOICE_NAME = "xiaoyan"
    XFYUN_TTS_AUE_FORMAT = "raw"
    XFYUN_TTS_AUF_RATE = "16000"


class XfyunTTSClient:
    def __init__(self, app_id, api_key, api_secret,
                 voice_name="xiaoyan", aue_format="raw", auf_rate="16000",
                 url=TTS_URL, host=TTS_HOST, path=TTS_PATH,
                 pyaudio_instance=None, # 允许传入 PyAudio 实例
                 # 新增参数，用于和 app.py 中的主线程进行同步
                 tts_current_playing_lock=None): # <-- 这里添加参数
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.voice_name = voice_name
        self.aue_format = aue_format
        self.auf_rate = auf_rate
        self.url = url
        self.host = host
        self.path = path
        self.ws = None
        self.p_audio = pyaudio_instance # 使用传入的 PyAudio 实例
        self.stream = None
        self.audio_buffer = [] # 存储接收到的音频数据
        self.is_connected = False
        self.is_speaking = threading.Event() # 用于标记是否正在播放语音
        self.ws_thread = None
        self.audio_play_thread = None
        self.audio_buffer_lock = threading.Lock() # 保护 audio_buffer
        self.play_stop_event = threading.Event() # 用于停止播放线程
        self.audio_stream_closed = threading.Event() # 新增：标记音频流是否真正关闭
        self.playback_finished_event = threading.Event()

        # 保存传递进来的锁
        self.tts_current_playing_lock = tts_current_playing_lock if tts_current_playing_lock is not None else threading.Lock()

        # 标记 PyAudio 是否由本实例创建，以便在关闭时决定是否 terminate
        self._p_audio_managed_internally = False 
        if self.p_audio is None:
            self.p_audio = pyaudio.PyAudio()
            self._p_audio_managed_internally = True # 标记为内部管理
            logging.info("XfyunTTSClient 内部初始化 PyAudio。")
            
        # TTS 客户端连接 WebSocket（在初始化时尝试连接，保持活跃）
        self.connect() 

        # 启动音频播放线程
        self.audio_play_thread = threading.Thread(target=self._play_audio_from_buffer)
        self.audio_play_thread.daemon = True
        self.audio_play_thread.start()
        logging.info("TTS 客户端初始化完成。") # 移动这个日志到这里，与 ASR 客户端保持一致


    def _create_auth_url(self):
        """
        生成带有鉴权参数的WebSocket连接URL。
        """
        # 请求时间
        now = datetime.datetime.now()
        date = now.strftime("%a, %d %b %Y %H:%M:%S GMT")

        # 拼接签名字符串
        signature_origin = f"host: {self.host}\ndate: {date}\nGET {self.path} HTTP/1.1"
        
        # 进行hmac-sha256加密
        signature_sha = hmac.new(self.api_secret.encode('utf-8'), 
                                 signature_origin.encode('utf-8'), 
                                 digestmod=hashlib.sha256).digest()
        signature_sha = base64.b64encode(signature_sha).decode('utf-8')

        # 拼接授权参数
        authorization_origin = f'api_key="{self.api_key}",algorithm="hmac-sha256",headers="host date request-line",signature="{signature_sha}"'
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode('utf-8')

        # 拼接URL
        v = {
            "host": self.host,
            "date": date,
            "authorization": authorization
        }
        url = self.url + "?" + urlencode(v)
        return url

    def _on_message(self, ws, message):
        """
        处理从WebSocket接收到的消息，将音频数据添加到缓冲区。
        """
        try:
            message_dict = json.loads(message)
            code = message_dict.get("code")
            sid = message_dict.get("sid")
            data = message_dict.get("data")

            if code != 0:
                logging.error(f"TTS 错误，错误码：{code}, sid: {sid}, 错误信息: {message_dict.get('message')}")
                with self.audio_buffer_lock:
                    self.audio_buffer.append(None)
                self.is_speaking.clear()
                return

            if data:
                if data.get("audio"):
                    audio_data = base64.b64decode(data["audio"])
                    with self.audio_buffer_lock:
                        self.audio_buffer.append(audio_data)
                status = data.get("status")
                if status == 2:
                    logging.info("TTS 收到最后一帧音频数据。")
                    with self.audio_buffer_lock:
                        self.audio_buffer.append(None)
            else:
                logging.warning(f"TTS 消息中未包含数据: {message}")
        except json.JSONDecodeError as e:
            logging.error(f"TTS 消息解析失败: {e}, 消息: {message}")
            with self.audio_buffer_lock:
                self.audio_buffer.append(None)
            self.is_speaking.clear()
        except Exception as e:
            logging.error(f"处理 TTS 消息时发生错误: {e}", exc_info=True)
            with self.audio_buffer_lock:
                self.audio_buffer.append(None)
            self.is_speaking.clear()

    def _on_error(self, ws, error):
        """
        处理WebSocket错误。
        """
        logging.error(f"TTS WebSocket 错误: {error}")
        self.is_connected = False
        with self.audio_buffer_lock:
            self.audio_buffer.append(None)
        self.is_speaking.clear()

    def _on_close(self, ws, *args):
        """
        处理WebSocket关闭事件。
        """
        logging.info("TTS WebSocket 连接已关闭。调用堆栈：\n" + ''.join(traceback.format_stack()))
        self.is_connected = False
        # 关闭时，如果还有未播放的数据，也需要触发播放线程停止
        with self.audio_buffer_lock:
            if not self.audio_buffer or self.audio_buffer[-1] is not None:
                self.audio_buffer.append(None) # 添加结束标记，确保播放线程能停止

    def _on_open(self, ws):
        """
        处理WebSocket连接打开事件。
        """
        logging.info("TTS WebSocket 连接已打开。")
        self.is_connected = True
        # 在这里不发送数据，由 synthesize_and_play 方法负责

    def connect(self):
        """
        建立并保持 WebSocket 连接。
        """
        if self.is_connected and self.ws and self.ws.sock and self.ws.sock.connected:
            logging.info("TTS WebSocket 已经连接。")
            return True

        logging.info("正在尝试连接 TTS WebSocket...")
        auth_url = self._create_auth_url()
        self.ws = websocket.WebSocketApp(auth_url,
                                         on_message=self._on_message,
                                         on_error=self._on_error,
                                         on_close=self._on_close,
                                         on_open=self._on_open)
        
        # 启动 WebSocket 线程
        self.ws_thread = threading.Thread(target=lambda: self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}))
        self.ws_thread.daemon = True # 设置为守护线程，随主程序退出而退出
        self.ws_thread.start()

        # 等待连接建立，设置一个超时时间
        timeout = 5 # 秒
        start_time = time.time()
        while not self.is_connected and (time.time() - start_time < timeout):
            time.sleep(0.1)
        
        if self.is_connected:
            logging.info("TTS WebSocket 连接成功。")
            return True
        else:
            logging.error("TTS WebSocket 连接超时或失败。")
            return False

    def _play_audio_from_buffer(self):
        """
        音频播放线程，持续等待音频数据，只有收到None标记才退出。
        """
        logging.info("TTS播放线程启动")
        try:
            if not self.stream or not self.stream.is_active():
                self.stream = self.p_audio.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    output=True,
                    frames_per_buffer=1024
                )
                logging.info("TTS PyAudio 音频输出流已开启 (Rate: 16000, Format: 8)。")
            
            while not self.play_stop_event.is_set():
                with self.audio_buffer_lock:
                    if self.audio_buffer:
                        chunk = self.audio_buffer.pop(0)
                    else:
                        chunk = 'WAIT'
                if chunk == 'WAIT':
                    time.sleep(0.01)
                    continue
                if chunk is None:
                    logging.info("TTS播放线程：收到None标记，退出播放循环")
                    break
                try:
                    self.stream.write(chunk)
                    logging.info(f"TTS播放线程：写入音频块 {len(chunk)} bytes")
                except Exception as e:
                    logging.error(f"TTS音频播放错误: {e}")
                    break
            # 播放完成，关闭音频流
            if self.stream and self.stream.is_active():
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                    self.stream = None
                    logging.info("TTS PyAudio 音频流已关闭（全部数据已写入）。")
                except Exception as e:
                    logging.error(f"TTS关闭音频流错误: {e}")
            self.playback_finished_event.set()
            self.audio_stream_closed.set()
            self.is_speaking.clear()
            logging.info("TTS 播放正常完成")
        except Exception as e:
            logging.error(f"TTS播放线程异常: {e}\n{traceback.format_exc()}")
            self.playback_finished_event.set()
            self.audio_stream_closed.set()
            self.is_speaking.clear()
        finally:
            logging.info("TTS播放线程结束")

    def synthesize_and_play(self, text):
        """
        合成并播放文本，返回播放是否成功。
        支持长文本分段合成和智能重连。
        """
        logging.info(f"开始合成文本: '{text}'")
        self.is_speaking.set()
        self.audio_stream_closed.clear()
        self.playback_finished_event.clear()
        self.tts_current_playing_lock.acquire()
        try:
            with self.audio_buffer_lock:
                self.audio_buffer = []
            
            # 检查播放线程是否还在运行，如果已停止则重新启动
            if not self.audio_play_thread or not self.audio_play_thread.is_alive():
                logging.warning("TTS播放线程已停止，重新启动...")
                self.play_stop_event.clear()
                self.audio_play_thread = threading.Thread(target=self._play_audio_from_buffer)
                self.audio_play_thread.daemon = True
                self.audio_play_thread.start()
                time.sleep(0.5)  # 等待线程启动
            
            # 分段处理长文本
            segments = self._split_long_text(text)
            all_audio_received = True
            
            for i, segment in enumerate(segments):
                logging.info(f"合成第 {i+1}/{len(segments)} 段: '{segment[:50]}...'")
                
                # 确保连接正常
                if not self.is_connected or not self.ws or not self.ws.sock or not self.ws.sock.connected:
                    logging.info("TTS连接异常，重新连接...")
                    if not self.connect():
                        logging.error("TTS 客户端未能连接，无法合成和播放语音。")
                        self.is_speaking.clear()
                        return False
                
                request_data = {
                    "common": {"app_id": self.app_id},
                    "business": {
                        "aue": self.aue_format,
                        "auf": self.auf_rate,
                        "vcn": self.voice_name,
                        "tte": "utf8",
                        "speed": 50,
                        "volume": 50,
                        "pitch": 50
                    },
                    "data": {
                        "status": 2,
                        "text": base64.b64encode(segment.encode('utf-8')).decode('utf-8')
                    }
                }
                
                # 发送请求
                try:
                    self.ws.send(json.dumps(request_data))
                    logging.info(f"TTS 文本合成请求已发送 (第{i+1}段)。")
                except websocket._exceptions.WebSocketConnectionClosedException:
                    logging.error("TTS WebSocket连接已关闭，尝试重连...")
                    if self.connect():
                        self.ws.send(json.dumps(request_data))
                        logging.info(f"TTS重连后文本合成请求已发送 (第{i+1}段)。")
                    else:
                        logging.error("TTS重连失败，无法播报")
                        self.is_speaking.clear()
                        return False
                
                # 等待当前段音频数据接收完成
                segment_timeout = 15  # 每段15秒超时
                start_time = time.time()
                while time.time() - start_time < segment_timeout:
                    # 检查是否收到最后一帧数据
                    with self.audio_buffer_lock:
                        if self.audio_buffer and self.audio_buffer[-1] is None:
                            logging.info(f"第 {i+1} 段音频数据接收完成")
                            break
                    time.sleep(0.1)
                else:
                    logging.warning(f"第 {i+1} 段音频数据接收超时")
                    all_audio_received = False
                    break
            
            # 等待语音播放完毕
            max_retries = 2
            retry_count = 0
            playback_success = False
            
            while retry_count < max_retries:
                try:
                    start_time = time.time()
                    while self.is_speaking.is_set() and (time.time() - start_time) < 60:  # 增加总超时时间
                        time.sleep(0.1)
                    
                    if not self.is_speaking.is_set():
                        logging.info("TTS 播放正常完成")
                        playback_success = True
                        break
                    else:
                        logging.warning(f"TTS 播放超时 (第{retry_count + 1}次)")
                        retry_count += 1
                        if retry_count < max_retries:
                            # 重新发送最后一段请求
                            if self.is_connected and self.ws and self.ws.sock and self.ws.sock.connected:
                                self.ws.send(json.dumps(request_data))
                                continue
                            else:
                                logging.error("TTS连接已断开，无法重试")
                                break
                        else:
                            logging.error("TTS 播放重试次数已达上限，强制结束")
                            break
                except Exception as e:
                    logging.error(f"TTS 播放等待过程中发生错误: {e}")
                    break
            
            if self.is_speaking.is_set():
                logging.warning("TTS 播放最终超时，强制清理状态")
                with self.audio_buffer_lock:
                    self.audio_buffer.append(None)
                self.is_speaking.clear()
                self.close_stream()
                return False
            
            # 返回播放结果
            return playback_success and all_audio_received
                
        except websocket._exceptions.WebSocketConnectionClosedException:
            logging.error("TTS WebSocket 连接已意外关闭，无法发送请求。")
            self.is_connected = False
            self.is_speaking.clear()
            with self.audio_buffer_lock: 
                self.audio_buffer.append(None)
            return False
        except Exception as e:
            logging.error(f"发送 TTS 请求或播放时发生错误: {e}", exc_info=True)
            self.is_speaking.clear()
            with self.audio_buffer_lock: 
                self.audio_buffer.append(None)
            return False
        finally:
            if self.tts_current_playing_lock.locked():
                self.tts_current_playing_lock.release()
    
    def _split_long_text(self, text, max_length=300):
        """
        将长文本分段，避免单次合成过长导致连接超时
        """
        if len(text) <= max_length:
            return [text]
        
        # 按句号、问号、感叹号分段
        sentences = re.split(r'([。！？；])', text)
        segments = []
        current_segment = ""
        
        for i in range(0, len(sentences), 2):
            sentence = sentences[i]
            if i + 1 < len(sentences):
                sentence += sentences[i + 1]  # 加上标点符号
            
            if len(current_segment + sentence) <= max_length:
                current_segment += sentence
            else:
                if current_segment:
                    segments.append(current_segment.strip())
                current_segment = sentence
        
        if current_segment:
            segments.append(current_segment.strip())
        
        return segments if segments else [text]

    def is_playing(self):
        """
        检查当前是否有语音正在播放。
        """
        return self.is_speaking.is_set()

    def close_ws_connection(self): 
        """
        主动关闭WebSocket连接。
        """
        if self.ws:
            try:
                self.ws.close()
                self.is_connected = False
                logging.info("TTS WebSocket 连接已关闭。")
            except Exception as e:
                logging.warning(f"关闭 TTS WebSocket 连接时发生错误: {e}")

    def close_stream(self, reason="手动关闭"):
        """
        关闭 PyAudio 音频流。
        """
        if self.stream:
            try:
                if self.stream.is_active():
                    self.stream.stop_stream()
                self.stream.close()
                logging.info(f"TTS PyAudio 音频流已关闭。关闭原因: {reason}\n调用堆栈：\n{''.join(traceback.format_stack())}")
                self.audio_stream_closed.set()  # 新增：音频流关闭后设置事件
            except Exception as e:
                logging.error(f"关闭 TTS 音频流时发生错误: {e}\n{traceback.format_exc()}")
            self.stream = None

    def close(self): 
        """
        释放所有TTS相关的资源。
        """
        logging.info("正在释放 TTS 客户端资源...")
        self.play_stop_event.set() # 通知播放线程停止
        # 在加入播放线程之前，确保缓冲区有结束标记，防止线程卡死
        with self.audio_buffer_lock:
            if not self.audio_buffer or self.audio_buffer[-1] is not None:
                self.audio_buffer.append(None) # 添加一个结束标志
        
        if self.audio_play_thread and self.audio_play_thread.is_alive():
            self.audio_play_thread.join(timeout=3) # 等待线程停止，给予更长的超时时间
            if self.audio_play_thread.is_alive():
                logging.warning("TTS 音频播放线程未能及时停止。")

        self.close_ws_connection() # 关闭当前 WebSocket 连接 (如果连接还存在)
        self.close_stream() # 关闭音频流
        
        # 只有当 PyAudio 实例是内部创建时才 terminate
        if self._p_audio_managed_internally and self.p_audio:
            try:
                self.p_audio.terminate()
                logging.info("TTS PyAudio 资源已释放。")
            except Exception as e:
                logging.error(f"终止 PyAudio 资源时发生错误: {e}")
        else:
            logging.info("PyAudio 实例由外部管理，不在此处终止。")

        logging.info("TTS 客户端资源释放完毕。")

    def is_connection_healthy(self):
        """
        检查TTS连接是否健康
        """
        return (self.is_connected and 
                self.ws and 
                hasattr(self.ws, 'sock') and 
                self.ws.sock and 
                hasattr(self.ws.sock, 'connected') and 
                self.ws.sock.connected)


# 示例代码（仅供测试 XfyunTTSClient 本身）
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s') # 测试时可以开 DEBUG

    # 注意：这里的凭证请替换为你在 config.py 中配置的真实凭证
    # 在运行此测试前，请确保 config.py 中的 TTS 凭证已正确填写！
    # 否则这里会使用默认的 'YOUR_TTS_APPID' 等占位符，导致认证失败。
    # 为了避免 PyAudio 实例被重复创建和终止，这里可以手动创建一个 PyAudio 实例传入
    p_audio_instance = pyaudio.PyAudio()
    # 创建一个用于测试的 Lock
    test_lock = threading.Lock() 

    client = XfyunTTSClient(
        app_id=XFYUN_TTS_APPID,
        api_key=XFYUN_TTS_API_KEY,
        api_secret=XFYUN_TTS_API_SECRET,
        voice_name=XFYUN_TTS_VOICE_NAME,
        aue_format=XFYUN_TTS_AUE_FORMAT,
        auf_rate=XFYUN_TTS_AUF_RATE,
        pyaudio_instance=p_audio_instance, # 传入外部创建的 PyAudio 实例
        tts_current_playing_lock=test_lock # 传入测试用的锁
    )

    try:
        # 模拟合成并播放一个句子
        text_to_synthesize = "你好，这是一段测试语音。希望你能听到。"
        logging.info(f"第一次合成: {text_to_synthesize}")
        client.synthesize_and_play(text_to_synthesize)
        
        time.sleep(1) # 短暂等待

        text_to_synthesize_2 = "这是一个更长的句子，用于测试连续播放的效果。希望系统能够稳定运行。"
        logging.info(f"第二次合成: {text_to_synthesize_2}")
        client.synthesize_and_play(text_to_synthesize_2)
        
        time.sleep(1)

        text_to_synthesize_3 = "现在我们来测试一下，如果在播放过程中停止，会发生什么。"
        logging.info(f"第三次合成: {text_to_synthesize_3}")
        client.synthesize_and_play(text_to_synthesize_3)
        

    except Exception as e:
        logging.error(f"测试过程中发生异常: {e}", exc_info=True)
    finally:
        logging.info("TTS 测试完成，正在清理资源。")
        client.close() # 调用重命名后的 close 方法
        # 如果 PyAudio 实例是外部传入的，则在外部负责 terminate
        if p_audio_instance:
            try:
                p_audio_instance.terminate()
                logging.info("外部 PyAudio 实例已终止。")
            except Exception as e:
                logging.error(f"终止外部 PyAudio 实例时发生错误: {e}")
        logging.info("TTS 客户端资源已释放。")