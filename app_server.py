from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
import threading
import queue
import logging
from xfyun_spark_client import SparkClient
from xfyun_tts_client import XfyunTTSClient
from xfyun_asr_client import XfyunASRClient
from voice_analyzer import VoiceAnalyzer
from interview_logic import InterviewLogic
from config import (
    SPARK_HTTP_API_PASSWORD,
    SPARK_MODEL_VERSION,
    XFYUN_ASR_APPID,
    XFYUN_ASR_API_SECRET,
    XFYUN_ASR_API_KEY,
    XFYUN_TTS_APPID,
    XFYUN_TTS_API_KEY,
    XFYUN_TTS_API_SECRET,
    XFYUN_TTS_VOICE_NAME,
    XFYUN_TTS_AUE_FORMAT,
    XFYUN_TTS_AUF_RATE
)
import cv2
import numpy as np
import base64
from deepface import DeepFace
import interview_evaluation_api
from flask import session as flask_session
from flask import copy_current_request_context

app = Flask(__name__)

# 注册面试评测路由
app.add_url_rule('/api/interview/result', 'interview_evaluation', interview_evaluation_api.interview_evaluation, methods=['POST'])
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', logger=True, engineio_logger=True)

# 初始化各组件
asr_client = XfyunASRClient(
    app_id=XFYUN_ASR_APPID,
    api_key=XFYUN_ASR_API_KEY,
    api_secret=XFYUN_ASR_API_SECRET
)
# 不在启动时连接ASR，而是在需要时连接
logging.info("ASR客户端初始化完成，将在需要时连接")

tts_current_playing_lock = threading.Lock()
tts_client = XfyunTTSClient(
    app_id=XFYUN_TTS_APPID,
    api_key=XFYUN_TTS_API_KEY,
    api_secret=XFYUN_TTS_API_SECRET,
    voice_name=XFYUN_TTS_VOICE_NAME,
    aue_format=XFYUN_TTS_AUE_FORMAT,
    auf_rate=XFYUN_TTS_AUF_RATE,
    tts_current_playing_lock=tts_current_playing_lock
)
tts_client.connect()

spark_client = SparkClient(
    api_password=SPARK_HTTP_API_PASSWORD,
    model_version=SPARK_MODEL_VERSION
)

voice_analyzer = VoiceAnalyzer()
response_audio_q = queue.Queue()
is_asr_listening = threading.Event()
stop_event = threading.Event()  # 显式传入stop_event
audio_stream_should_open_event = threading.Event()
audio_stream_opened_event = threading.Event()

# 全局存储每个session的音频数据
session_audio_data = {}
# 全局保存所有轮次的语音分析
all_audio_analysis = []

# 全局模拟用户信息（实际可用数据库/登录系统）
user_info = {
    'nickname': '未命名用户',
    'avatar_url': '',
    'email': '',
    'phone': ''
}

# 全局面试会话对象
session = InterviewLogic(
    asr_client=asr_client,
    tts_client=tts_client,
    spark_client=spark_client,
    voice_analyzer=voice_analyzer,
    response_audio_q=response_audio_q,
    tts_current_playing_lock=tts_current_playing_lock,
    is_asr_listening=is_asr_listening,
    stop_event=stop_event,
    audio_stream_should_open_event=audio_stream_should_open_event,
    audio_stream_opened_event=audio_stream_opened_event
)

audio_queue = queue.Queue()
# audio_frames = []  # 当前轮次的音频帧
# all_round_audio_analysis = []  # 存储所有轮次的语音分析结果
result_queue = queue.Queue()
asr_result_queue = queue.Queue()

# ========== RESTful API ==========
@app.route('/api/interview/start', methods=['POST'])
def start_interview():
    logging.info("收到/api/interview/start请求，准备启动主流程线程")
    stop_event.clear()
    threading.Thread(target=interview_main_loop, daemon=True).start()
    return jsonify({"question": "您好，欢迎参加本次面试。请先进行简单的自我介绍。"})

@app.route('/api/interview/next', methods=['POST'])
def next_question():
    return jsonify({"question": "请开始回答下一个问题。"})

