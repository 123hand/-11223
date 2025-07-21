# xfyun_asr_client.py

import websocket
import datetime
import hashlib
import base64
import hmac
import json
import ssl
from urllib.parse import urlencode, quote_plus
import _thread
import time
import logging
import threading
import numpy as np
import email.utils

# 从 config.py 导入凭证
from config import XFYUN_ASR_APPID, XFYUN_ASR_API_SECRET, XFYUN_ASR_API_KEY, ASR_FINAL_RESULT_TIMEOUT

# 定义 WebSocket URL
ASR_HOST = "iat-api.xfyun.cn"
ASR_PATH = "/v2/iat"
ASR_URL = f"wss://{ASR_HOST}{ASR_PATH}"

class XfyunASRClient:
    def __init__(self, app_id, api_key, api_secret, url=ASR_URL, host=ASR_HOST, path=ASR_PATH):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.url = url
        self.host = host
        self.path = path
        self.ws = None
        self.is_connected = False
        self.callback = None # 最终结果回调
        self.final_result_received_event = threading.Event()
        self.final_result = ""
        self.temp_result = ""
        self.is_receiving_final_result = False
        self.invalid_result_received = False  # 新增：标记是否收到无效结果
        self.last_valid_result = ""  # 新增：保存最后一次有效的中间结果
        self.accumulated_result = ""  # 新增：跨停顿累积识别内容

        self.result_lock = threading.Lock()
        self.interim_result_callback = None # 中间结果回调
        self.session_active = threading.Event()
        
        # 添加语音分段检测相关变量
        self.last_result_time = time.time()
        self.segment_timeout = 1.5  # 减少到1.5秒，更快响应
        self.is_new_segment = False
        
        # 新增：实时处理相关变量
        self.last_interim_update = time.time()
        self.interim_update_interval = 0.3  # 300ms更新一次中间结果
        self.auto_finalize_timeout = 3.0  # 3秒无新内容自动结束
        self.auto_finalize_timer = None
        self.auto_finalize_thread = None

        logging.info("ASR 客户端初始化完成。")

    def _create_auth_url(self):
        now = datetime.datetime.now()
        date = email.utils.formatdate(time.mktime(now.timetuple()), usegmt=True)

        signature_origin = "host: " + self.host + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + self.path + " HTTP/1.1"

        hmac_code = hmac.new(self.api_secret.encode('utf-8'), signature_origin.encode('utf-8'),
                             digestmod=hashlib.sha256).digest()
        signature = base64.b64encode(hmac_code).decode('utf-8')

        authorization_origin = 'api_key="%s", algorithm="%s", headers="%s", signature="%s"' % \
                               (self.api_key, "hmac-sha256", "host date request-line", signature)

        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode('utf-8')

        v = {
            "host": self.host,
            "date": date,
            "authorization": authorization
        }

        auth_params = urlencode(v, quote_via=quote_plus)
        url = self.url + "?" + auth_params
        logging.info(f"Connecting to ASR URL: {url}")
        return url

    def _on_message(self, ws, message):
        """
        处理从WebSocket接收到的消息。
        """
        logging.info(f"收到ASR服务端消息: {message}")
        logging.debug(f"ASR消息长度: {len(message)}, 消息类型: {type(message)}")
        
        try:
            json_message = json.loads(message) # 统一解析一次

            # 调试信息，先打开观察消息结构
            logging.debug(f"Received ASR raw message: {json_message}")

            code = json_message.get("code")
            sid = json_message.get("sid")
            
            logging.debug(f"ASR消息解析: code={code}, sid={sid}")
            
            # --- 检查错误消息 ---
            if code is not None and code != 0: # 如果有错误码且不为0
                error_message = json_message.get("message", "未知错误")
                logging.error(f"ASR 服务器返回错误: Code={code}, Message={error_message}, SID={sid}")
                self.final_result_received_event.set() # 错误时也设置事件，避免阻塞
                self.session_active.clear() # 发生错误也清除会话标记
                
                # 如果有回调，通知错误
                if self.callback:
                    # 构建一个符合 app.py asr_callback 预期的错误字典
                    error_dict = {"action": "error", "code": code, "message": error_message, "sid": sid}
                    self.callback(error_dict, self)
                return # 处理完错误后立即返回

            # --- 处理正常识别结果 ---
            # 只有当消息包含 'data' 字段时，才尝试解析识别结果
            if "data" in json_message:
                data = json_message["data"]
                status = data.get("status")
                
                # 提取识别文本
                result_text = ""
                if "result" in data and "ws" in data["result"]:
                    for w in data["result"]["ws"]:
                        if "cw" in w:
                            for cw_item in w["cw"]:
                                result_text += cw_item.get("w", "")
                
                # 调试信息：显示原始识别结果
                logging.debug(f"ASR status={status}, result_text='{result_text}', SID={sid}")

                with self.result_lock:
                    if status == 0:  # 语音识别开始 (VAD 状态)
                        self.temp_result = ""
                        self.final_result = ""
                        self.session_active.set() # 标记会话激活
                        logging.debug(f"ASR 识别开始 (status=0), SID: {sid}")
                        self.invalid_result_received = False  # 重置无效结果标志
                        self.last_valid_result = ""  # 重置最后一次有效结果
                        # 重置时间戳和分段标志
                        self.last_result_time = time.time()
                        self.is_new_segment = False
                        # 新一轮分段开始时不清空accumulated_result
                    elif status == 1:  # 中间结果
                        # 实时处理中间结果
                        if result_text and result_text.strip():
                            current_time = time.time()
                            
                            # 更新结果
                            self.temp_result = result_text
                            self.accumulated_result = result_text
                            self.last_valid_result = result_text
                            self.last_result_time = current_time
                            
                            # 重置自动结束定时器
                            self._reset_auto_finalize_timer()
                            
                            # 检查是否需要发送中间结果更新
                            if current_time - self.last_interim_update >= self.interim_update_interval:
                                self.last_interim_update = current_time
                                logging.debug(f"更新中间结果: {self.temp_result}")
                                
                                # 如果有中间结果回调，调用它
                                if self.interim_result_callback:
                                    interim_dict = {"action": "partial", "text": self.accumulated_result, "sid": sid}
                                    self.interim_result_callback(interim_dict, self)
                        
                        logging.debug(f"ASR 中间结果: {self.temp_result}, SID: {sid}")
                    elif status == 2:  # 最终结果
                        # 最终结果处理逻辑
                        if result_text and result_text.strip():
                            # 如果最终结果有内容，直接使用
                            self.final_result = result_text
                            logging.info(f"使用最终结果: {self.final_result}")
                        else:
                            # 如果最终结果为空，使用累积的中间结果
                            if self.accumulated_result and self.accumulated_result.strip():
                                self.final_result = self.accumulated_result
                                logging.info(f"使用累积中间结果作为最终结果: {self.final_result}")
                            elif self.temp_result and self.temp_result.strip():
                                self.final_result = self.temp_result
                                logging.info(f"使用当前中间结果作为最终结果: {self.final_result}")
                            else:
                                self.final_result = result_text
                                logging.warning(f"没有有效结果，使用原始结果: {result_text}")
                        
                        # 确保最终结果不为空
                        if not self.final_result or self.final_result.strip() in ["。", ".", "？", "?", ""]:
                            logging.warning("ASR最终结果为空或只有标点符号，尝试使用中间结果")
                            if self.last_valid_result and self.last_valid_result.strip():
                                self.final_result = self.last_valid_result
                                logging.info(f"使用last_valid_result作为最终结果: {self.final_result}")
                            elif self.temp_result and self.temp_result.strip():
                                self.final_result = self.temp_result
                                logging.info(f"使用temp_result作为最终结果: {self.final_result}")
                            else:
                                logging.error("没有可用的中间结果，最终结果为空")
                        
                        # 无论结果如何，都要设置事件，让ASR结果处理线程知道有结果了
                        self.final_result_received_event.set() # 设置事件，通知主程序收到最终结果
                        logging.info(f"ASR 最终结果: {self.final_result}, SID: {sid}")
                        logging.info(f"ASR客户端：final_result_received_event已设置，等待ASR结果处理线程处理")
                        self.is_receiving_final_result = False # 最终结果处理完毕
                        self.session_active.clear() # 标记会话结束

                        # 如果有最终结果回调，调用它
                        if self.callback:
                            # 构建一个符合 app.py asr_callback 预期的最终结果字典
                            final_dict = {"action": "recognized", "type": "final", "text": self.final_result, "sid": sid}
                            logging.info(f"ASR客户端：调用回调函数，结果: {self.final_result}")
                            self.callback(final_dict, self)
                        else:
                            logging.warning("ASR客户端：没有设置回调函数")
                    else:
                        logging.debug(f"ASR 收到未知状态消息 (status={status}): {json_message}")
            else:
                # 如果没有 'data' 字段，但 code 为 0，则可能是连接成功或其他控制消息
                # 这种情况不需要特别处理，或者可以记录一下
                logging.debug(f"ASR message without 'data' field (code=0): {json_message}")

        except json.JSONDecodeError as e:
            logging.error(f"ASR 消息解析失败: {e}, 消息: {message}", exc_info=True)
            # 解析失败也应该尝试解除阻塞
            self.final_result_received_event.set()
            self.session_active.clear()
        except Exception as e:
            logging.critical(f"处理 ASR 消息时发生未知错误: {e}, 消息: {message}", exc_info=True)
            self.final_result_received_event.set() # 发生异常时也设置事件，防止阻塞
            self.session_active.clear() # 发生异常也清除会话标记

    def _on_error(self, ws, error):
        logging.error(f"ASR WebSocket 错误: {error}", exc_info=True)
        print(f"【ASR】WebSocket连接错误: {error}")
        self.is_connected = False
        self.final_result_received_event.set() # 确保在错误时解除阻塞
        self.session_active.clear() # 发生错误也清除会话标记

    def _on_close(self, ws, *args):
        logging.info("ASR WebSocket closed.", exc_info=True)
        self.is_connected = False
        self.session_active.clear() # 连接关闭也清除会话标记

    def _on_open(self, ws):
        logging.info("ASR WebSocket opened.")
        print("【ASR】WebSocket连接已打开")
        self.is_connected = True

    def connect(self):
        """
        连接到 ASR WebSocket 服务器。
        返回 True 表示连接成功，False 表示连接失败。
        """
        if self.is_connected:
            logging.info("ASR 客户端已连接。")
            return True

        try:
            auth_url = self._create_auth_url()
            self.ws = websocket.WebSocketApp(auth_url,
                                             on_message=self._on_message,
                                             on_error=self._on_error,
                                             on_close=self._on_close,
                                             on_open=self._on_open)
            # 在一个新线程中运行 WebSocket 连接，避免阻塞主线程
            _thread.start_new_thread(self.ws.run_forever, (None, None, None, 60, ssl.CERT_NONE))
            logging.info("Waiting for ASR client to connect...")
            # 等待连接建立
            for _ in range(30): # 最多等待 3 秒
                if self.is_connected:
                    logging.info("ASR client connected successfully.")
                    return True
                time.sleep(0.1)
            else:
                logging.error("ASR client failed to connect within timeout.", exc_info=True)
                raise RuntimeError("ASR client failed to connect within timeout.")
        except Exception as e:
            logging.error(f"ASR连接异常: {e}", exc_info=True)
            raise  # 直接抛出异常

    def send_end_frame(self):
        """
        发送ASR结束帧
        """
        self.send_audio(b'', status=2)

    def send_audio(self, audio_data, status=1):
        """
        发送音频数据到 ASR 服务器。
        status: 0-开始，1-音频中，2-结束
        """
        if not self.is_connected:
            logging.warning("ASR 客户端未连接，尝试重新连接...", exc_info=True)
            try:
                self.connect()
                if not self.is_connected:
                    logging.error("ASR 客户端重连失败。", exc_info=True)
                    raise RuntimeError("ASR 客户端重连失败。")
            except Exception as e:
                logging.error(f"ASR 客户端重连时发生错误: {e}", exc_info=True)
                raise

        try:
            # 在发送 status=0 时，重置内部状态和事件
            if status == 0:
                logging.debug("Sent ASR status=0 frame.")
                with self.result_lock:
                    self.final_result = ""
                    self.temp_result = ""
                    self.last_valid_result = ""  # 重置最后一次有效结果
                    self.accumulated_result = "" # 重置累积结果
                self.final_result_received_event.clear() # 清除之前的事件状态
                self.session_active.set() # 标记会话开始
                self.is_receiving_final_result = True # 标记正在等待最终结果
                self.invalid_result_received = False  # 重置无效结果标志

            elif status == 2:
                logging.debug("Sent ASR status=2 frame.")
                # 在这里不清除 session_active，等待最终结果到达后才清除
                # self.session_active.clear() # 标记会话结束

            # 构建发送数据
            data = {
                "common": {"app_id": self.app_id},
                "business": {
                    "language": "zh_cn", 
                    "domain": "iat", 
                    "accent": "mandarin", 
                    "dwa": "wpgs"  # 开启动态修正功能
                },
                "data": {
                    "status": status,
                    "format": "audio/L16;rate=16000",
                    "encoding": "raw",
                    "audio": base64.b64encode(audio_data).decode('utf-8')
                }
            }
            # 增强日志：每帧发送时打印帧长度、status、时间戳
            logging.debug(f"ASR发送音频帧: 长度={len(audio_data)}, status={status}, 时间={time.strftime('%H:%M:%S', time.localtime())}")
            
            # 添加调试信息：检查WebSocket连接状态
            if self.ws and hasattr(self.ws, 'sock') and self.ws.sock:
                if hasattr(self.ws.sock, 'connected') and self.ws.sock.connected:
                    logging.debug(f"ASR WebSocket连接状态正常，准备发送数据")
                else:
                    logging.warning(f"ASR WebSocket连接状态异常: connected={getattr(self.ws.sock, 'connected', 'unknown')}", exc_info=True)
            else:
                logging.warning(f"ASR WebSocket对象异常: ws={self.ws}, sock={getattr(self.ws, 'sock', None)}", exc_info=True)
            
            # 检查WebSocket连接状态并发送数据
            if self.ws and hasattr(self.ws, 'sock') and self.ws.sock and self.ws.sock.connected:
                self.ws.send(json.dumps(data))
                logging.debug(f"ASR数据发送成功，status={status}, 数据长度={len(json.dumps(data))}")
            else:
                logging.warning("ASR WebSocket连接已断开，无法发送音频数据。", exc_info=True)
                self.is_connected = False
                try:
                    self.connect()
                    if self.is_connected and self.ws and hasattr(self.ws, 'sock') and self.ws.sock and self.ws.sock.connected:
                        self.ws.send(json.dumps(data))
                        logging.info("ASR重连成功，音频数据已发送")
                    else:
                        logging.error("ASR重连失败，无法发送音频数据", exc_info=True)
                        raise RuntimeError("ASR重连失败，无法发送音频数据")
                except Exception as e:
                    logging.error(f"ASR重连时发生错误: {e}", exc_info=True)
                    raise
                
        except Exception as e:
            logging.error(f"发送音频数据到ASR服务器时发生错误: {e}", exc_info=True)
            self.is_connected = False
            self.session_active.clear()
            raise

    def get_final_result(self):
        """
        获取最终识别结果。会阻塞直到接收到最终结果或超时。
        """
        # 等待 final_result_received_event 被设置，表示收到了最终结果
        # 设置超时时间，防止长时间阻塞
        if self.final_result_received_event.wait(timeout=ASR_FINAL_RESULT_TIMEOUT):
            with self.result_lock:
                result = self.final_result
                self.final_result = "" # 读取后清空，准备下一次识别
                return result
        else:
            logging.warning(f"ASR 结果处理线程等待最终结果超时 ({ASR_FINAL_RESULT_TIMEOUT}s)。")
            with self.result_lock:
                result = self.final_result # 超时也返回可能有的部分结果
                self.final_result = ""
                return result

    def get_interim_result(self):
        """
        获取中间识别结果。
        """
        with self.result_lock:
            return self.temp_result

    def start_accumulate(self):
        with self.result_lock:
            self.accumulated_result = ""

    def get_accumulated_result(self):
        with self.result_lock:
            return self.accumulated_result.strip()

    def set_final_result(self, result):
        """
        设置最终识别结果。
        """
        with self.result_lock:
            self.final_result = result

    def set_temp_result(self, result):
        """
        设置临时识别结果。
        """
        with self.result_lock:
            self.temp_result = result

    def set_callback(self, callback):
        """
        设置最终结果的回调函数。这个回调函数会接收两个参数：
        (result_dict: dict, asr_client_instance: XfyunASRClient)
        """
        self.callback = callback

    def set_interim_result_callback(self, callback):
        """
        设置中间结果的回调函数。这个回调函数会接收两个参数：
        (result_dict: dict, asr_client_instance: XfyunASRClient)
        """
        self.interim_result_callback = callback

    def close(self):
        """
        关闭WebSocket连接。
        """
        # 取消定时器
        if hasattr(self, 'auto_finalize_timer') and self.auto_finalize_timer:
            self.auto_finalize_timer.cancel()
        
        logging.info("Closing ASR WebSocket...")
        if self.ws and hasattr(self.ws, 'sock') and self.ws.sock and self.ws.sock.connected:
            self.ws.close()
            logging.info("ASR WebSocket closed.")
        self.is_connected = False
        self.session_active.clear() # 清除会话标记
        logging.info("ASR client closed.")

    def _reset_auto_finalize_timer(self):
        """重置自动结束定时器"""
        if hasattr(self, 'auto_finalize_timer') and self.auto_finalize_timer:
            self.auto_finalize_timer.cancel()
        
        self.auto_finalize_timer = threading.Timer(self.auto_finalize_timeout, self._auto_finalize)
        self.auto_finalize_timer.daemon = True
        self.auto_finalize_timer.start()

    def _auto_finalize(self):
        """自动结束当前识别会话"""
        if self.session_active.is_set() and self.accumulated_result.strip():
            logging.info(f"自动结束识别会话，最终结果: {self.accumulated_result}")
            with self.result_lock:
                self.final_result = self.accumulated_result
                self.final_result_received_event.set()
                self.session_active.clear()
            
            # 调用最终结果回调
            if self.callback:
                final_dict = {"action": "recognized", "type": "auto_final", "text": self.final_result}
                self.callback(final_dict, self)

    def _start_auto_finalize_monitor(self):
        """启动自动结束监控线程"""
        def monitor():
            while self.session_active.is_set():
                current_time = time.time()
                if current_time - self.last_result_time > self.auto_finalize_timeout:
                    if self.accumulated_result.strip():
                        self._auto_finalize()
                    break
                time.sleep(0.5)  # 每500ms检查一次
        
        if hasattr(self, 'auto_finalize_thread') and self.auto_finalize_thread and self.auto_finalize_thread.is_alive():
            return
        
        self.auto_finalize_thread = threading.Thread(target=monitor, daemon=True)
        self.auto_finalize_thread.start()