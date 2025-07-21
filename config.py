# config.py - 重构后的配置文件（仅流式ASR版本）

# --- 讯飞星火大模型 HTTP API 凭证 ---
# 请将 YOUR_SPARK_HTTP_API_PASSWORD 替换为你从讯飞控制台获取的实际 APIPassword
# 注意：这里只需要API密码，不需要APISecret
SPARK_HTTP_API_PASSWORD = "ONamSSewOPIZPYijlDEl:KQzwHmytwjcZhgzbfDvi"  # 请替换为你的实际API密码

# 星火大模型API Secret，用于HMAC签名认证
SPARK_HTTP_API_SECRET = "YmRkZDAxYzQyYzNlMmY1NzY0ZWRjNTBh"  # 请替换为你的实际API Secret

# 星火大模型API Key，用于Authorization头
SPARK_HTTP_API_KEY = "c89245430c89fcb1d6111725dfc7f4ca"  # 请替换为你的实际API Key

# 指定你使用的模型版本（例如 x1 等）
# 请根据你的实际使用和开通情况选择
SPARK_MODEL_VERSION = "x1"  # 使用正确的模型名称

# --- 讯飞语音听写（ASR）API 凭证 ---
# 请替换为你从讯飞控制台获取的实际凭证
XFYUN_ASR_APPID = "dde81f6b"
XFYUN_ASR_API_SECRET = "YmRkZDAxYzQyYzNlMmY1NzY0ZWRjNTBh"
XFYUN_ASR_API_KEY = "c89245430c89fcb1d6111725dfc7f4ca"
ASR_FINAL_RESULT_TIMEOUT = 20

# --- 讯飞语音合成（TTS）API 凭证 ---
# 请替换为你从讯飞控制台获取的实际凭证
XFYUN_TTS_APPID = "dde81f6b" # <<< 请务必替换为你的真实 TTS AppID
XFYUN_TTS_API_SECRET = "YmRkZDAxYzQyYzNlMmY1NzY0ZWRjNTBh" # <<< 请务必替换为你的真实 TTS APISecret
XFYUN_TTS_API_KEY = "c89245430c89fcb1d6111725dfc7f4ca" # <<< 请务必替换为你的真实 TTS APIKey

# 推荐的语音发音人（例如"xiaoyan", "aisxrjing"等），具体可在讯飞TTS文档查看和体验
XFYUN_TTS_VOICE_NAME = "x4_xiaoyan" 

# TTS 音频编码格式 (对应业务参数 business.aue)
# 例如： "raw" (PCM), "lame" (MP3)
# 注意：PyAudio 通常直接处理 PCM 数据，因此 "raw" 是常见选择。
# 如果选择 "lame" 等压缩格式，你需要额外的库来解码。
XFYUN_TTS_AUE_FORMAT = "raw" 

# TTS 音频采样率 (对应业务参数 business.auf)
# 例如： "16000" (16k), "8000" (8k)
XFYUN_TTS_AUF_RATE = "16000"

# --- 流式ASR配置 ---
# 音频输入设备索引
AUDIO_INPUT_DEVICE_INDEX = 1

# --- 视频处理配置 ---
CAMERA_INDEX = 0  # 摄像头索引，0 通常是默认摄像头
VIDEO_RESOLUTION = (640, 480)  # 视频分辨率 (宽度, 高度)
VIDEO_FPS = 30  # 视频帧率
VIDEO_OUTPUT_DIR = "video_records" # 视频录制文件保存目录

# --- 面试配置 ---
# 面试问题总数
INTERVIEW_TOTAL_QUESTIONS = 3

# ASR连续失败最大次数
ASR_MAX_FAILURES = 2

# ASR超时时间（秒）
ASR_TIMEOUT = 15.0

# TTS等待超时时间（秒）
TTS_WAIT_TIMEOUT = 10.0

# --- 日志配置 ---
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

# --- 性能配置 ---
# 线程健康检查间隔（秒）
THREAD_HEALTH_CHECK_INTERVAL = 1.0

# --- 错误处理配置 ---
# 是否启用自动恢复
ENABLE_AUTO_RECOVERY = True

# 恢复尝试次数
RECOVERY_MAX_ATTEMPTS = 3

# 恢复间隔（秒）
RECOVERY_INTERVAL = 2.0