@app.route('/api/interview/stop', methods=['POST'])
def stop_interview():
    if not stop_event.is_set():
        stop_event.set()
        socketio.emit('interview_force_stop')
    return jsonify({"msg": "面试已结束"})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/test_spark', methods=['GET'])
def test_spark():
    try:
        result = spark_client.send_message([{"role": "user", "content": "你好，请自我介绍一下。"}])
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/face_emotion', methods=['POST'])
def face_emotion():
    data = request.json
    img_data = data['image'].split(',')[1]
    img_bytes = base64.b64decode(img_data)
    nparr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    # 表情分析
    try:
        result = DeepFace.analyze(img, actions=['emotion'], enforce_detection=False)
        logging.info(f"DeepFace.analyze 返回: {result}")
        if isinstance(result, list):
            if len(result) > 0 and isinstance(result[0], dict):
                emotion = result[0].get('dominant_emotion', 'unknown')
            else:
                emotion = 'unknown'
        elif isinstance(result, dict):
            emotion = result.get('dominant_emotion', 'unknown')
        else:
            emotion = 'unknown'
    except Exception as e:
        logging.error(f"DeepFace.analyze 异常: {e}", exc_info=True)
        emotion = "unknown"

    return jsonify({
        "emotion": emotion
    })

@app.route('/api/generate_resume', methods=['POST'])
def generate_resume():
    data = request.json
    prompt = (
        f"请根据以下信息帮我生成一份完整的中文简历，内容包括个人信息、教育背景、技能、项目经历和自我评价，要求简洁专业：\n"
        f"姓名：{data.get('name','')}\n"
        f"学校：{data.get('school','')}\n"
        f"专业：{data.get('major','')}\n"
        f"技能：{data.get('skills','')}\n"
        f"项目经历：{data.get('project','')}\n"
        f"自我评价：{data.get('selfIntro','')}"
    )
    try:
        print("【简历生成Prompt】", prompt)
        messages = [
            {"role": "user", "content": prompt}
        ]
        result = spark_client.send_message(messages)
        print("【简历生成结果】", result)
        return jsonify({'resume': result})
    except Exception as e:
        print("【简历生成异常】", e)
        return jsonify({'resume': '', 'error': str(e)})

@app.route('/api/exam_questions', methods=['GET'])
def get_exam_questions():
    # 题库写死
    questions = {
        '人工智能': [
            {'id': 1, 'question': '请简述深度学习与传统机器学习的主要区别。'},
            {'id': 2, 'question': '什么是卷积神经网络（CNN），它主要应用于哪些场景？'},
            {'id': 3, 'question': '请解释什么是过拟合，并简要说明常用的防止过拟合的方法。'}
        ],
        '大数据': [
            {'id': 4, 'question': '请简述Hadoop和Spark的主要区别。'},
            {'id': 5, 'question': '什么是MapReduce？请描述其基本原理。'},
            {'id': 6, 'question': '请说明数据湖和数据仓库的区别。'}
        ],
        '物联网': [
            {'id': 7, 'question': '请简述物联网（IoT）的基本架构。'},
            {'id': 8, 'question': '什么是MQTT协议？它适合哪些应用场景？'},
            {'id': 9, 'question': '请说明边缘计算在物联网中的作用。'}
        ],
        '智能系统': [
            {'id': 10, 'question': '请简述智能控制系统的基本组成。'},
            {'id': 11, 'question': '什么是专家系统？请举例说明其应用。'},
            {'id': 12, 'question': '请说明模糊控制的基本思想及其应用场景。'}
        ]
    }
    return {'questions': questions}

@app.route('/api/exam_review', methods=['POST'])
def exam_review():
    data = request.get_json()
    field = data.get('field')
    question = data.get('question')
    answer = data.get('answer')
    # 构造prompt
    prompt = f"你是一名{field}领域的面试官，请对下面的笔试题作答进行专业、详细的批改，指出优点、不足，并给出改进建议。\n题目：{question}\n考生答案：{answer}\n请用中文输出批改意见。"
    from xfyun_spark_client import SparkClient, SPARK_HTTP_API_PASSWORD, SPARK_MODEL_VERSION
    spark_client = SparkClient(api_password=SPARK_HTTP_API_PASSWORD, model_version=SPARK_MODEL_VERSION)
    messages = [
        {"role": "user", "content": prompt}
    ]
    review = spark_client.send_message(messages)
    return {'review': review or '批改失败，请稍后重试。'}

