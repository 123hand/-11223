# interview_logic.py

import logging
import time
import threading
from config import ASR_FINAL_RESULT_TIMEOUT 
import re

class InterviewLogic:
    def __init__(self, *,
                 asr_client,
                 tts_client,
                 spark_client,
                 voice_analyzer,
                 response_audio_q,
                 tts_current_playing_lock,
                 is_asr_listening,
                 audio_stream_should_open_event=None,
                 audio_stream_opened_event=None,
                 **kwargs):
        self.spark_client = spark_client
        self.tts_client = tts_client
        self.asr_client = asr_client
        self.voice_analyzer = voice_analyzer
        self.stop_event = kwargs.get('stop_event') # 用于控制面试逻辑线程的停止

        # 从 app.py 传递过来的全局事件和队列
        self.tts_play_event = kwargs.get('tts_play_event')
        self.response_audio_q = response_audio_q
        self.tts_current_playing_lock = tts_current_playing_lock
        self.is_asr_listening = is_asr_listening # 用于标记 ASR 是否正在监听用户
        logging.info(f"InterviewLogic: is_asr_listening对象id: {id(self.is_asr_listening)}")

        self.interview_state = "INITIAL" # 面试状态：INITIAL -> QUESTIONING -> ENDED
        self.current_question = ""
        self.total_questions = 3 # 假设有3个问题
        self.question_count = 0 # 提问计数，0表示未开始正式提问
        self.conversation_history = [] 
        self.audio_stream_should_open_event = audio_stream_should_open_event
        self.audio_stream_opened_event = audio_stream_opened_event
        self.system_prompt = (
    "你现在是一个专业的AI面试官，正在进行一场真实的面试。请严格按照以下要求：\n"
    "1. 面试目标：全面考察候选人的专业知识水平、技能匹配度、语言表达能力、逻辑思维能力、创新能力、应变抗压能力。\n"
    "2. 面试流程：每轮只问一个问题，不要进行中间评价，让面试更自然流畅。\n"
    "3. 问题设计：根据候选人的回答和简历，动态生成下一个有针对性的问题，逐步深入考察各个维度。\n"
    "4. 面试结束：当你认为已经充分考察了候选人的各项能力，或者已经问了足够多的问题时，主动说'面试结束'并礼貌告别。\n"
    "5. 输出格式：只输出下一个问题，不要评价，不要一次性输出多个问题。\n"
    "请记住：这是一场真实的面试，保持专业、自然、流畅的对话节奏。"
)
        self.conversation_history.append({"role": "system", "content": self.system_prompt})
        logging.info("InterviewLogic 初始化完成。")
        self.last_question = ""  # 新增，消除Pylance报错

    def start_interview(self):
        logging.info("开始面试流程...")
        try:
            self.say_hello() # 面试官打招呼 (这是第一次播放)
            self.is_asr_listening.set()

            if self.stop_event is not None and self.stop_event.is_set():
                logging.info("面试流程在开始前被停止。")
                return

            while (self.stop_event is None or not self.stop_event.is_set()) and self.interview_state != "ENDED":
                logging.info(f"当前面试状态: {self.interview_state}, 已提问数量: {self.question_count}/{self.total_questions}")

                # 新顺序：先等待ASR连接，再TTS提示，再激活ASR监听
                wait_count = 0
                while not self.asr_client.is_connected and wait_count < 10:
                    logging.warning("ASR未连接，等待重连...")
                    time.sleep(0.5)
                    wait_count += 1
                if not self.asr_client.is_connected:
                    logging.error("ASR重连失败，跳过本轮提问。")
                    continue

                # TTS"请开始回答"前：恢复采集流并等待确认
                if hasattr(self, 'audio_stream_should_open_event') and hasattr(self, 'audio_stream_opened_event'):
                    if self.audio_stream_should_open_event is not None:
                        self.audio_stream_should_open_event.set()
                    logging.info("主流程：TTS前已通知采集线程恢复音频流，等待采集线程确认...")
                    wait_audio_open = 0
                    while (self.audio_stream_opened_event is not None and not self.audio_stream_opened_event.is_set()) and wait_audio_open < 40:
                        time.sleep(0.05)
                        wait_audio_open += 1
                    if self.audio_stream_opened_event is not None and not self.audio_stream_opened_event.is_set():
                        logging.warning("采集线程音频流恢复超时，可能存在冲突。")

                logging.info("请开始回答（ASR即将激活）")
                self.tts_current_playing_lock.acquire()
                try:
                    self._play_tts_response("请开始回答")
                    logging.info("TTS播报已调用完成（请开始回答）")
                except Exception as e:
                    logging.error(f"TTS播报异常: {e}")
                self.tts_current_playing_lock.release()
                self.is_asr_listening.set() # TTS播报后再激活ASR监听
                logging.info("TTS播报结束，ASR监听已激活")

                self.asr_client.final_result_received_event.clear()
                
                logging.info("面试官提问完毕，激活 ASR 监听用户回答...")
                # 新增：TTS播报提示词（去除重复）
                # try:
                #     self._play_tts_response("请开始回答")
                #     logging.info("TTS播报已调用完成（请开始回答）")
                # except Exception as e:
                #     logging.error(f"TTS播报异常: {e}")

                ASR_TIMEOUT_EXTENDED = ASR_FINAL_RESULT_TIMEOUT + 5
                logging.info(f"等待用户回答，超时时间: {ASR_TIMEOUT_EXTENDED} 秒...")
                
                max_retries = 3
                retry_count = 0
                valid_answer_received = False
                user_answer = None
                
                while retry_count < max_retries and not valid_answer_received and not (self.stop_event is not None and self.stop_event.is_set()):
                    if self.asr_client.final_result_received_event is not None and not self.asr_client.final_result_received_event.wait(timeout=ASR_TIMEOUT_EXTENDED):
                        retry_count += 1
                        logging.warning(f"面试逻辑等待用户回答超时 ({ASR_TIMEOUT_EXTENDED}s)，第{retry_count}次重试")
                        self.is_asr_listening.clear()  # 超时后立即关闭ASR监听，防止采集线程一直工作
                        if retry_count >= max_retries:
                            logging.warning(f"用户回答重试次数已达上限({max_retries}次)，跳过当前问题")
                            if self.interview_state == "INITIAL":
                                self._play_tts_response("抱歉，我没有听清楚您的自我介绍。请您重新进行自我介绍。")
                            else:
                                self._play_tts_response("抱歉，我没有听清楚您的回答。请您重新回答这个问题。")
                            break
                        else:
                            continue
                    else:
                        # 收到了ASR结果，但需要检查是否有效
                        if hasattr(self.asr_client, 'invalid_result_received') and self.asr_client.invalid_result_received:
                            logging.warning("收到无效的ASR结果，继续等待有效回答")
                            valid_answer_received = False
                            self.asr_client.invalid_result_received = False
                            self.is_asr_listening.clear()  # 收到无效结果后也关闭ASR监听
                            continue
                        else:
                            valid_answer_received = True
                            self.is_asr_listening.clear()  # 收到有效结果后关闭ASR监听
                            user_answer = self.asr_client.final_result
                            logging.info("用户回答已收到并处理。")
                            break
                if self.stop_event is not None and self.stop_event.is_set():
                    logging.info("收到停止事件，面试循环退出。")
                    break
                # 新增：收到有效回答后，立即推进面试流程
                if valid_answer_received and user_answer:
                    self.process_human_input(user_answer)
                time.sleep(0.5)

            if (self.stop_event is None or not self.stop_event.is_set()) and self.interview_state == "ENDED":
                logging.info("面试流程已自然结束。")
                self.say_goodbye()
            elif self.stop_event is not None and self.stop_event.is_set():
                logging.info("面试流程因外部停止事件而结束。")

        except Exception as e:
            logging.critical(f"面试逻辑线程发生严重错误: {e}", exc_info=True)
        finally:
            self.is_asr_listening.clear()  # 确保流程结束时关闭ASR监听
            logging.info("面试流程结束。")
            if self.stop_event is not None:
                self.stop_event.set() # 确保面试逻辑结束时设置停止事件

    def say_hello(self):
        logging.info("面试官：您好，欢迎参加本次面试。请先进行简单的自我介绍。")
        greeting_text = "您好，欢迎参加本次面试。请先进行简单的自我介绍。"
        self.current_question = greeting_text 
        self._play_tts_response(greeting_text)
        self.interview_state = "QUESTIONING"  # 自我介绍后进入提问阶段
        self.conversation_history.append({"role": "assistant", "content": greeting_text})  # 新增，确保历史中有AI的提问

    def ask_question(self):
        # 此方法在当前设计中不再直接生成和播放问题，
        # 问题由 Spark 生成，并在 process_human_input 中播放。
        pass

    def listen_for_answer(self):
        # 这个方法似乎未被直接调用，逻辑已集成到 start_interview 和 process_human_input 中
        self.asr_client.final_result_received_event.clear()
        logging.info("等待用户回答...")
        self.is_asr_listening.set()


    def process_human_input(self, text_input):
        logging.info(f"进入process_human_input，收到文本: {text_input}")
        try:
            if not text_input or not text_input.strip():
                logging.warning(f"用户回答无效（为空或全是空格）: '{text_input}'，继续等待用户回答")
                return
            self.current_answer = text_input.strip()
            logging.info(f"面试逻辑收到用户回答: {self.current_answer}")
            self.conversation_history.append({"role": "user", "content": self.current_answer})

            # 只用 system prompt + history，不再拼接固定问题
            temp_messages_for_spark = [
                {"role": "system", "content": self.system_prompt}
            ] + [msg for msg in self.conversation_history if msg["role"] != "system"]

            logging.info(f"发送给Spark的消息: {temp_messages_for_spark}")
            try:
                response = self.spark_client.send_message(temp_messages_for_spark)
                logging.info(f"Spark模型回复: {response}")
            except Exception as e:
                logging.error(f"Spark模型调用异常: {e}", exc_info=True)
                response = None

            if response:
                if isinstance(response, dict):
                    spark_reply = response.get("content", "")
                else:
                    spark_reply = response
                
                # 检查AI是否主动结束面试
                if "面试结束" in spark_reply:
                    logging.info("AI主动结束面试")
                    self.interview_state = "ENDED"
                    self._play_tts_response(spark_reply)
                    self.conversation_history.append({"role": "assistant", "content": spark_reply})
                    return spark_reply
                
                logging.info(f"调用TTS播报: {spark_reply}")
                self._play_tts_response(spark_reply)
                self._play_tts_response("请开始回答")
                self.is_asr_listening.set()
                logging.info("TTS全部播报完毕，ASR监听已激活，考生可开始作答")
                self.conversation_history.append({"role": "assistant", "content": spark_reply})
                return spark_reply
            else:
                logging.warning("未能从 Spark 模型获取回复，TTS播报提示用户")
                try:
                    self._play_tts_response("对不起，我暂时无法生成回复，请稍后再试。")
                    logging.info("TTS播报已调用完成（异常提示）")
                except Exception as e:
                    logging.error(f"TTS播报异常: {e}", exc_info=True)
                return "对不起，我暂时无法生成回复。"
        except Exception as e:
            logging.critical(f"process_human_input发生严重错误: {e}", exc_info=True)

    def say_goodbye(self):
        logging.info("面试官：感谢您的参与，本次面试结束。祝您一切顺利！")
        goodbye_text = "感谢您的参与，本次面试结束。祝您一切顺利！"
        self._play_tts_response(goodbye_text)

    def process_user_answer(self, user_text):
        """处理用户回答，整理成更清晰的内容"""
        try:
            if not user_text or not user_text.strip():
                return "未提供有效回答"
            
            # 使用AI整理用户的回答
            prompt = (
                "你是面试AI助手。请将用户的原始回答进行专业、流畅的整理，只输出整理后的面试回答，不要输出任何说明、处理过程或分析。"
                "请严格基于用户原始回答，不得添加、虚构或编造任何未出现的信息。"
                "输出格式示例：\n整理后的面试回答：xxx\n"
                "用户原始回答：\n" + user_text.strip()
            )
            
            messages = [{"role": "user", "content": prompt}]
            processed_text = self.spark_client.send_message(messages)
            
            logging.info(f"用户原始回答: {user_text}")
            logging.info(f"AI整理后回答: {processed_text}")
            
            # 只保留“整理后的面试回答：”前面的内容，去掉“说明：...”等
            clean_text = processed_text
            # 去掉“说明：”及其后内容
            clean_text = re.split(r'[（(]说明[:：]', clean_text)[0].strip()
            # 去掉“整理后的面试回答：”前缀
            clean_text = re.sub(r'^整理后的面试回答[:：]\s*', '', clean_text)
            return clean_text
            
        except Exception as e:
            logging.error(f"处理用户回答时发生错误: {e}")
            # 如果AI处理失败，返回原始回答
            return user_text.strip()

    def _play_tts_response(self, text):
        if not self.tts_client:
            logging.error("TTS 客户端未初始化，无法播放语音。")
            return
        logging.info(f"请求 TTS 合成文本: '{text}'")
        try:
            self.tts_client.synthesize_and_play(text)
            # 等待TTS音频真正播放完毕
            if hasattr(self.tts_client, 'playback_finished_event'):
                logging.info("等待TTS音频真正播放完毕...")
                self.tts_client.playback_finished_event.wait(timeout=15)  # 最多等15秒
                logging.info("TTS音频已真正播放完毕。")
            else:
                # 兼容老版本
                while self.tts_client.is_playing():
                    time.sleep(0.1)
            logging.info("TTS 播放完成。")
        except Exception as e:
            logging.error(f"TTS 播放失败: {e}", exc_info=True)