@app.route('/api/user_info', methods=['GET', 'POST'])
def user_info_api():
    global user_info
    if request.method == 'GET':
        return user_info
    elif request.method == 'POST':
        data = request.get_json()
        for k in ['nickname', 'avatar_url', 'email', 'phone']:
            if k in data:
                user_info[k] = data[k]
        return {'success': True, 'user_info': user_info}

# ========== WebSocket 音频流转发 ==========
@socketio.on('connect')
def handle_connect():
    print(f"【WebSocket】客户端连接: {request.sid}")
    # 初始化该session的音频数据
    session_audio_data[request.sid] = {
        'audio_frames': [],
        'all_round_audio_analysis': []
    }

def delayed_cleanup(sid, delay=300):
    import time
    time.sleep(delay)
    if sid in session_audio_data:
        del session_audio_data[sid]
        print(f"【清理】延迟删除session音频数据: {sid}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"【WebSocket】客户端断开: {request.sid}")
    # 延迟5分钟后清理session数据
    threading.Thread(target=delayed_cleanup, args=(request.sid,), daemon=True).start()

@socketio.on('audio_stream')
def handle_audio_stream(data):
    if isinstance(data, bytes):
        # 只有在ASR监听时才收集音频帧（即用户正在回答时）
        # 使用session中的is_asr_listening，而不是全局的
        if session.is_asr_listening.is_set():
            # 限制音频帧数量，避免内存泄漏
            sid = request.sid
            if sid not in session_audio_data:
                session_audio_data[sid] = {'audio_frames': [], 'all_round_audio_analysis': []}
            audio_frames = session_audio_data[sid]['audio_frames']
            if len(audio_frames) < 1000:  # 最多保存1000帧
                audio_frames.append(data)  # 收集当前轮次的音频帧
                audio_queue.put(data)  # 发送到ASR队列
                print(f"【音频流】✅ 收到音频数据，长度: {len(data)} 字节，当前累积帧数: {len(audio_frames)}")
            else:
                print(f"【音频流】⚠️ 音频帧数量过多({len(audio_frames)})，跳过新帧")
        else:
            print(f"【音频流】❌ ASR未监听，跳过音频数据，长度: {len(data)} 字节，session.is_asr_listening状态: {session.is_asr_listening.is_set()}")
    else:
        print(f"❌ 收到无效音频数据，类型为: {type(data)}, 内容: {data}")

# 添加一个调试路由来检查音频帧状态
@app.route('/api/debug/audio_frames', methods=['GET'])
def debug_audio_frames():
    sid = request.args.get('sid') or request.cookies.get('sid')
    if not sid or sid not in session_audio_data:
        return jsonify({
            'frame_count': 0,
            'total_size': 0,
            'global_is_asr_listening': is_asr_listening.is_set(),
            'session_is_asr_listening': False,
            'all_round_audio_analysis_count': 0,
            'all_round_audio_analysis': []
        })
    audio_frames = session_audio_data[sid]['audio_frames']
    return jsonify({
        'frame_count': len(audio_frames),
        'total_size': sum(len(frame) for frame in audio_frames) if audio_frames else 0,
        'global_is_asr_listening': is_asr_listening.is_set(),
        'session_is_asr_listening': session.is_asr_listening.is_set(),
        'all_round_audio_analysis_count': len(session_audio_data[sid]['all_round_audio_analysis']),
        'all_round_audio_analysis': session_audio_data[sid]['all_round_audio_analysis']
    })

# 新增：开始/结束回答事件
@socketio.on('start_answer')
def handle_start_answer():
    asr_client.start_accumulate()
    logging.info('收到start_answer，已重置累积内容')

@socketio.on('end_answer')
def handle_end_answer():
    print("【调试】handle_end_answer 被调用")
    sid = request.sid
    audio_frames = session_audio_data.get(sid, {}).get('audio_frames', [])
    print(f"【调试】audio_frames 长度: {len(audio_frames)}")
    if audio_frames:
        # 发送ASR结束帧
        try:
            asr_client.send_end_frame()
            print("【ASR】发送结束帧")
        except Exception as e:
            print(f"【ASR】发送结束帧失败: {e}")
        
        # 同步分析当前轮次的音频，确保分析完成
        if audio_frames:
            print(f"【语音分析】开始分析当前轮次音频，帧数: {len(audio_frames)}")
            # 复制音频帧，避免在分析过程中被修改
            frames_copy = audio_frames.copy()
            
            try:
                audio_path = voice_analyzer.save_audio(frames_copy, filename=f"round_{len(all_audio_analysis)+1}_audio.wav")
                
                if audio_path:
                    audio_features = voice_analyzer.analyze_audio_features(audio_path)
                    if audio_features:
                        print(f'【调试】audio_features: {audio_features}')
                        # 记录当前轮次的语音分析结果
                        session_audio_data[sid]['all_round_audio_analysis'].append({'features': audio_features})
                        # 新增：将本轮语音分析结果通过answer_result事件返回给前端
                        audio_analysis_text = f"响度: {audio_features.get('loudness_db', '无'):.2f} dB，时长: {audio_features.get('duration_seconds', '无'):.2f}秒，音高: {audio_features.get('average_pitch_hz', '无'):.2f} Hz，情感: {audio_features.get('estimated_emotional_tone', '无')}"
                        all_audio_analysis.append(audio_analysis_text) # 新增：将分析文本添加到全局列表
                        socketio.emit('answer_result', {'audio_analysis': audio_analysis_text}, to=sid)
                    else:
                        print("【语音分析】当前轮次音频分析失败")
                else:
                    print("【语音分析】当前轮次音频保存失败")
            except Exception as e:
                print(f"【语音分析】分析异常: {e}")
        else:
            print('【调试】当前轮次没有音频数据')
            socketio.emit('answer_result', {'audio_analysis': '无语音分析数据'}, to=sid)
    else:
        print("【语音分析】当前轮次没有音频数据")
        socketio.emit('answer_result', {'audio_analysis': '无语音分析数据'}, to=sid)
    
    # 清空当前轮次的音频帧，准备下一轮
    audio_frames.clear()
    
    result = asr_client.get_accumulated_result()
    logging.info(f'收到end_answer，返回累积内容: {result}')
    socketio.emit('answer_result', {'text': result}, to=sid)

# 处理用户回答事件
@socketio.on('user_answer')
def handle_user_answer(data):
    if stop_event.is_set():
        logging.info("面试已终止，忽略用户回答")
        return
    user_text = data.get('text', '')
    logging.info(f"收到用户回答: {user_text}")

    # 获取上一个问题
    last_question = getattr(session, 'last_question', '请再试一次回答本题')

    if not user_text or not user_text.strip():
        logging.warning("用户回答为空，自动重复上一个问题")
        # 1. 反馈“未检测到有效回答”
        socketio.emit('ai_feedback', {'text': '未检测到有效回答，请再试一次'})
        # 2. 重新发送上一个问题
        socketio.emit('ai_question', {'text': last_question})
        # 3. 允许前端再次作答
        session.is_asr_listening.set()
        socketio.emit('can_answer', {})
        return

    # 先让AI处理用户的回答，整理成更清晰的内容
    processed_answer = session.process_user_answer(user_text)

    # 如果面试已终止（如点击了结束面试），只反馈整理后的内容和结束语，不再AI提问
    if stop_event.is_set():
        logging.info("面试已终止，最后反馈整理后的内容和结束语")
        socketio.emit('ai_feedback', {
            'text': '面试已结束，感谢您的参与！',
            'processed_answer': processed_answer
        })
        return

    # 然后进行正常的AI面试流程
    ai_reply = session.process_human_input(user_text)
    # 保存本轮问题
    session.last_question = ai_reply if ai_reply else last_question
    if stop_event.is_set():
        logging.info("面试已终止，忽略AI提问")
        return
    if ai_reply:
        # 发送处理后的回答和AI反馈
        socketio.emit('ai_feedback', {
            'text': '回答已记录，请继续',
            'processed_answer': processed_answer
        })
        socketio.emit('ai_question', {'text': ai_reply})
        session.is_asr_listening.set()
        socketio.emit('can_answer', {})  # 通知前端可以开始下一轮回答
    else:
        # 面试结束
        logging.info("面试流程结束。")
        session._play_tts_response('面试已结束，感谢您的参与！')
        socketio.emit('ai_feedback', {
            'text': '面试已结束，感谢您的参与！',
            'processed_answer': processed_answer
        })

# asr_worker 只做音频帧推送

def asr_final_callback(result_dict, asr_client_instance):
    # 只要有最终结果就 set 事件
    asr_client_instance.final_result_received_event.set()
    
    # 记录日志
    result_type = result_dict.get('type', 'unknown')
    result_text = result_dict.get('text', '')
    logging.info(f"ASR最终结果回调: type={result_type}, text='{result_text}'")
    
    # 如果是自动结束的结果，也发送到前端
    if result_type == 'auto_final':
        socketio.emit('asr_result', {
            'text': result_text, 
            'is_final': True, 
            'feedback': '自动结束识别'
        })

def asr_interim_callback(result_dict, asr_client_instance):
    """处理ASR中间结果，实时发送到前端"""
    if result_dict.get('action') == 'partial' and result_dict.get('text'):
        # 发送中间结果到前端
        socketio.emit('asr_result', {
            'text': result_dict['text'], 
            'is_final': False, 
            'feedback': ''
        })
        logging.debug(f"发送ASR中间结果到前端: {result_dict['text']}")
        
        # 启动自动结束监控
        asr_client_instance._start_auto_finalize_monitor()

asr_client.set_callback(asr_final_callback)
asr_client.set_interim_result_callback(asr_interim_callback)

def asr_worker():
    import time
    asr_connected = False  # 标记ASR是否已连接
    connection_attempts = 0  # 连接尝试次数
    is_first_frame = True  # 标记是否是第一帧音频
    last_connection_time = 0  # 上次连接时间
    last_audio_time = 0  # 上次发送音频时间
    audio_buffer = []  # 音频缓冲区
    buffer_size = 5  # 缓冲区大小（帧数）
    
    while True:
        try:
            audio_data = audio_queue.get(timeout=0.1)  # 增加超时，避免无限等待
            if audio_data is None:
                continue
            
            current_time = time.time()
            
            # 如果ASR未连接，尝试连接（增加时间间隔避免频繁重连）
            if not asr_connected:
                if current_time - last_connection_time < 3:  # 减少到3秒内不重复连接
                    time.sleep(0.1)
                    continue
                    
                connection_attempts += 1
                last_connection_time = current_time
                
                try:
                    logging.info(f"ASR工作线程：第{connection_attempts}次尝试连接ASR客户端...")
                    print(f"【ASR连接】第{connection_attempts}次尝试连接...")
                    asr_client.connect()
                    asr_connected = True
                    logging.info("ASR工作线程：ASR客户端连接成功")
                    print("【ASR连接】连接成功！")
                    connection_attempts = 0  # 重置尝试次数
                    is_first_frame = True  # 重置第一帧标记
                    audio_buffer.clear()  # 清空缓冲区
                except Exception as e:
                    logging.error(f"ASR工作线程：连接失败: {e}", exc_info=True)
                    print(f"【ASR连接】连接失败: {e}")
                    if connection_attempts >= 3:  # 最多尝试3次
                        print("【ASR连接】连接失败次数过多，跳过ASR处理，继续收集音频数据")
                        # 不继续尝试连接，但继续处理音频数据用于语音分析
                        break
                    time.sleep(1)  # 减少等待时间到1秒
                    continue
            
            # 音频数据缓冲和批量发送
            audio_buffer.append(audio_data)
            
            # 当缓冲区满了或者距离上次发送超过200ms时发送数据
            if len(audio_buffer) >= buffer_size or (current_time - last_audio_time > 0.2):
                if is_first_frame:
                    # 第一帧发送开始信号
                    asr_client.send_audio(b''.join(audio_buffer), status=0)
                    print("【ASR】发送开始帧")
                    is_first_frame = False
                else:
                    # 后续帧发送音频数据
                    asr_client.send_audio(b''.join(audio_buffer), status=1)
                
                last_audio_time = current_time
                audio_buffer.clear()  # 清空缓冲区
                
        except queue.Empty:
            # 队列超时，检查是否需要自动结束
            if asr_connected and not is_first_frame and audio_buffer:
                # 发送剩余的缓冲数据
                asr_client.send_audio(b''.join(audio_buffer), status=1)
                audio_buffer.clear()
                
        except Exception as e:
            logging.error(f"ASR转发异常: {e}", exc_info=True)
            print(f"【ASR发送】发送音频数据失败: {e}")
            asr_connected = False  # 连接失败，重置连接状态
            audio_buffer.clear()  # 清空缓冲区
            time.sleep(0.1)

# 主流程线程：简化版本，只负责初始化和结束
def interview_main_loop():
    import time
    logging.info("interview_main_loop 线程已启动")
    # 1. AI打招呼
    greeting = "您好，欢迎参加本次面试。请先进行简单的自我介绍。"
    session._play_tts_response(greeting)
    socketio.emit('ai_question', {'text': greeting})
    session.last_question = greeting  # <--- 新增
    session.is_asr_listening.set()
    socketio.emit('can_answer', {})  # 通知前端可以作答

    # 等待面试结束
    while not stop_event.is_set():
            time.sleep(0.1)

    logging.info("面试流程结束。")
    session._play_tts_response('面试已结束，感谢您的参与！')
    socketio.emit('ai_question', {'text': '面试已结束，感谢您的参与！'})
    socketio.emit('ai_feedback', {'text': '面试已结束，感谢您的参与！'})

@socketio.on('interview_end')
def handle_interview_end():
    if not stop_event.is_set():
        stop_event.set()
        socketio.emit('interview_force_stop')

@app.route('/api/interview/result', methods=['POST'])
def interview_evaluation_route():
    data = request.get_json()
    print(f'收到 video_analysis: {data.get("video_analysis")}')
    print(f'收到 resume_text: {data.get("resume_text")}')
    # 直接用前端传来的audio_analysis
    audio_analysis = data.get('audio_analysis', '无语音分析数据')
    print(f'【语音分析】最终分析文本: {audio_analysis}')
    # 清空该session的数据
    # session_audio_data[sid]['audio_frames'].clear() # 不再需要清空音频帧
    # session_audio_data[sid]['all_round_audio_analysis'].clear() # 不再需要清空分析数据
    # data['audio_analysis'] = audio_analysis # 不再需要将分析结果放入data
    from interview_evaluation_api import interview_evaluation
    import flask
    with app.test_request_context(json=data):
        result = interview_evaluation()
    return result

@app.route('/api/get_audio_analysis', methods=['GET'])
def get_audio_analysis():
    return {'audio_analysis': all_audio_analysis}

# 启动ASR后台线程和主流程线程，必须放到主入口下
if __name__ == '__main__':
    print("【启动】正在启动ASR后台线程...")
    t = threading.Thread(target=asr_worker, daemon=True)
    t.start()
    logging.info("ASR后台线程已启动")
    print("【启动】ASR后台线程已启动")
    
    # 启动定期清理线程
    def cleanup_temp_files():
        import os
        import time
        import glob
        while True:
            try:
                # 清理超过1小时的临时音频文件
                audio_dir = "audio_records"
                if os.path.exists(audio_dir):
                    current_time = time.time()
                    for file_path in glob.glob(os.path.join(audio_dir, "*.wav")):
                        if os.path.getmtime(file_path) < current_time - 3600:  # 1小时前
                            os.remove(file_path)
                            print(f"【清理】删除过期音频文件: {file_path}")
                time.sleep(300)  # 每5分钟检查一次
            except Exception as e:
                print(f"【清理】清理线程异常: {e}")
                time.sleep(60)
    
    cleanup_thread = threading.Thread(target=cleanup_temp_files, daemon=True)
    cleanup_thread.start()
    print("【启动】临时文件清理线程已启动")
    
    print("【启动】正在启动Flask-SocketIO服务器...")
    # 只保留一次socketio.run()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
